from fastapi import APIRouter, Depends, HTTPException, Response, status, Path
from typing import Dict, List, Optional, Any
import logging
from google.cloud import bigquery
import supabase


from app.config import settings
from app.api.deps import get_current_user, get_bigquery_client
from app.services.cache_service import cache_service
from app.schemas.favorites import FavoritesResponse, FavoriteProduct, FavoriteResponse

router = APIRouter()

# Supabase client initialization function
def get_supabase_client():
    """Returns a Supabase client using the URL and key from settings."""
    try:
        client = supabase.create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        return client
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create Supabase client: {e}"
        )

@router.get("/", response_model=FavoritesResponse)
async def get_user_favorites(
    current_user: Dict = Depends(get_current_user),
    bq_client: bigquery.Client = Depends(get_bigquery_client),
    supabase_client = Depends(get_supabase_client)
) -> Dict:
    """
    Get all favorited products for the authenticated user.
    
    This endpoint retrieves the list of products that the user has added to their favorites.
    It requires user authentication with a valid token.
    """
    try:
        # Extract user ID from the JWT token
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required"
            )
        
        # Create a cache key specific to this user's favorites
        cache_key = f"user:{user_id}:favorites"
        
        # Try to get from cache first
        cached_data = cache_service.get(cache_key)
        # if cached_data:
        #     return cached_data
        
        # Get the user's favorites from Supabase
        # Note: The column is named "variant_id" but actually stores the product ID (shop_product_id)
        favorites_response = supabase_client.table("userfavorites") \
            .select("variant_id") \
            .eq("user_id", user_id) \
            .execute()
        
        if not favorites_response.data:
            # Return empty list if user has no favorites
            return {"favorites": []}
        
        # Extract product IDs from the response (column is named variant_id but contains shop_product_id)
        product_ids = [item["variant_id"] for item in favorites_response.data]
        
        # Query BigQuery for product details using the product IDs
        product_ids_str = ", ".join(str(id) for id in product_ids)
        query = f"""
        WITH LatestPrices AS (
            -- This CTE ensures we only get the most recent price for each variant
            SELECT variant_id, current_price, original_price, is_available, date_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
            QUALIFY ROW_NUMBER() OVER(PARTITION BY variant_id ORDER BY date_id DESC) = 1
        ),
        -- Get the best variant (highest price) for each product
        BestVariants AS (
            SELECT 
                v.shop_product_id,
                v.variant_id,
                ROW_NUMBER() OVER(PARTITION BY v.shop_product_id ORDER BY lp.current_price DESC) AS price_rank
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v
            JOIN LatestPrices lp ON v.variant_id = lp.variant_id
            WHERE v.shop_product_id IN ({product_ids_str})
        )
        SELECT
          bv.variant_id,
          sp.shop_product_id as id,
          sp.product_title_native as name,
          sp.brand_native as brand,
          COALESCE(c.category_name, 'Uncategorized') as category,
          lp.current_price as price,
          lp.original_price,
          lp.is_available,
          s.shop_name as retailer,
          s.contact_phone as retailer_phone,
          s.contact_whatsapp as retailer_whatsapp,
          pi.image_url as image,
          CASE
            WHEN lp.original_price > 0 AND lp.original_price > lp.current_price
            THEN ROUND(((lp.original_price - lp.current_price) / lp.original_price) * 100, 0)
            ELSE 0
          END as discount
        FROM BestVariants bv
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON bv.variant_id = v.variant_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON v.shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
        LEFT JOIN LatestPrices lp ON v.variant_id = lp.variant_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
        WHERE bv.price_rank = 1 -- Only get the highest price variant for each product
        AND sp.shop_product_id IN ({product_ids_str})
        """
        
        query_job = bq_client.query(query)
        results = [dict(row) for row in query_job.result()]
        
        # Format the response
        favorite_products = []
        for row in results:
            favorite_product = {
                "id": row["id"],
                "name": row["name"],
                "brand": row.get("brand"),
                "category": row.get("category", "Uncategorized"),
                "price": row["price"],
                "original_price": row.get("original_price"),
                "image": row.get("image"),
                "retailer": row["retailer"],
                "retailer_phone": row.get("retailer_phone"),
                "retailer_whatsapp": row.get("retailer_whatsapp"),
                "discount": row.get("discount", 0),
                "is_available": row.get("is_available", True),
                "variant_id": row["variant_id"]
            }
            favorite_products.append(favorite_product)
        
        response = {"favorites": favorite_products}
        
        # Cache the result for a short time (5 minutes)
        # Short cache time because favorites can change frequently
        cache_service.set(cache_key, response, 300)
        
        return response
        
    except Exception as e:
        logging.error(f"Error retrieving user favorites: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while retrieving favorites: {e}"
        )

@router.delete("/{product_id}/favorite", response_model=FavoriteResponse)
async def remove_from_favorites(
    product_id: int = Path(..., description="The ID of the product to unfavorite"),
    current_user: Dict = Depends(get_current_user),
    bq_client: bigquery.Client = Depends(get_bigquery_client),
    supabase_client = Depends(get_supabase_client)
) -> Dict:
    """
    Remove a product from the user's favorites.
    
    Requires authentication.
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required"
            )
        
        # First, get the variant ID for this product
        variant_query = f"""
        SELECT v.variant_id
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        WHERE sp.shop_product_id = {product_id}
        """
        
        variant_job = bq_client.query(variant_query)
        variant_results = list(variant_job.result())
        
        if not variant_results:
            raise HTTPException(
                status_code=404,
                detail=f"Product with ID {product_id} not found"
            )
        
        # Get all variant IDs for this product
        variant_ids = [row["variant_id"] for row in variant_results]
        
        # Remove from favorites
        delete_response = supabase_client.table("userfavorites") \
            .delete() \
            .eq("user_id", user_id) \
            .in_("variant_id", variant_ids) \
            .execute()
        
        return {
            "is_favorited": False,
            "message": "Product removed from favorites"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while removing from favorites: {e}"
        )