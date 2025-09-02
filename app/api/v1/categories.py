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
    category_id: int = Path(..., description="Category ID"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    sort: str = Query("popularity", description="Sort order: price_asc, price_desc, popularity, newest"),
    min_price: Optional[float] = Query(None, description="Minimum price filter"),
    max_price: Optional[float] = Query(None, description="Maximum price filter"),
    retailer: Optional[str] = Query(None, description="Retailer filter"),
    in_stock: Optional[bool] = Query(None, description="Stock status filter"),
    response: Response = None,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get products for a specific category with filtering and pagination.
    """
    # Create a unique cache key based on all parameters
    cache_key = f"categories:{category_id}:products:{page}:{limit}:{sort}:{min_price}:{max_price}:{retailer}:{in_stock}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        # First, get the category information
        category_query = f"""
        SELECT
            c.category_id,
            c.category_name as name,
            c.parent_category_id
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
        WHERE c.category_id = {category_id}
        """
        
        category_job = bq_client.query(category_query)
        category_rows = list(category_job.result())
        
        if not category_rows:
            raise HTTPException(status_code=404, detail=f"Category with ID {category_id} not found")
        
        category_row = category_rows[0]
        category = {
            "category_id": category_row.category_id,
            "name": category_row.name,
            "description": f"{category_row.name} and accessories",
            "parent_category_id": category_row.parent_category_id
        }
        
        # Build the base products query with all filters
        products_query = f"""
        WITH ProductsInCategory AS (
            SELECT
                sp.shop_product_id as id,
                sp.product_title_native as name,
                sp.brand_native as brand,
                fpp.current_price as price,
                fpp.original_price as original_price,
                CAST((1 - (fpp.current_price / NULLIF(fpp.original_price, 0))) * 100 AS INT64) as discount,
                s.shop_name as retailer,
                s.shop_id as retailer_id,
                fpp.is_available as in_stock,
                (SELECT image_url FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` 
                 WHERE shop_product_id = sp.shop_product_id ORDER BY sort_order LIMIT 1) as image,
                COALESCE(AVG(pa.anomaly_score), 0) * 20 as popularity_score
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` pa ON fpp.price_fact_id = pa.price_fact_id
            WHERE sp.predicted_master_category_id = {category_id}
            AND fpp.date_id = (
                SELECT MAX(date_id) 
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
            )
        """
        
        # Add filters
        where_clauses = []
        
        if min_price is not None:
            where_clauses.append(f"price >= {min_price}")
            
        if max_price is not None:
            where_clauses.append(f"price <= {max_price}")
            
        if retailer is not None:
            where_clauses.append(f"retailer = '{retailer}'")
            
        if in_stock is not None:
            where_clauses.append(f"in_stock = {str(in_stock).lower()}")
        
        if where_clauses:
            products_query += " AND " + " AND ".join(where_clauses)
        
        products_query += " GROUP BY sp.shop_product_id, sp.product_title_native, sp.brand_native, "
        products_query += "fpp.current_price, fpp.original_price, s.shop_name, s.shop_id, fpp.is_available"
        
        # Add sorting
        if sort == "price_asc":
            products_query += " ORDER BY price ASC"
        elif sort == "price_desc":
            products_query += " ORDER BY price DESC"
        elif sort == "newest":
            products_query += " ORDER BY id DESC"  # Assuming newer products have higher IDs
        else:  # Default to popularity
            products_query += " ORDER BY popularity_score DESC, price ASC"
            
        # Get the total count before adding pagination
        count_query = f"SELECT COUNT(*) as total FROM ({products_query})"
        count_job = bq_client.query(count_query)
        count_result = list(count_job.result())[0]
        total_items = count_result.total
        
        # Add pagination
        offset = (page - 1) * limit
        products_query += f" LIMIT {limit} OFFSET {offset}"
        
        # Execute the main query
        products_job = bq_client.query(products_query)
        product_rows = list(products_job.result())
        
        # Process product results
        products = []
        for row in product_rows:
            product = {
                "id": row.id,
                "name": row.name,
                "brand": row.brand if row.brand else "Unknown",
                "price": float(row.price),
                "original_price": float(row.original_price) if row.original_price else None,
                "discount": row.discount if row.discount and row.discount > 0 else None,
                "retailer": row.retailer,
                "retailer_id": row.retailer_id,
                "in_stock": row.in_stock,
                "image": row.image if row.image else "https://placeholder.com/product",
                "popularity_score": int(row.popularity_score) if row.popularity_score else 0
            }
            products.append(product)
            
        # Get filter options for the category (brands, retailers, price ranges)
        filters_query = f"""
        WITH ProductsBase AS (
            SELECT
                sp.brand_native as brand,
                s.shop_id as retailer_id,
                s.shop_name as retailer_name,
                fpp.current_price as price
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
            WHERE sp.predicted_master_category_id = {category_id}
            AND fpp.date_id = (
                SELECT MAX(date_id) 
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
            )
        ),
        BrandCounts AS (
            SELECT brand as name, COUNT(*) as count 
            FROM ProductsBase 
            WHERE brand IS NOT NULL 
            GROUP BY brand 
            ORDER BY count DESC 
            LIMIT 10
        ),
        RetailerCounts AS (
            SELECT retailer_id, retailer_name as name, COUNT(*) as count 
            FROM ProductsBase 
            GROUP BY retailer_id, retailer_name 
            ORDER BY count DESC
        ),
        PriceRanges AS (
            SELECT
                CASE
                    WHEN price < 100 THEN '0-100'
                    WHEN price >= 100 AND price < 500 THEN '100-500'
                    WHEN price >= 500 AND price < 1000 THEN '500-1000'
                    WHEN price >= 1000 AND price < 2000 THEN '1000-2000'
                    ELSE '2000+'
                END as range,
                COUNT(*) as count
            FROM ProductsBase
            GROUP BY range
            ORDER BY MIN(price)
        )
        SELECT
            (SELECT ARRAY_AGG(STRUCT(name, count)) FROM BrandCounts) as brands,
            (SELECT ARRAY_AGG(STRUCT(retailer_id, name, count)) FROM RetailerCounts) as retailers,
            (SELECT ARRAY_AGG(STRUCT(range, count)) FROM PriceRanges) as price_ranges
        """
        
        filters_job = bq_client.query(filters_query)
        filters_result = list(filters_job.result())[0]
        
        # Calculate pagination info
        total_pages = (total_items + limit - 1) // limit  # Ceiling division
        
        # Build the response
        response_data = {
            "category": category,
            "products": products,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_items": total_items,
                "items_per_page": limit
            },
            "filters": {
                "brands": [{"name": b.name, "count": b.count} for b in filters_result.brands] if filters_result.brands else [],
                "retailers": [{"retailer_id": r.retailer_id, "name": r.name, "count": r.count} for r in filters_result.retailers] if filters_result.retailers else [],
                "price_ranges": [{"range": p.range, "count": p.count} for p in filters_result.price_ranges] if filters_result.price_ranges else []
            }
        }
        
        # Cache the result for 15 minutes
        cache_service.set(cache_key, response_data, 900)
        
        return response_data
    
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        print(f"Error fetching category products: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve category products")
