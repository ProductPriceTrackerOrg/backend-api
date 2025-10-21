# app/api/v1/analytics/market_summary.py

from fastapi import APIRouter, Query, Depends, HTTPException, Response
from typing import Literal
import logging
from google.cloud import bigquery

from app.schemas.analytics.market_summary import MarketSummaryResponse
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


@router.get("/market-summary", response_model=MarketSummaryResponse, summary="Get market summary data")
async def get_market_summary(
    response: Response,
    category: str = "all",
    retailer: str = "all",
    time_range: Literal["7d", "30d", "90d", "1y"] = "30d",
    max_categories: int = Query(5, le=10),
    bq_client=Depends(get_bigquery_client),
):
    """
    Get overall market summary and distribution.
    
    - **category**: Category ID or "all"
    - **retailer**: Shop ID or "all"
    - **time_range**: The time period for analysis (7d, 30d, 90d, 1y)
    - **max_categories**: Number of distinct categories to return in distribution (max 10)
    """
    # Cache key based on parameters
    cache_key = f"market_summary:{category}:{retailer}:{time_range}:{max_categories}"

    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data

    try:
        time_range_value = get_time_range_value(time_range)

        # Build filter conditions and query parameters
        category_condition = "TRUE"
        retailer_condition = "TRUE"
        query_params = []
        join_category = f"LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id"
        join_shop = f"LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id"

        if category == "all":
            category_condition = "TRUE"
        elif category.isdigit():
            category_condition = "sp.predicted_master_category_id = @category_id"
            query_params.append(bigquery.ScalarQueryParameter("category_id", "INT64", int(category)))
        else:
            cleaned_category = category.strip()
            if not cleaned_category:
                raise ValueError("Category name cannot be empty")
            category_condition = "c.category_name = @category_name"
            query_params.append(bigquery.ScalarQueryParameter("category_name", "STRING", cleaned_category))

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

        query = f"""
        WITH filtered_products AS (
          SELECT
            v.variant_id,
            sp.shop_id,
            sp.predicted_master_category_id,
            COALESCE(c.category_name, 'Uncategorized') AS category_name
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            ON v.shop_product_id = sp.shop_product_id
          {join_category}
          {join_shop}
          WHERE {category_condition}
            AND {retailer_condition}
        ),
        latest_date AS (
          SELECT MAX(d.full_date) AS full_date
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON fpp.date_id = d.date_id
          JOIN filtered_products fp ON fp.variant_id = fpp.variant_id
          WHERE fpp.is_available = TRUE
        ),
        current_prices AS (
          SELECT
            fpp.variant_id,
            fpp.current_price,
            fpp.original_price
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON fpp.date_id = d.date_id
          JOIN latest_date ld ON d.full_date = ld.full_date
          WHERE fpp.variant_id IN (SELECT variant_id FROM filtered_products)
        ),
        historical_prices AS (
          SELECT
            fpp.variant_id,
            fpp.current_price AS historical_price
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON fpp.date_id = d.date_id
          JOIN latest_date ld ON d.full_date <= DATE_SUB(ld.full_date, INTERVAL {time_range_value} DAY)
          WHERE fpp.variant_id IN (SELECT variant_id FROM filtered_products)
          QUALIFY ROW_NUMBER() OVER (PARTITION BY fpp.variant_id ORDER BY d.full_date DESC) = 1
        ),
        active_products AS (
          SELECT
            fp.variant_id,
            fp.shop_id,
            fp.category_name,
            cp.current_price,
            cp.original_price
          FROM filtered_products fp
          JOIN current_prices cp ON fp.variant_id = cp.variant_id
        ),
        market_metrics AS (
          SELECT
            COUNT(DISTINCT ap.variant_id) AS total_products,
            COUNT(DISTINCT ap.shop_id) AS total_shops,
            AVG(
              CASE
                WHEN hp.historical_price IS NOT NULL AND hp.historical_price != 0
                THEN (ap.current_price - hp.historical_price) / hp.historical_price * 100
                ELSE 0
              END
            ) AS avg_price_change,
            COUNTIF(hp.historical_price IS NOT NULL AND ap.current_price < hp.historical_price) * 100.0 /
              NULLIF(COUNT(ap.variant_id), 0) AS price_drop_percentage
          FROM active_products ap
          LEFT JOIN historical_prices hp ON ap.variant_id = hp.variant_id
        ),
        category_counts AS (
          SELECT
            ap.category_name,
            COUNT(DISTINCT ap.variant_id) AS product_count
          FROM active_products ap
          GROUP BY ap.category_name
        ),
        category_distribution AS (
          SELECT
            category_name,
            product_count,
            ROW_NUMBER() OVER (ORDER BY product_count DESC) AS category_rank
          FROM category_counts
        ),
        category_breakdown AS (
          SELECT
            category_name,
            product_count,
            category_rank,
            CASE
              WHEN category_rank = 1 THEN '#3B82F6'
              WHEN category_rank = 2 THEN '#10B981'
              WHEN category_rank = 3 THEN '#F59E0B'
              WHEN category_rank = 4 THEN '#EF4444'
              ELSE '#8B5CF6'
            END AS color
          FROM category_distribution
          WHERE category_rank <= {max_categories}
        )
        SELECT
          COALESCE(mm.total_products, 0) AS total_products,
          COALESCE(mm.total_shops, 0) AS total_shops,
          ROUND(COALESCE(mm.avg_price_change, 0), 2) AS average_price_change,
          ROUND(COALESCE(mm.price_drop_percentage, 0), 2) AS price_drop_percentage,
          CASE
            WHEN COALESCE(mm.avg_price_change, 0) < -5 AND COALESCE(mm.price_drop_percentage, 0) > 40 THEN 85
            WHEN COALESCE(mm.avg_price_change, 0) < -3 AND COALESCE(mm.price_drop_percentage, 0) > 30 THEN 75
            WHEN COALESCE(mm.avg_price_change, 0) < 0 THEN 65
            WHEN COALESCE(mm.avg_price_change, 0) < 3 THEN 45
            ELSE 30
          END AS best_buying_score,
          ARRAY(
            SELECT AS STRUCT
              cb.category_name AS name,
              cb.product_count AS value,
              cb.color AS color
            FROM category_breakdown cb
            ORDER BY cb.category_rank
          ) AS category_distribution
        FROM market_metrics mm
        """

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = bq_client.query(query, job_config=job_config)
        results = list(query_job.result())

        if not results:
            response_data = {
                "summary": {
                    "total_products": 0,
                    "total_shops": 0,
                    "average_price_change": 0.0,
                    "price_drop_percentage": 0.0,
                    "best_buying_score": 0,
                    "category_distribution": []
                }
            }
        else:
            result = results[0]

            def _extract_field(row, field, default=0):
                if isinstance(row, dict):
                    return row.get(field, default)
                if hasattr(row, "__getitem__"):
                    try:
                        return row[field]
                    except (KeyError, TypeError):
                        pass
                return getattr(row, field, default)

            category_distribution = []
            distribution_rows = getattr(result, "category_distribution", None)
            if distribution_rows:
                for item in distribution_rows:
                    if isinstance(item, dict):
                        category_distribution.append({
                            "name": item.get("name"),
                            "value": item.get("value", 0),
                            "color": item.get("color", "#3B82F6")
                        })
                        continue

                    # Handle BigQuery Row objects
                    name = None
                    value = 0
                    color = "#3B82F6"

                    if hasattr(item, "__getitem__"):
                        try:
                            name = item["name"]
                            value = item.get("value", 0) if hasattr(item, "get") else item["value"]
                            color = item.get("color", "#3B82F6") if hasattr(item, "get") else item["color"]
                        except (KeyError, TypeError):
                            pass

                    if name is None:
                        name = getattr(item, "name", None)
                        value = getattr(item, "value", 0)
                        color = getattr(item, "color", "#3B82F6")

                    if name is not None:
                        category_distribution.append({
                            "name": name,
                            "value": value,
                            "color": color
                        })

            response_data = {
                "summary": {
                    "total_products": _extract_field(result, "total_products", 0) or 0,
                    "total_shops": _extract_field(result, "total_shops", 0) or 0,
                    "average_price_change": _extract_field(result, "average_price_change", 0) or 0,
                    "price_drop_percentage": _extract_field(result, "price_drop_percentage", 0) or 0,
                    "best_buying_score": _extract_field(result, "best_buying_score", 0) or 0,
                    "category_distribution": category_distribution
                }
            }

        cache_service.set(cache_key, response_data, ttl_seconds=900)
        return response_data

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"Invalid input parameter: {str(ve)}")

    except Exception as e:
        error_message = str(e)
        if "Unrecognized name" in error_message and category != "all" and not category.isdigit():
            raise HTTPException(
                status_code=404,
                detail=f"Category '{category}' not found. Please verify the category name or use a category ID instead."
            )
        if "Unrecognized name" in error_message and retailer != "all" and not retailer.isdigit():
            raise HTTPException(
                status_code=404,
                detail=f"Retailer '{retailer}' not found. Please verify the retailer name or use a retailer ID instead."
            )
        raise HTTPException(status_code=500, detail=f"Error retrieving market summary data: {error_message}")
        
