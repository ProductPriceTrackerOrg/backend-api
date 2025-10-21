# app/api/v1/analytics/category_insights.py

from fastapi import APIRouter, Query, Depends, HTTPException, Response
from typing import Literal
from datetime import timedelta
import logging
from google.cloud import bigquery

from app.schemas.analytics.category_insights import CategoryInsightsResponse
from app.config import settings
from app.api.deps import get_bigquery_client
from app.services.cache_service import cache_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


def get_time_range_value(time_range: str) -> int:
    """Convert time range string to number of days"""
    mapping = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
    return mapping.get(time_range, 30)


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
        retailer_condition = "TRUE"
        query_params = []
        join_shop = f"LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id"

        if retailer == "all":
            retailer_condition = "TRUE"
        elif retailer.isdigit():
            retailer_condition = "sp.shop_id = @retailer_id"
            query_params.append(bigquery.ScalarQueryParameter("retailer_id", "INT64", int(retailer)))
        else:
            cleaned_retailer = retailer.strip()
            if not cleaned_retailer:
                raise ValueError("Retailer name cannot be empty")
            retailer_condition = "s.shop_name = @retailer_name"
            query_params.append(bigquery.ScalarQueryParameter("retailer_name", "STRING", cleaned_retailer))

        time_range_value = get_time_range_value(time_range)

        # SQL query for category insights
        query = f"""
                WITH filtered_products AS (
                    SELECT
                        v.variant_id,
                        sp.shop_id,
                        COALESCE(c.category_name, 'Uncategorized') AS category_name
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
                        ON v.shop_product_id = sp.shop_product_id
                    LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
                        ON sp.predicted_master_category_id = c.category_id
                    {join_shop}
                    WHERE {retailer_condition}
                ),
                latest_date AS (
                    SELECT MAX(d.full_date) AS full_date
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON pp.date_id = d.date_id
                    JOIN filtered_products fp ON fp.variant_id = pp.variant_id
                    WHERE pp.is_available = TRUE
                ),
                current_snapshot AS (
                    SELECT
                        pp.variant_id,
                        pp.current_price,
                        pp.original_price
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON pp.date_id = d.date_id
                    JOIN latest_date ld ON d.full_date = ld.full_date
                    WHERE pp.variant_id IN (SELECT variant_id FROM filtered_products)
                ),
                historical_reference AS (
                    SELECT
                        pp.variant_id,
                        pp.current_price AS historical_price
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON pp.date_id = d.date_id
                    JOIN latest_date ld ON d.full_date <= DATE_SUB(ld.full_date, INTERVAL {time_range_value} DAY)
                    WHERE pp.variant_id IN (SELECT variant_id FROM filtered_products)
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY pp.variant_id ORDER BY d.full_date DESC) = 1
                ),
                price_window AS (
                    SELECT
                        fp.variant_id,
                        d.full_date,
                        pp.current_price
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON pp.date_id = d.date_id
                    JOIN latest_date ld ON d.full_date BETWEEN DATE_SUB(ld.full_date, INTERVAL {time_range_value} DAY) AND ld.full_date
                    JOIN filtered_products fp ON fp.variant_id = pp.variant_id
                ),
                category_stats AS (
                    SELECT
                        fp.category_name,
                        COUNT(DISTINCT fp.variant_id) AS product_count,
                        AVG(cs.current_price) AS current_avg_price,
                        AVG(
                            CASE
                                WHEN hr.historical_price IS NOT NULL AND hr.historical_price > 0
                                THEN (cs.current_price - hr.historical_price) / hr.historical_price * 100
                                ELSE 0
                            END
                        ) AS price_change_pct,
                        SAFE_DIVIDE(STDDEV(pw.current_price), NULLIF(AVG(pw.current_price), 0)) AS price_volatility,
                        COUNTIF(hr.historical_price IS NOT NULL AND cs.current_price < hr.historical_price) AS deal_count
                    FROM filtered_products fp
                    JOIN current_snapshot cs ON fp.variant_id = cs.variant_id
                    LEFT JOIN historical_reference hr ON fp.variant_id = hr.variant_id
                    LEFT JOIN price_window pw ON fp.variant_id = pw.variant_id
                    GROUP BY fp.category_name
                )
                SELECT
                    category_name,
                    ROUND(current_avg_price, 2) AS avg_price,
                    ROUND(price_change_pct, 2) AS price_change,
                    ROUND(price_volatility, 4) AS price_volatility,
                    product_count,
                    deal_count
                FROM category_stats
                ORDER BY deal_count DESC, product_count DESC
                LIMIT 10
                """

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)

        # Execute query
        query_job = bq_client.query(query, job_config=job_config)
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
        if date_result and hasattr(date_result[0], "full_date"):
            print(f"Category insights using data from: {date_result[0].full_date}")
            historical_date = date_result[0].full_date - timedelta(days=time_range_value)
            print(f"Historical comparison date: {historical_date}")

        # Transform into response format
        insights = []
        for item in results:
            if isinstance(item, dict):
                insights.append(
                    {
                        "category_name": item.get("category_name"),
                        "avg_price": item.get("avg_price", 0),
                        "price_change": item.get("price_change", 0),
                        "price_volatility": item.get("price_volatility", 0),
                        "product_count": item.get("product_count", 0),
                        "deal_count": item.get("deal_count", 0),
                    }
                )
                continue

            category_name = getattr(item, "category_name", None)
            if category_name is None and hasattr(item, "__getitem__"):
                try:
                    category_name = item["category_name"]
                except (KeyError, TypeError):
                    category_name = None

            avg_price = getattr(item, "avg_price", 0)
            price_change = getattr(item, "price_change", 0)
            price_volatility = getattr(item, "price_volatility", 0)
            product_count = getattr(item, "product_count", 0)
            deal_count = getattr(item, "deal_count", 0)

            insights.append(
                {
                    "category_name": category_name,
                    "avg_price": avg_price,
                    "price_change": price_change,
                    "price_volatility": price_volatility,
                    "product_count": product_count,
                    "deal_count": deal_count,
                }
            )

        if not insights:
            insights.append(
                {
                    "category_name": "No data",
                    "avg_price": 0,
                    "price_change": 0,
                    "price_volatility": 0,
                    "product_count": 0,
                    "deal_count": 0,
                }
            )

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