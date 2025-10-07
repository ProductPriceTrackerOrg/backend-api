# app/api/v1/analytics/shop_comparison.py

from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Literal, Optional, List
from app.schemas.analytics.shop_comparison import ShopComparisonResponse
from app.config import settings
from app.api.deps import get_bigquery_client

router = APIRouter()


def get_time_range_value(time_range: str) -> int:
    """Convert time range string to number of days"""
    mapping = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
    return mapping.get(time_range, 30)


def sanitize_string_for_sql(input_str: str) -> str:
    """
    Sanitize a string to be used safely in SQL queries.
    Replaces single quotes with two single quotes to prevent SQL injection.
    """
    if not input_str:
        return ""
    return input_str.replace("'", "''")


@router.get("/shop-comparison", response_model=ShopComparisonResponse, summary="Get shop comparison data")
async def get_shop_comparison(
    category: str = "all",
    time_range: Literal["7d", "30d", "90d", "1y"] = "30d",
    bq_client=Depends(get_bigquery_client),
):
    """
    Get comparison data for retailers/shops.
    
    - **category**: Category ID or "all"
    - **time_range**: The time period for analysis (7d, 30d, 90d, 1y)
    """
    try:
        # Build query with the appropriate filters
        if category == "all":
            category_filter = "TRUE"
        elif category.isdigit():
            # If category is a numeric ID
            category_filter = f"sp.predicted_master_category_id = {category}"
        else:
            # If category is a name string, join with the category table
            sanitized_category = sanitize_string_for_sql(category)
            if not sanitized_category:
                raise ValueError("Category name cannot be empty")
            category_filter = f"c.category_name = '{sanitized_category}'"
            
        time_range_value = get_time_range_value(time_range)
        
        # SQL query for shop comparison
        query = f"""
        WITH today_date AS (
          SELECT date_id 
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` 
          WHERE full_date = CURRENT_DATE()
        ),
        shop_products AS (
          SELECT 
            s.shop_id,
            s.shop_name,
            v.variant_id,
            pp.current_price,
            pp.is_available
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON s.shop_id = sp.shop_id
          {'JOIN `' + settings.GCP_PROJECT_ID + '.' + settings.BIGQUERY_DATASET_ID + '.DimCategory` c ON sp.predicted_master_category_id = c.category_id' if not category.isdigit() and category != 'all' else ''}
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
          JOIN today_date td ON 1=1
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
            ON v.variant_id = pp.variant_id AND pp.date_id = td.date_id
          WHERE {category_filter}
        ),
        avg_market_prices AS (
          SELECT 
            variant_id,
            AVG(current_price) as avg_market_price
          FROM shop_products
          GROUP BY variant_id
        ),
        shop_stats AS (
          SELECT
            sp.shop_id,
            sp.shop_name,
            COUNT(DISTINCT sp.variant_id) as product_count,
            -- Price competitiveness rating (100 scale)
            -- Higher is better (100 means prices are on average 0% of market average)
            -- Lower is worse (0 means prices are on average 100%+ more than market average)
            SAFE_DIVIDE(100, AVG(SAFE_DIVIDE(sp.current_price, amp.avg_market_price) * 100)) as price_rating,
            -- Reliability score based on consistent inventory
            (COUNT(CASE WHEN sp.is_available = TRUE THEN 1 END) * 100.0 /
              NULLIF(COUNT(sp.variant_id), 0)) as reliability_score,
            -- Availability percentage
            (SUM(CASE WHEN sp.is_available = TRUE THEN 1 ELSE 0 END) * 100.0 /
              NULLIF(COUNT(sp.variant_id), 0)) as availability_percentage
          FROM shop_products sp
          LEFT JOIN avg_market_prices amp ON sp.variant_id = amp.variant_id
          GROUP BY sp.shop_id, sp.shop_name
        ),
        best_categories AS (
          SELECT
            s.shop_id,
            c.category_name,
            COUNT(*) as product_count,
            ROW_NUMBER() OVER (PARTITION BY s.shop_id ORDER BY COUNT(*) DESC) as category_rank
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON s.shop_id = sp.shop_id
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
          WHERE
            sp.scraped_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {time_range_value} DAY)
          GROUP BY s.shop_id, c.category_name
        ),
        top_categories AS (
          SELECT
            shop_id,
            category_name,
            category_rank
          FROM best_categories
          WHERE category_rank <= 3
        ),
        shop_categories AS (
          SELECT
            ss.shop_id,
            ss.shop_name,
            ss.product_count,
            ROUND(GREATEST(0, LEAST(ss.price_rating, 100)), 0) as avg_price_rating,
            ROUND(ss.reliability_score, 0) as reliability_score,
            ROUND(ss.availability_percentage, 0) as availability_percentage,
            ARRAY_AGG(tc.category_name ORDER BY tc.category_rank LIMIT 3) as best_categories
          FROM shop_stats ss
          LEFT JOIN top_categories tc ON ss.shop_id = tc.shop_id
          GROUP BY ss.shop_id, ss.shop_name, ss.product_count, ss.price_rating, ss.reliability_score, ss.availability_percentage
        )
        SELECT
          shop_name,
          product_count,
          avg_price_rating,
          reliability_score,
          availability_percentage,
          best_categories
        FROM shop_categories
        ORDER BY avg_price_rating DESC
        LIMIT 10
        """
        
        # Execute query
        query_job = bq_client.query(query)
        results = list(query_job.result())
        
        # Transform into response format
        insights = []
        for item in results:
            # Convert array from BigQuery to Python list if needed
            best_categories = []
            if hasattr(item, 'best_categories'):
                if isinstance(item.best_categories, list):
                    best_categories = [cat for cat in item.best_categories if cat]
                elif item.best_categories:
                    best_categories = [item.best_categories]
            
            insights.append({
                "shop_name": item.shop_name,
                "product_count": item.product_count,
                "avg_price_rating": int(item.avg_price_rating) if item.avg_price_rating is not None else 0,
                "reliability_score": int(item.reliability_score) if item.reliability_score is not None else 0,
                "availability_percentage": float(item.availability_percentage) if item.availability_percentage is not None else 0,
                "best_categories": best_categories
            })
        
        return {"insights": insights}
        
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"Invalid input parameter: {str(ve)}")
    except Exception as e:
        error_message = str(e)
        if "Unrecognized name" in error_message and category != "all" and not category.isdigit():
            # Provide a more helpful error message for category name issues
            raise HTTPException(
                status_code=404, 
                detail=f"Category '{category}' not found. Please verify the category name or use a category ID instead."
            )
        else:
            raise HTTPException(status_code=500, detail=f"Error retrieving shop comparison data: {error_message}")