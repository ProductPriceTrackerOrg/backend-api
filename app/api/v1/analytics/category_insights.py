# app/api/v1/analytics/category_insights.py

from fastapi import APIRouter, Query, Depends, HTTPException, Response
from typing import Literal, Optional
from datetime import timedelta
import logging
from app.schemas.analytics.category_insights import CategoryInsightsResponse
from app.config import settings
from app.api.deps import get_bigquery_client
from app.services.cache_service import cache_service
from app.services.async_query_service import async_query_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


@router.get("/category-insights", response_model=CategoryInsightsResponse, summary="Get category insights")
async def get_category_insights(
    response: Response,
    time_range: Literal["7d", "30d", "90d", "1y"] = "30d",
    retailer: str = "all",
    bq_client=Depends(get_bigquery_client),
):
    """
    Get insights and performance metrics for product categories.
    
    Uses the most recent date with available data to ensure consistency across all analyses.
    Price changes are calculated by comparing with historical data from the specified time range.
    
    - **time_range**: The time period for analysis (7d, 30d, 90d, 1y)
    - **retailer**: Shop ID or name, or "all" for all retailers
    """
    # Cache key based on parameters
    cache_key = f"category_insights:{retailer}:{time_range}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        # Build query with the appropriate filters
        if retailer == "all":
            retailer_filter = "TRUE"
        elif retailer.isdigit():
            retailer_filter = f"sp.shop_id = {retailer}"
        else:
            sanitized_retailer = sanitize_string_for_sql(retailer)
            if not sanitized_retailer:
                raise ValueError("Retailer name cannot be empty")
            retailer_filter = f"s.shop_name = '{sanitized_retailer}'"
            
        time_range_value = get_time_range_value(time_range)
        
        # SQL query for category insights
        query = f"""
                WITH latest_available_date AS (
                -- Find the most recent date with data in FactProductPrice
                SELECT MAX(dd.date_id) as date_id, MAX(dd.full_date) as full_date
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` dd ON pp.date_id = dd.date_id
                ),
                today_date AS (
                SELECT date_id
                FROM latest_available_date
                ),
                historical_date AS (
                SELECT dd.date_id
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` dd
                JOIN latest_available_date lad
                ON dd.full_date = DATE_SUB(lad.full_date, INTERVAL {time_range_value} DAY)
                ),
                category_stats AS (
                SELECT
                    c.category_id,
                    c.category_name,
                    COUNT(DISTINCT v.variant_id) as product_count,
                    AVG(current_pp.current_price) as current_avg_price,
                    -- Fix division by zero in price change calculation
                    AVG(
                    CASE 
                      WHEN historical_pp.current_price IS NOT NULL AND historical_pp.current_price > 0
                      THEN (current_pp.current_price - historical_pp.current_price) / historical_pp.current_price * 100
                      ELSE 0 
                    END
                    ) as price_change_pct,
                    -- Fix division by zero in volatility calculation
                    SAFE_DIVIDE(
                      STDDEV(daily_pp.current_price), 
                      NULLIF(AVG(daily_pp.current_price), 0)
                    ) as price_volatility,
                    COUNT(CASE WHEN current_pp.current_price < historical_pp.current_price THEN 1 END) as deal_count
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
                    ON c.category_id = sp.predicted_master_category_id
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v
                    ON sp.shop_product_id = v.shop_product_id
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s
                    ON sp.shop_id = s.shop_id
                CROSS JOIN today_date td
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` current_pp
                    ON v.variant_id = current_pp.variant_id
                AND current_pp.date_id = td.date_id
                CROSS JOIN historical_date hd
                LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` historical_pp
                    ON v.variant_id = historical_pp.variant_id
                AND historical_pp.date_id = hd.date_id
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` daily_pp
                    ON v.variant_id = daily_pp.variant_id
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d
                    ON daily_pp.date_id = d.date_id
                JOIN latest_available_date lad2 ON 1=1
                AND d.full_date BETWEEN DATE_SUB(lad2.full_date, INTERVAL {time_range_value} DAY) AND lad2.full_date
                WHERE current_pp.is_available = TRUE
                    AND {retailer_filter}
                GROUP BY c.category_id, c.category_name
                )
                SELECT
                category_name,
                ROUND(current_avg_price, 2) as avg_price,
                ROUND(price_change_pct, 2) as price_change,
                ROUND(price_volatility, 2) as price_volatility,
                product_count,
                deal_count
                FROM category_stats
                ORDER BY deal_count DESC
                LIMIT 10
        """
        
        # Execute query
        query_job = bq_client.query(query)
        results = list(query_job.result())
        
        # Get the date that was used for analysis (for logging)
        date_query = f"""
        WITH latest_available_date AS (
          SELECT MAX(dd.date_id) as date_id, MAX(dd.full_date) as full_date
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` dd ON pp.date_id = dd.date_id
        )
        SELECT full_date FROM latest_available_date
        """
        date_result = list(bq_client.query(date_query).result())
        if date_result and hasattr(date_result[0], 'full_date'):
            print(f"Category insights using data from: {date_result[0].full_date}")
            historical_date = date_result[0].full_date - timedelta(days=time_range_value)
            print(f"Historical comparison date: {historical_date}")
        
        # Transform into response format
        insights = [
            {
                "category_name": item.category_name,
                "avg_price": item.avg_price,
                "price_change": item.price_change,
                "price_volatility": item.price_volatility,
                "product_count": item.product_count,
                "deal_count": item.deal_count
            }
            for item in results
        ]
        
        response_data = {"insights": insights}
        
        # Cache the result for 30 minutes (1800 seconds)
        cache_service.set(cache_key, response_data, ttl_seconds=1800)
        
        return response_data
        
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"Invalid input parameter: {str(ve)}")
    except Exception as e:
        error_message = str(e)
        if "Unrecognized name" in error_message and retailer != "all" and not retailer.isdigit():
            # Provide a more helpful error message for retailer name issues
            raise HTTPException(
                status_code=404, 
                detail=f"Retailer '{retailer}' not found. Please verify the retailer name or use a retailer ID instead."
            )
        else:
            raise HTTPException(status_code=500, detail=f"Error retrieving category insights: {error_message}")