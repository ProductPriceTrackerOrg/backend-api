import logging
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, Depends, Query, HTTPException, Response
from google.cloud import bigquery
from app.config import settings
from app.api.deps import get_bigquery_client, get_current_user_optional
from app.services.cache_service import cache_service
from app.schemas.search import (
    AutocompleteSuggestions,
    SearchResultsResponse
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/autocomplete", response_model=AutocompleteSuggestions)
async def get_autocomplete_suggestions(
    q: str = Query(..., min_length=2, description="Partial search query"),
    limit: int = Query(10, ge=1, le=20, description="Maximum number of suggestions to return"),
    response: Response = None,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Provides fast product title suggestions for a partial search query.
    """
    # Create cache key based on the query
    cache_key = f"search:autocomplete:{q}:limit:{limit}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
        
    try:
        # Use a parameterized query to prevent SQL injection
        query_params = [
            bigquery.ScalarQueryParameter("query", "STRING", f"%{q.lower()}%"),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        
        query = f"""
            WITH RankedSuggestions AS (
                SELECT 
                    product_title_native as suggestion,
                    -- Prioritize titles that start with the query
                    CASE 
                        WHEN LOWER(product_title_native) = LOWER(@query) THEN 1
                        WHEN LOWER(product_title_native) LIKE CONCAT(LOWER(@query), '%') THEN 2
                        WHEN LOWER(product_title_native) LIKE CONCAT('%', LOWER(@query), '%') THEN 3
                        ELSE 4 
                    END as match_rank,
                    -- Count how many products have this title (popular titles should rank higher)
                    COUNT(*) OVER(PARTITION BY product_title_native) as title_frequency
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct`
                WHERE LOWER(product_title_native) LIKE CONCAT('%', LOWER(@query), '%')
                GROUP BY product_title_native
            )
            SELECT suggestion
            FROM RankedSuggestions
            -- Order first by match quality, then by popularity (frequency), then alphabetically
            ORDER BY match_rank, title_frequency DESC, suggestion
            LIMIT @limit
        """
        
        query_job = bq_client.query(query, job_config=job_config)
        suggestions = [row['suggestion'] for row in query_job.result()]
        
        result = {"suggestions": suggestions}
        
        # Cache the results for 5 minutes
        cache_service.set(cache_key, result, 300)
        
        return result

    except Exception as e:
        logger.error(f"Error in autocomplete: {e}")
        # Return empty list on error instead of crashing
        return {"suggestions": []}


@router.get("", response_model=SearchResultsResponse)
async def search_products(
    q: str = Query(..., description="The search query (product title or keywords)"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(20, ge=1, le=50, description="Number of results per page"),
    bq_client: bigquery.Client = Depends(get_bigquery_client),
    current_user: Optional[Dict] = Depends(get_current_user_optional)
):
    """
    Searches for products by title/keywords, finds match groups,
    and returns all products in those groups.
    """
    # Create cache key based on the query and pagination
    cache_key = f"search:results:{q}:page:{page}:limit:{limit}"
    
    # Skip cache for authenticated users (for personalization)
    if not current_user:
        cached_data = cache_service.get(cache_key)
        if cached_data:
            return cached_data
    
    try:
        query_params = [
            bigquery.ScalarQueryParameter("query", "STRING", f"%{q.lower()}%"),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
            bigquery.ScalarQueryParameter("offset", "INT64", (page - 1) * limit),
        ]
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        
        query = f"""
        WITH
          -- Step 1: Find all products that match the search query
          MatchingProducts AS (
            SELECT 
              sp.shop_product_id,
              fpm.match_group_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` AS sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductMatch` AS fpm 
              ON sp.shop_product_id = fpm.shop_product_id
            WHERE LOWER(sp.product_title_native) LIKE @query
              OR LOWER(sp.brand_native) LIKE @query
          ),
          
          -- Step 2: Get all match groups that contain any matching products
          MatchGroups AS (
            SELECT DISTINCT match_group_id
            FROM MatchingProducts
          ),
          
          -- Step 3: Get the latest price for all variants
          LatestPrices AS (
            SELECT variant_id, current_price, original_price, is_available, date_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
            QUALIFY ROW_NUMBER() OVER(PARTITION BY variant_id ORDER BY date_id DESC) = 1
          ),
          
          -- Step 4: Get all products in the same match groups (including products that didn't match the search directly)
          GroupedProducts AS (
            SELECT
              sp.shop_product_id,
              sp.product_title_native,
              sp.brand_native,
              sp.product_url,
              COALESCE(c.category_name, 'Uncategorized') AS category_name,
              c.category_id,
              s.shop_id,
              s.shop_name,
              v.variant_id,
              lp.current_price,
              lp.original_price,
              lp.is_available,
              pi.image_url,
              fpm.match_group_id,
              -- Flag to indicate if this product directly matched the search query
              CASE WHEN mp.shop_product_id IS NOT NULL THEN TRUE ELSE FALSE END AS is_direct_match,
              CASE
                WHEN lp.original_price > 0 AND lp.original_price > lp.current_price
                THEN ROUND(((lp.original_price - lp.current_price) / lp.original_price) * 100, 0)
                ELSE 0
              END AS discount_percentage,
              -- Add relevance score - prioritize exact title matches
              CASE
                WHEN LOWER(sp.product_title_native) = LOWER(@query) THEN 3
                WHEN LOWER(sp.product_title_native) LIKE LOWER(@query) THEN 2
                ELSE 1
              END AS relevance_score
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductMatch` AS fpm
            JOIN MatchGroups mg ON fpm.match_group_id = mg.match_group_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` AS sp ON fpm.shop_product_id = sp.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` AS s ON sp.shop_id = s.shop_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` AS c ON sp.predicted_master_category_id = c.category_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` AS v ON sp.shop_product_id = v.shop_product_id
            LEFT JOIN LatestPrices AS lp ON v.variant_id = lp.variant_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` AS pi 
              ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
            -- Left join with MatchingProducts to determine if this is a direct match
            LEFT JOIN MatchingProducts mp ON sp.shop_product_id = mp.shop_product_id
            WHERE lp.is_available = TRUE
          ),
          
          -- Step 5: Get the best product (lowest price) for each match group
          BestProducts AS (
            SELECT
              shop_product_id,
              product_title_native AS name,
              brand_native AS brand,
              product_url,
              category_name,
              category_id,
              shop_name AS retailer,
              shop_id AS retailer_id,
              current_price AS price,
              original_price,
              is_available AS in_stock,
              image_url AS image,
              discount_percentage AS discount,
              match_group_id,
              is_direct_match,
              relevance_score,
              -- Get the lowest price variant for each product
              ROW_NUMBER() OVER(PARTITION BY match_group_id ORDER BY relevance_score DESC, current_price ASC) AS price_rank
            FROM GroupedProducts
            QUALIFY price_rank = 1
          ),
          
          -- Step 5: Count total results for pagination
          TotalCount AS (
            SELECT COUNT(*) AS total_count FROM BestProducts
          )
          
        -- Main query with pagination
        SELECT
          bp.*,
          tc.total_count
        FROM BestProducts bp
        CROSS JOIN TotalCount tc
        ORDER BY 
          is_direct_match DESC,
          relevance_score DESC,
          price DESC
        LIMIT @limit
        OFFSET @offset
        """
        
        query_job = bq_client.query(query, job_config=job_config)
        results = [dict(row) for row in query_job.result()]
        
        total_count = 0
        products = []
        for row in results:
            total_count = row.get('total_count', 0)
            # Remove the count from each product
            if 'total_count' in row:
                del row['total_count']
            products.append(row)
        
        # Calculate pagination info
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1
        
        response_data = {
            "products": products,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_items": total_count,
                "items_per_page": limit
            },
            "query": q
        }
        
        # Cache the results for non-authenticated users
        if not current_user:
            cache_service.set(cache_key, response_data, 300)  # Cache for 5 minutes
        
        return response_data
        
    except Exception as e:
        logger.error(f"Error during product search for query '{q}': {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred during search: {str(e)}")