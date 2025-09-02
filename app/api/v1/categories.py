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


