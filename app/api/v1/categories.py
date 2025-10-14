from fastapi import APIRouter, Depends, HTTPException, Query, Path, Response
from typing import Dict, List, Optional, Any, Union
from google.cloud import bigquery
import supabase
from app.config import settings
from app.api.deps import get_current_user, get_current_admin_user, get_bigquery_client
from app.services.cache_service import cache_service
from app.schemas.category import (
    CategoriesResponse, 
    CategoryProductsResponse
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from app.services.cache_service import cache_service
from app.schemas.category import (
    CategoriesResponse, 
    CategoryProductsResponse
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=CategoriesResponse)
async def get_all_categories(
    include_subcategories: bool = Query(True, description="Include child categories"),
    response: Response = None,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get all product categories, with counts correctly aggregated from subcategories
    and an optional nested subcategory structure built by the database.
    """
    cache_key = f"categories:all:{include_subcategories}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        # This more efficient query builds the category hierarchy and calculates counts in a single pass
        query = f"""
        WITH
          -- Step 1: Create a definitive map of each category to its ultimate top-level parent
          CategoryHierarchy AS (
            SELECT
              c.category_id,
              c.category_name,
              -- If a category has no parent, it is its own parent
              COALESCE(p.category_id, c.category_id) AS parent_id,
              COALESCE(p.category_name, c.category_name) AS parent_name,
              -- Include trending score calculation
              COALESCE(AVG(pa.anomaly_score), 0) AS trending_score
            FROM
              `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` AS c
            LEFT JOIN
              `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` AS p 
              ON c.parent_category_id = p.category_id
            LEFT JOIN 
              `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
              ON c.category_id = sp.predicted_master_category_id
            LEFT JOIN 
              `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
              ON sp.shop_product_id = v.shop_product_id
            LEFT JOIN 
              `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp 
              ON v.variant_id = fpp.variant_id
            LEFT JOIN 
              `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` pa 
              ON fpp.price_fact_id = pa.price_fact_id
            WHERE 
              fpp.date_id = (
                SELECT MAX(date_id) 
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
              ) OR fpp.date_id IS NULL
            GROUP BY
              c.category_id, c.category_name, p.category_id, p.category_name
          ),

          -- Step 2: Calculate the product count for EACH individual category
          CategoryProductCounts AS (
            SELECT
              dsp.predicted_master_category_id AS category_id,
              COUNT(DISTINCT dsp.shop_product_id) AS product_count
            FROM
              `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` AS dsp
            GROUP BY
              dsp.predicted_master_category_id
          )

        -- Step 3: Join the hierarchy and counts, and use ARRAY_AGG to build the nested structure
        SELECT
          h.parent_id AS category_id,
          h.parent_name AS name,
          -- Add description, icon, and color
          CONCAT(h.parent_name, ' and accessories') AS description,
          LOWER(REPLACE(h.parent_name, ' ', '_')) AS icon,
          'blue' AS color,
          -- Correctly sum the counts of the parent AND all its children
          SUM(COALESCE(cpc.product_count, 0)) AS product_count,
          -- Include average trending score for the parent category
          MAX(h.trending_score) AS trending_score,
          -- Build a nested array of subcategories directly in the query
          ARRAY_AGG(
            -- Only include subcategories in the array, not the parent itself
            IF(h.category_id != h.parent_id,
              STRUCT(
                h.category_id AS category_id,
                h.category_name AS name,
                COALESCE(cpc.product_count, 0) AS product_count,
                h.parent_id AS parent_category_id
              ),
              NULL)
            IGNORE NULLS -- Ignore the NULLs generated for parent categories
          ) AS subcategories
        FROM
          CategoryHierarchy AS h
        LEFT JOIN
          CategoryProductCounts AS cpc ON h.category_id = cpc.category_id
        GROUP BY
          h.parent_id, h.parent_name
        ORDER BY
          product_count DESC
        """

        # Execute the query
        query_job = bq_client.query(query)
        results = [dict(row) for row in query_job.result()]
        
        # Clean up the results based on include_subcategories parameter
        if not include_subcategories:
            for category in results:
                # Set subcategories to an empty list instead of null for better type consistency
                category["subcategories"] = []
                
        # Calculate total products across all categories (avoiding double counting)
        total_products = sum(cat.get('product_count', 0) for cat in results if cat)
        
        # Build the response
        response_data = {
            "categories": results,
            "total_categories": len(results),
            "total_products": total_products
        }
        
        # Cache the result for 30 minutes
        cache_service.set(cache_key, response_data, 1800)
        
        return response_data
    
    except Exception as e:
        print(f"Error fetching categories: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve categories")


@router.get("/{category_id}/products", response_model=CategoryProductsResponse)
async def get_category_products(
    category_id: int = Path(..., description="The ID of the category to retrieve products for"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Number of products per page"),
    sort_by: str = Query("price_desc", description="Sorting method: price_asc, price_desc, name_asc"),
    brand: Optional[str] = Query(None, description="Filter by brand name"),
    min_price: Optional[float] = Query(None, description="Minimum price filter"),
    max_price: Optional[float] = Query(None, description="Maximum price filter"),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get paginated list of products for a specific category (including its subcategories)
    with secure filtering and sorting options, all in a single efficient query.
    """
    # Create a cache key with all parameters
    cache_key = f"category:{category_id}:products:page{page}:limit{limit}:sort{sort_by}"
    if brand:
        cache_key += f":brand{brand}"
    if min_price:
        cache_key += f":min{min_price}"
    if max_price:
        cache_key += f":max{max_price}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    cache_key = f"category:{category_id}:products:page{page}:limit{limit}:sort{sort_by}:min{min_price}:max{max_price}:brand{brand}"
    
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data

    try:
        # --- Build Query with Secure Parameters ---
        query_params = [
            bigquery.ScalarQueryParameter("category_id", "INT64", category_id),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
            bigquery.ScalarQueryParameter("offset", "INT64", (page - 1) * limit),
        ]
        filter_clauses = ["lp.is_available = TRUE"]

        if brand:
            filter_clauses.append("LOWER(sp.brand_native) LIKE LOWER(@brand)")
            query_params.append(bigquery.ScalarQueryParameter("brand", "STRING", f"%{brand}%"))
        if min_price is not None:
            filter_clauses.append("lp.current_price >= @min_price")
            query_params.append(bigquery.ScalarQueryParameter("min_price", "FLOAT64", min_price))
        if max_price is not None:
            filter_clauses.append("lp.current_price <= @max_price")
            query_params.append(bigquery.ScalarQueryParameter("max_price", "FLOAT64", max_price))
        
        filter_sql = " AND ".join(filter_clauses)

        # --- FIX: Remove the 'p.' prefix from the sort map values ---
        sort_map = {
            "price_asc": "price ASC",
            "price_desc": "price DESC",
            "name_asc": "name ASC",
        }
        order_by_sql = sort_map.get(sort_by, "price ASC")

        # --- The All-in-One Query ---
        query = f"""
        WITH
          CategoryAndDescendants AS (
            SELECT category_id FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory`
            WHERE category_id = @category_id OR parent_category_id = @category_id
          ),
          LatestPrices AS (
            SELECT variant_id, current_price, original_price, is_available, date_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
            QUALIFY ROW_NUMBER() OVER(PARTITION BY variant_id ORDER BY date_id DESC) = 1
          ),
          -- Get the primary image for each product (lowest sort_order available)
          ProductImages AS (
            SELECT 
              shop_product_id,
              image_url
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage`
            QUALIFY ROW_NUMBER() OVER(PARTITION BY shop_product_id ORDER BY sort_order ASC) = 1
          ),
          ProductsInScope AS (
            SELECT
              sp.shop_product_id, sp.product_title_native, sp.brand_native,
              lp.current_price, lp.original_price, s.shop_name, s.shop_id,
              lp.is_available, pi.image_url,
              CASE
                WHEN lp.original_price > 0 AND lp.original_price > lp.current_price
                THEN ROUND(((lp.original_price - lp.current_price) / lp.original_price) * 100, 0)
                ELSE 0
              END as discount
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
            LEFT JOIN LatestPrices lp ON v.variant_id = lp.variant_id -- Use LEFT JOIN to not lose products without price
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            -- Join with ProductImages to get the image with the lowest sort_order
            LEFT JOIN ProductImages pi ON sp.shop_product_id = pi.shop_product_id
            WHERE sp.predicted_master_category_id IN (SELECT category_id FROM CategoryAndDescendants)
            AND {filter_sql}
          ),
          FinalProducts AS (
            SELECT
              shop_product_id as id,
              ANY_VALUE(product_title_native) as name,
              COALESCE(ANY_VALUE(brand_native), 'Unknown Brand') as brand,
              ANY_VALUE(shop_name) as retailer,
              ANY_VALUE(shop_id) as retailer_id,
              MIN(current_price) as price,
              ANY_VALUE(original_price) as original_price,
              ANY_VALUE(discount) as discount,
              ANY_VALUE(is_available) as in_stock,
              ANY_VALUE(image_url) as image
            FROM ProductsInScope
            GROUP BY shop_product_id
          ),
          BrandFilters AS (
            SELECT
              brand_native AS name,
              COUNT(DISTINCT shop_product_id) AS count
            FROM ProductsInScope
            WHERE brand_native IS NOT NULL
            GROUP BY brand_native ORDER BY count DESC LIMIT 20
          ),
          TotalCount AS (
            SELECT COUNT(*) as total_items FROM FinalProducts
          )
        SELECT
          (SELECT AS STRUCT category_id, category_name as name, 
           CONCAT(category_name, ' and accessories') as description,
           LOWER(REPLACE(category_name, ' ', '_')) as icon,
           'blue' as color,
           parent_category_id,
           (SELECT COUNT(*) FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` 
            WHERE predicted_master_category_id = @category_id) as product_count
           FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` 
           WHERE category_id = @category_id) AS category,
          (SELECT ARRAY_AGG(STRUCT(id, name, brand, price, retailer, retailer_id, original_price, discount, in_stock, image)) 
           FROM (SELECT * FROM FinalProducts ORDER BY {order_by_sql} LIMIT @limit OFFSET @offset)) AS products,
          (SELECT ARRAY_AGG(STRUCT(name, count)) FROM BrandFilters) AS brands,
          (SELECT total_items FROM TotalCount) AS total_items
        """

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = bq_client.query(query, job_config=job_config)
        result = list(query_job.result())
        
        if not result or not result[0].category:
            raise HTTPException(status_code=404, detail=f"Category with ID {category_id} not found")
        
        row = result[0]
        category_data = dict(row.category)
        products_data = [dict(p) for p in row.products] if row.products else []
        brands_data = [dict(b) for b in row.brands] if row.brands else []
        total_items = row.total_items or 0
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 1
        
        response_data = {
            "category": category_data,
            "products": products_data,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_items": total_items,
                "items_per_page": limit,
            },
            "filters": {"brands": brands_data},
        }

        cache_service.set(cache_key, response_data, 900)
        return response_data
        
    except Exception as e:
        logger.error(f"Error fetching products for category {category_id}: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred while retrieving products for category {category_id}.")