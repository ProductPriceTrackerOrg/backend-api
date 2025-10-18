from fastapi import APIRouter, Depends, HTTPException
from google.cloud import bigquery
from typing import List, Dict
import redis
import json
from datetime import datetime, timedelta
from app.api.deps import get_bigquery_client
from app.config import settings
import logging

router = APIRouter()

# Redis client (assuming Redis is running locally)
redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_cached_data(cache_key: str):
    """Get data from Redis cache, return None if Redis is not available"""
    try:
        return redis_client.get(cache_key)
    except redis.exceptions.ConnectionError:
        logger.warning("Redis connection failed, skipping cache read")
        return None
    except Exception as e:
        logger.warning(f"Redis error during cache read: {e}, skipping cache")
        return None


def set_cache_data(cache_key: str, data: str, expiry: int = 3600):
    """Set data in Redis cache, silently fail if Redis is not available"""
    try:
        redis_client.setex(cache_key, expiry, data)
    except redis.exceptions.ConnectionError:
        logger.warning("Redis connection failed, skipping cache write")
    except Exception as e:
        logger.warning(f"Redis error during cache write: {e}, skipping cache")


@router.get("/price-forecasting/{product_id}", response_model=List[Dict])
async def get_price_forecast(
    product_id: int, bq_client: bigquery.Client = Depends(get_bigquery_client)
):
    """
    Get 7-day price forecast for a specific variant.
    Returns predicted prices with confidence intervals.
    """
    cache_key = f"forecast:{product_id}"

    # Check cache first (optional)
    cached_data = get_cached_data(cache_key)
    if cached_data:
        logger.info(f"Cache hit for forecast:{product_id}")
        return json.loads(cached_data)

    logger.info(f"Cache miss for forecast:{product_id}, querying BigQuery")

    try:
        # Query to get the latest forecast data for each variant and date
        # This gets the most recent prediction for each day based on created_at
        query = f"""
        WITH LatestForecasts AS (
            SELECT
                fpf.variant_id,
                fpf.forecast_date,
                fpf.predicted_price,
                fpf.created_at,
                v.shop_product_id,
                -- Get the latest forecast for each variant-date combination
                ROW_NUMBER() OVER (
                    PARTITION BY fpf.variant_id, fpf.forecast_date
                    ORDER BY fpf.created_at DESC
                ) as rn
            FROM `price-pulse-470211.warehouse.FactPriceForecast` fpf
            JOIN `price-pulse-470211.warehouse.DimVariant` v
                ON fpf.variant_id = v.variant_id
            WHERE v.shop_product_id = {product_id}
            AND fpf.forecast_date >= CURRENT_DATE()  -- Only future dates
            AND fpf.forecast_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)  -- Next 7 days
        )
        SELECT 
            variant_id,
            shop_product_id as product_id,
            forecast_date,
            predicted_price,
            predicted_price * 1.05 as confidence_upper,  -- Simple 5% confidence bounds
            predicted_price * 0.95 as confidence_lower,
            created_at
        FROM LatestForecasts
        WHERE rn = 1  -- Only the latest forecast for each variant-date
        ORDER BY variant_id ASC, forecast_date ASC
        """

        logger.info(f"Executing query for product {product_id}")
        query_job = bq_client.query(query)
        results = query_job.result()

        forecasts = []
        seen_combinations = set()  # Track variant_id + forecast_date combinations

        for row in results:
            combination_key = f"{row.variant_id}_{row.forecast_date}"

            if combination_key in seen_combinations:
                logger.warning(
                    f"Duplicate combination found: variant_id={row.variant_id}, date={row.forecast_date}"
                )
                continue

            seen_combinations.add(combination_key)
            forecasts.append(
                {
                    "product_id": row.product_id,
                    "variant_id": row.variant_id,
                    "forecast_date": row.forecast_date.isoformat(),
                    "predicted_price": float(row.predicted_price),
                    "confidence_upper": float(row.confidence_upper),
                    "confidence_lower": float(row.confidence_lower),
                    "created_at": (
                        row.created_at.isoformat() if row.created_at else None
                    ),
                }
            )

        logger.info(
            f"Returning {len(forecasts)} unique forecasts for product {product_id}"
        )

        # Cache for 1 hour (optional)
        set_cache_data(cache_key, json.dumps(forecasts), 3600)

        return forecasts

    except Exception as e:
        logger.error(f"Error fetching forecast for product {product_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching forecast: {str(e)}"
        )
