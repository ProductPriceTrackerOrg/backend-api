# app/api/v1/analytics/category_insights.py

from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Literal, Optional
from app.schemas.analytics.category_insights import CategoryInsightsResponse
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


@router.get("/category-insights", response_model=CategoryInsightsResponse, summary="Get category insights")
async def get_category_insights(
    time_range: Literal["7d", "30d", "90d", "1y"] = "30d",
    retailer: str = "all",
    bq_client=Depends(get_bigquery_client),
):
    """
    Get insights and performance metrics for product categories.
    
    - **time_range**: The time period for analysis (7d, 30d, 90d, 1y)
    - **retailer**: Shop ID or "all"
    """
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
                WITH today_date AS (
                SELECT date_id
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate`
                WHERE full_date = CURRENT_DATE()
                ),
                historical_date AS (
                SELECT date_id
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate`
                WHERE full_date = DATE_SUB(CURRENT_DATE(), INTERVAL {time_range_value} DAY)
                ),
                category_stats AS (
                SELECT
                    c.category_id,
                    c.category_name,
                    COUNT(DISTINCT v.variant_id) as product_count,
                    AVG(current_pp.current_price) as current_avg_price,
                    AVG(
                    CASE WHEN historical_pp.current_price IS NOT NULL
                    THEN (current_pp.current_price - historical_pp.current_price) / historical_pp.current_price * 100
                    ELSE 0 END
                    ) as price_change_pct,
                    STDDEV(daily_pp.current_price) / AVG(daily_pp.current_price) as price_volatility,
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
                AND d.full_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL {time_range_value} DAY) AND CURRENT_DATE()
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
        
        return {"insights": insights}
        
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