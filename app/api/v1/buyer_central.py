from fastapi import APIRouter, Depends, HTTPException, Query, Response, Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from google.cloud import bigquery
import supabase
from app.config import settings
from app.api.deps import get_current_user, get_bigquery_client, get_current_user_optional
from app.services.cache_service import cache_service

from app.schemas.buyer_central import (
    SearchProductsResponse,
    PriceComparisonResponse,
    BuyingGuidesResponse
)

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

# ---- Buyer Central Endpoints ----

@router.get("/search-products", response_model=SearchProductsResponse)
async def search_products(
    query: str = Query(..., description="The full product name to search for"),
    limit: int = Query(4, description="Maximum number of results to return", ge=1, le=5),
    category_id: Optional[int] = Query(None, description="Filter by category ID"),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Search for products by exact product name and find matching products across retailers.
    Returns a list of products with their retailer information, lowest price, and URLs.
    All returned products will be from the same category as the initially matched product.
    """
    # Cache key based on search parameters
    cache_key = f"buyer-central:search:{query}:{limit}:{category_id}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        # Prepare the query parameters
        query_params = [
            bigquery.ScalarQueryParameter("query", "STRING", query),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
        
        # Add category_id parameter only if it's provided
        if category_id is not None:
            query_params.append(bigquery.ScalarQueryParameter("category_id", "INT64", category_id))
        else:
            query_params.append(bigquery.ScalarQueryParameter("category_id", "INT64", None))
        
        # Create the BigQuery job config
        job_config = bigquery.QueryJobConfig(
            query_parameters=query_params
        )
        
        # BigQuery SQL implementation to search by full product name and find matching products
        sql = """
        WITH
          -- Get the initial product based on exact product name
          InitialProduct AS (
            SELECT
              sp.shop_product_id,
              sp.product_title_native,
              sp.brand_native,
              sp.product_url,
              c.category_name,
              c.category_id,
              sp.predicted_master_category_id,
              s.shop_name AS retailer,
              pm.match_group_id
            FROM
              `price-pulse-470211.warehouse.DimShopProduct` sp
            JOIN
              `price-pulse-470211.warehouse.DimCategory` c
              ON sp.predicted_master_category_id = c.category_id
            JOIN
              `price-pulse-470211.warehouse.DimShop` s
              ON sp.shop_id = s.shop_id  
            JOIN
              `price-pulse-470211.warehouse.FactProductMatch` pm
              ON sp.shop_product_id = pm.shop_product_id
            WHERE
              LOWER(sp.product_title_native) = LOWER(@query)
              OR LOWER(CONCAT(sp.brand_native, ' ', sp.product_title_native)) = LOWER(@query)
            LIMIT 1  -- Get the exact match only
          ),
          
          -- Find all matching products based on match_group_id from the initial product
          -- AND ensure they are from the same category as the initial product
          MatchingProducts AS (
            SELECT DISTINCT
              pm.match_group_id,
              pm.shop_product_id
            FROM
              `price-pulse-470211.warehouse.FactProductMatch` pm
            JOIN
              InitialProduct ip
              ON pm.match_group_id = ip.match_group_id
            JOIN
              `price-pulse-470211.warehouse.DimShopProduct` sp
              ON pm.shop_product_id = sp.shop_product_id
            WHERE
              -- Ensure the product is in the same category as the initial product
              sp.predicted_master_category_id = (SELECT predicted_master_category_id FROM InitialProduct LIMIT 1)
          ),
          
          -- Get all product details for matching products (already filtered by same category)
          ProductDetails AS (
            SELECT
              sp.shop_product_id,
              sp.product_title_native,
              sp.brand_native,
              sp.product_url,
              c.category_name,
              c.category_id,
              s.shop_name AS retailer,
              mp.match_group_id
            FROM
              `price-pulse-470211.warehouse.DimShopProduct` sp
            JOIN
              MatchingProducts mp
              ON sp.shop_product_id = mp.shop_product_id
            JOIN
              `price-pulse-470211.warehouse.DimCategory` c
              ON sp.predicted_master_category_id = c.category_id
            JOIN
              `price-pulse-470211.warehouse.DimShop` s
              ON sp.shop_id = s.shop_id
            JOIN
              InitialProduct ip
              ON c.category_id = ip.category_id -- Additional check to ensure same category
          ),

          -- Get image URLs for the products
          ProductImages AS (
            SELECT
              shop_product_id,
              image_url
            FROM
              `price-pulse-470211.warehouse.DimProductImage`
            WHERE
              sort_order = 1 -- Primary images only
          ),

          -- Get the latest available price date for each product
          LatestProductPriceDates AS (
            SELECT
              v.shop_product_id,
              MAX(pp.date_id) AS latest_date_id
            FROM
              `price-pulse-470211.warehouse.FactProductPrice` pp
            JOIN
              `price-pulse-470211.warehouse.DimVariant` v
              ON pp.variant_id = v.variant_id
            JOIN
              ProductDetails pd
              ON v.shop_product_id = pd.shop_product_id
            WHERE
              pp.is_available = TRUE
            GROUP BY
              v.shop_product_id
          ),
          
          -- Calculate the lowest price for each product when variants are available
          ProductPrices AS (
            SELECT
              v.shop_product_id,
              MIN(CASE 
                WHEN pp.current_price > 0 THEN pp.current_price 
                ELSE COALESCE(pp.original_price, 0) 
              END) AS lowest_price
            FROM
              `price-pulse-470211.warehouse.FactProductPrice` pp
            JOIN
              `price-pulse-470211.warehouse.DimVariant` v
              ON pp.variant_id = v.variant_id
            JOIN
              LatestProductPriceDates lpd
              ON v.shop_product_id = lpd.shop_product_id AND pp.date_id = lpd.latest_date_id
            WHERE
              pp.is_available = TRUE
            GROUP BY
              v.shop_product_id
          )

        -- Final result combining all data
        SELECT
          pd.shop_product_id AS id,
          pd.product_title_native AS name,
          pd.brand_native AS brand,
          pd.category_name AS category,
          pd.retailer AS retailer,
          COALESCE(pp.lowest_price, 0) AS currentPrice,
          pd.product_url AS productUrl,
          pi.image_url AS image
        FROM
          ProductDetails pd
        LEFT JOIN
          ProductImages pi
          ON pd.shop_product_id = pi.shop_product_id
        LEFT JOIN
          ProductPrices pp
          ON pd.shop_product_id = pp.shop_product_id
        WHERE
          (@category_id IS NULL OR pd.category_id = @category_id)
        ORDER BY
          pp.lowest_price IS NULL,
          pp.lowest_price ASC
        LIMIT
          @limit
        """
        
        # Execute query
        query_job = bq_client.query(sql, job_config=job_config)
        results = query_job.result()
        
        # Process results
        products = []
        for row in results:
            products.append({
                "id": row.id,
                "name": row.name,
                "brand": row.brand,
                "category": row.category,
                "retailer": row.retailer,
                "currentPrice": row.currentPrice,
                "productUrl": row.productUrl,
                "image": row.image
            })
        
        # Prepare the response
        response = {
            "success": True,
            "data": products,
            "timestamp": datetime.utcnow()
        }
        
        # Cache the results for 1 hour (as recommended in the guide)
        cache_service.set(cache_key, response, ttl_seconds=3600)
        
        return response
        
    except bigquery.exceptions.GoogleCloudError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Google BigQuery error during product search: {e}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid input parameter: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred during product search: {e}"
        )
        
@router.get("/price-comparison", response_model=PriceComparisonResponse)
async def price_comparison(
    product_ids: str = Query(..., description="Comma-separated list of product IDs"),
    limit: int = Query(5, description="Maximum number of retailers per product", ge=1, le=20),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Retrieve price comparison data across retailers for specific products.
    Returns a list of products with their retailer prices and price history.
    """
    # Cache key based on search parameters
    cache_key = f"buyer-central:price-comparison:{product_ids}:{limit}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        # Prepare the query parameters
        query_params = [
            bigquery.ScalarQueryParameter("product_ids", "STRING", product_ids),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
        
        # Create the BigQuery job config
        job_config = bigquery.QueryJobConfig(
            query_parameters=query_params
        )
        
        # BigQuery SQL following the provided implementation
        sql = """
        -- Parse product IDs from comma-separated string
        WITH 
          ProductIDs AS (
            SELECT CAST(value AS INT64) as product_id
            FROM UNNEST(SPLIT(@product_ids, ',')) as value
            WHERE TRIM(value) != ''
          ),
          
          -- Simplify the query to focus on getting product info first
          BasicProductInfo AS (
            SELECT 
              pm.match_group_id AS product_id,
              sp.product_title_native AS product_name,
              c.category_name,
              COUNT(v.variant_id) AS variant_count
            FROM 
              ProductIDs p
            JOIN
              `price-pulse-470211.warehouse.FactProductMatch` pm
              ON p.product_id = pm.match_group_id
            JOIN
              `price-pulse-470211.warehouse.DimShopProduct` sp
              ON pm.shop_product_id = sp.shop_product_id
            JOIN
              `price-pulse-470211.warehouse.DimCategory` c
              ON sp.predicted_master_category_id = c.category_id
            LEFT JOIN
              `price-pulse-470211.warehouse.DimVariant` v
              ON sp.shop_product_id = v.shop_product_id
            GROUP BY
              pm.match_group_id, 
              sp.product_title_native,
              c.category_name
          ),
          
          -- Latest prices
          ProductPrices AS (
            SELECT
              pm.match_group_id AS product_id,
              sp.product_title_native AS product_name,
              c.category_name,
              v.variant_id,
              s.shop_id AS retailer_id,
              s.shop_name AS retailer_name,
              pp.current_price AS price,
              pp.is_available,
              d.full_date AS price_date
            FROM
              ProductIDs p
            JOIN
              `price-pulse-470211.warehouse.FactProductMatch` pm
              ON p.product_id = pm.match_group_id
            JOIN
              `price-pulse-470211.warehouse.DimShopProduct` sp
              ON pm.shop_product_id = sp.shop_product_id
            JOIN
              `price-pulse-470211.warehouse.DimCategory` c
              ON sp.predicted_master_category_id = c.category_id
            JOIN
              `price-pulse-470211.warehouse.DimVariant` v
              ON sp.shop_product_id = v.shop_product_id
            JOIN
              `price-pulse-470211.warehouse.DimShop` s
              ON sp.shop_id = s.shop_id
            JOIN
              `price-pulse-470211.warehouse.FactProductPrice` pp
              ON v.variant_id = pp.variant_id
            JOIN
              `price-pulse-470211.warehouse.DimDate` d
              ON pp.date_id = d.date_id
            WHERE
              pp.date_id = (
                SELECT MAX(date_id)
                FROM `price-pulse-470211.warehouse.FactProductPrice`
              )
          ),
          
          -- Calculate average prices
          AvgPrices AS (
            SELECT
              product_id,
              AVG(price) AS avg_price
            FROM
              ProductPrices
            GROUP BY
              product_id
          ),
          
          -- Add debug info
          DebugInfo AS (
            SELECT 
              (SELECT COUNT(*) FROM ProductIDs) AS product_ids_count,
              (SELECT COUNT(*) FROM BasicProductInfo) AS basic_info_count,
              (SELECT COUNT(*) FROM ProductPrices) AS prices_count
          )

        -- Final result with structured response
        SELECT
          bp.product_id AS productId,
          bp.product_name AS productName,
          bp.category_name AS categoryName,
          COALESCE(ap.avg_price, 0) AS averagePrice,
          ARRAY_AGG(
            STRUCT(
              pp.retailer_id,
              pp.retailer_name,
              pp.price,
              CASE
                WHEN pp.is_available = TRUE THEN 'in_stock'
                ELSE 'out_of_stock'
              END AS stockStatus,
              4.5 AS rating, -- Placeholder; would be from actual ratings table
              FORMAT_DATE('%Y-%m-%d', pp.price_date) AS lastUpdated
            )
            ORDER BY pp.price ASC
            LIMIT @limit
          ) AS retailerPrices,
          STRUCT(
            0.0 AS priceChange,
            'stable' AS trend
          ) AS priceHistory
        FROM
          BasicProductInfo bp
        LEFT JOIN
          ProductPrices pp
          ON bp.product_id = pp.product_id
        LEFT JOIN
          AvgPrices ap
          ON bp.product_id = ap.product_id
        GROUP BY
          bp.product_id,
          bp.product_name,
          bp.category_name,
          ap.avg_price
        ORDER BY
          pi.product_id
        """
        
        # Try a direct basic query first to confirm these product IDs exist
        debug_query = f"""
        SELECT match_group_id, COUNT(*) 
        FROM `price-pulse-470211.warehouse.FactProductMatch`
        WHERE match_group_id IN ({product_ids})
        GROUP BY match_group_id
        """
        
        debug_job = bq_client.query(debug_query)
        debug_results = list(debug_job.result())
        
        if not debug_results:
            # Product IDs don't exist in the database, return empty response
            print(f"No products found with IDs: {product_ids}")
            return {"success": True, "data": [], "timestamp": datetime.utcnow()}
        
        # Execute the main query
        query_job = bq_client.query(sql, job_config=job_config)
        results = query_job.result()
        
        # Process results
        products = []
        for row in results:
            products.append({
                "productId": row.productId,
                "productName": row.productName,
                "categoryName": row.categoryName,
                "averagePrice": row.averagePrice,
                "retailerPrices": row.retailerPrices,
                "priceHistory": row.priceHistory
            })
        
        # Prepare the response
        response = {
            "success": True,
            "data": products,
            "timestamp": datetime.utcnow()
        }
        
        # Cache the results for 4 hours (as recommended in the guide)
        cache_service.set(cache_key, response, ttl_seconds=14400)
        
        return response
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred during price comparison: {e}"
        )
        
@router.get("/buying-guides", response_model=BuyingGuidesResponse)
async def buying_guides_categories(
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Retrieve categories for buying guides with relevant metadata.
    Returns a list of categories with their descriptions, icons, and popular brands.
    """
    # Cache key for buying guides categories
    cache_key = "buyer-central:buying-guides"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        # Create the BigQuery job config
        job_config = bigquery.QueryJobConfig()
        
        # BigQuery SQL following the provided implementation
        sql = """
        -- Get category information
        WITH
          CategoryStats AS (
            SELECT
              c.category_id,
              c.category_name,
              COUNT(DISTINCT pm.match_group_id) AS product_count,
              AVG(pp.current_price) AS avg_price
            FROM
              `price-pulse-470211.warehouse.DimCategory` c
            JOIN
              `price-pulse-470211.warehouse.DimShopProduct` sp
              ON c.category_id = sp.predicted_master_category_id
            JOIN
              `price-pulse-470211.warehouse.FactProductMatch` pm
              ON sp.shop_product_id = pm.shop_product_id
            JOIN
              `price-pulse-470211.warehouse.DimVariant` v
              ON sp.shop_product_id = v.shop_product_id
            JOIN
              `price-pulse-470211.warehouse.FactProductPrice` pp
              ON v.variant_id = pp.variant_id
            WHERE
              pp.date_id = (
                SELECT MAX(date_id)
                FROM `price-pulse-470211.warehouse.FactProductPrice`
              )
            GROUP BY
              c.category_id,
              c.category_name
          ),

          -- Get popular brands for each category
          CategoryBrands AS (
            SELECT
              sp.predicted_master_category_id AS category_id,
              sp.brand_native,
              COUNT(DISTINCT sp.shop_product_id) AS product_count
            FROM
              `price-pulse-470211.warehouse.DimShopProduct` sp
            WHERE
              sp.brand_native IS NOT NULL
            GROUP BY
              sp.predicted_master_category_id,
              sp.brand_native
          ),

          TopBrands AS (
            SELECT
              category_id,
              ARRAY_AGG(brand_native ORDER BY product_count DESC LIMIT 3) AS popular_brands
            FROM (
              SELECT
                category_id,
                brand_native,
                product_count,
                ROW_NUMBER() OVER (PARTITION BY category_id ORDER BY product_count DESC) AS rank
              FROM
                CategoryBrands
            )
            WHERE
              rank <= 3
            GROUP BY
              category_id
          )

        -- Final result
        SELECT
          cs.category_id AS categoryId,
          cs.category_name AS categoryName,
          CASE
            WHEN cs.category_name = 'Smartphones' THEN 'Complete guides for choosing the perfect smartphone'
            WHEN cs.category_name = 'Laptops' THEN 'Expert advice for laptop purchases'
            WHEN cs.category_name = 'Audio' THEN 'Find the best headphones and speakers'
            WHEN cs.category_name = 'Smart Watches' THEN 'Everything you need to know about smart watches'
            ELSE CONCAT('Buying guides for ', cs.category_name)
          END AS description,
          CASE
            WHEN cs.category_name = 'Smartphones' THEN '📱'
            WHEN cs.category_name = 'Laptops' THEN '💻'
            WHEN cs.category_name = 'Audio' THEN '🎧'
            WHEN cs.category_name = 'Smart Watches' THEN '⌚'
            WHEN cs.category_name = 'Cameras' THEN '📷'
            WHEN cs.category_name = 'Tablets' THEN '📱'
            WHEN cs.category_name = 'Gaming' THEN '🎮'
            ELSE '📦'
          END AS icon,
          FLOOR(SQRT(cs.product_count) * 2) AS guideCount, -- Simulated guide count
          cs.avg_price AS avgProductPrice,
          tb.popular_brands AS popularBrands
        FROM
          CategoryStats cs
        JOIN
          TopBrands tb
          ON cs.category_id = tb.category_id
        ORDER BY
          cs.product_count DESC
        LIMIT 10
        """
        
        # Execute query
        query_job = bq_client.query(sql, job_config=job_config)
        results = query_job.result()
        
        # Process results
        categories = []
        for row in results:
            categories.append({
                "categoryId": row.categoryId,
                "categoryName": row.categoryName,
                "description": row.description,
                "icon": row.icon,
                "guideCount": row.guideCount,
                "avgProductPrice": row.avgProductPrice,
                "popularBrands": row.popularBrands
            })
        
        # Prepare the response
        response = {
            "success": True,
            "data": categories,
            "timestamp": datetime.utcnow()
        }
        
        # Cache the results for 24 hours (as recommended in the guide)
        cache_service.set(cache_key, response, ttl_seconds=86400)
        
        return response
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while retrieving buying guides: {e}"
        )
