# app/api/v1/analytics/price_alerts.py

from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Literal, Optional, List
from datetime import timedelta
import logging
from app.schemas.analytics.price_alerts import PriceAlertsResponse
from app.config import settings
from app.api.deps import get_bigquery_client
from app.services.async_query_service import async_query_service
from app.services.cache_service import cache_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


def sanitize_string_for_sql(input_str: str) -> str:
    """
    Sanitize a string to be used safely in SQL queries.
    Replaces single quotes with two single quotes to prevent SQL injection.
    """
    if not input_str:
        return ""
    return input_str.replace("'", "''")


@router.get("/price-alerts", response_model=PriceAlertsResponse, summary="Get price alerts")
async def get_price_alerts(
    category: str = "all",
    retailer: str = "all",
    limit: int = Query(10, le=50),
    format: Literal["compact", "detailed"] = "detailed",
    bq_client=Depends(get_bigquery_client),
):
    """
    Get significant price changes and anomalies.
    
    - **category**: Category ID or "all"
    - **retailer**: Shop ID or "all"
    - **limit**: Number of alerts to return (max 50)
    - **format**: Data format (compact or detailed)
    """
    # Cache key based on parameters
    cache_key = f"price_alerts:{category}:{retailer}:{limit}:{format}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    # Default fallback data in case of timeout or error
    fallback_data = {
        "alerts": []
    }
    
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
        
        if retailer == "all":
            retailer_filter = "TRUE"
        elif retailer.isdigit():
            retailer_filter = f"sp.shop_id = {retailer}"
        else:
            sanitized_retailer = sanitize_string_for_sql(retailer)
            if not sanitized_retailer:
                raise ValueError("Retailer name cannot be empty")
            retailer_filter = f"s.shop_name = '{sanitized_retailer}'"
        
        # SQL query for price alerts
        alerts_query = f"""
        WITH recent_anomalies AS (
          SELECT
            pa.anomaly_id,
            pa.anomaly_type,
            pa.price_fact_id,
            pa.anomaly_score,
            v.variant_id,
            sp.shop_product_id,
            pa.created_at as detected_date
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` pa
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp ON pa.price_fact_id = pp.price_fact_id
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON pp.variant_id = v.variant_id
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON v.shop_product_id = sp.shop_product_id
          {f'JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id' if not category.isdigit() and category != 'all' else ''}
          {f'JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id' if not retailer.isdigit() and retailer != 'all' else ''}
          WHERE
            pa.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
            AND pa.anomaly_score >= 0.7
            AND {category_filter}
            AND {retailer_filter}
          ORDER BY pa.anomaly_score DESC
          LIMIT 100
        ),
        product_images AS (
          SELECT
            pi.shop_product_id,
            pi.image_url,
            ROW_NUMBER() OVER (PARTITION BY pi.shop_product_id ORDER BY pi.sort_order ASC) as row_num
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi
        ),
        alert_details AS (
          SELECT
            CAST(ra.anomaly_id AS STRING) as id,
            sp.product_title_native as product_title,
            COALESCE(img.image_url, '/placeholder.jpg') as image_url,
            historical_pp.current_price as original_price,
            current_pp.current_price as current_price,
            ((current_pp.current_price - historical_pp.current_price) / NULLIF(historical_pp.current_price, 0)) * 100 as percentage_change,
            s.shop_name,
            FORMAT_TIMESTAMP('%Y-%m-%d', ra.detected_date) as detected_date,
            CONCAT('/product/', CAST(sp.shop_product_id AS STRING)) as product_url,
            CASE
              WHEN ra.anomaly_type = 'PRICE_DROP' THEN 'price_drop'
              WHEN ra.anomaly_type = 'FLASH_SALE' THEN 'flash_sale'
              WHEN ra.anomaly_type = 'BACK_IN_STOCK' THEN 'back_in_stock'
              ELSE 'unusual_discount'
            END as type
          FROM recent_anomalies ra
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON ra.shop_product_id = sp.shop_product_id
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
          LEFT JOIN product_images img ON sp.shop_product_id = img.shop_product_id AND img.row_num = 1
          -- Find the latest date with price data
          JOIN (
            WITH LatestAvailableDate AS (
              SELECT MAX(d.date_id) as latest_date_id, MAX(d.full_date) as latest_date
              FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
              JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON pp.date_id = d.date_id
            )
            SELECT pp.*
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON pp.date_id = d.date_id
            JOIN LatestAvailableDate lad ON d.date_id = lad.latest_date_id
          ) current_pp
            ON ra.variant_id = current_pp.variant_id
          -- Get historical price data from 14 days before the latest date
          JOIN (
            WITH LatestAvailableDate AS (
              SELECT MAX(d.date_id) as latest_date_id, MAX(d.full_date) as latest_date
              FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
              JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON pp.date_id = d.date_id
            ),
            HistoricalDate AS (
              SELECT MAX(d.date_id) as historical_date_id
              FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d
              JOIN LatestAvailableDate lad ON d.full_date = DATE_SUB(lad.latest_date, INTERVAL 14 DAY)
            )
            SELECT pp.*
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
            JOIN HistoricalDate hd ON pp.date_id = hd.historical_date_id
          ) historical_pp
            ON ra.variant_id = historical_pp.variant_id
          WHERE current_pp.is_available = TRUE
        )
        SELECT
          id,
          product_title,
          image_url,
          ROUND(original_price, 2) as original_price,
          ROUND(current_price, 2) as current_price,
          ROUND(percentage_change, 2) as percentage_change,
          shop_name,
          detected_date,
          product_url,
          type
        FROM alert_details
        ORDER BY detected_date DESC, ABS(percentage_change) DESC
        LIMIT {limit}
        """
        
        # Date query for logging purposes only
        date_query = f"""
        WITH LatestAvailableDate AS (
          SELECT MAX(d.date_id) as latest_date_id, MAX(d.full_date) as latest_date
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON pp.date_id = d.date_id
        )
        SELECT latest_date FROM LatestAvailableDate
        """
        
        # Function to process alerts results
        def process_alerts_results(results):
            alerts = []
            for item in results:
                alert = {
                    "id": item.get("id"),
                    "product_title": item.get("product_title"),
                    "image_url": item.get("image_url"),
                    "original_price": item.get("original_price"),
                    "current_price": item.get("current_price"),
                    "percentage_change": item.get("percentage_change"),
                    "shop_name": item.get("shop_name"),
                    "detected_date": item.get("detected_date"),
                    "product_url": item.get("product_url"),
                    "type": item.get("type")
                }
                
                # For compact format, only include essential fields
                if format == "compact":
                    compact_alert = {
                        "id": item.get("id"),
                        "product_title": item.get("product_title"),
                        "image_url": item.get("image_url"),
                        "percentage_change": item.get("percentage_change"),
                        "type": item.get("type")
                    }
                    alerts.append(compact_alert)
                else:
                    alerts.append(alert)
            return {"alerts": alerts}
        
        # Execute queries in parallel with timeouts
        query_configs = [
            {
                "query": alerts_query,
                "result_key": "alerts",
                "cache_key": None,  # Don't cache intermediate results
                "timeout": 15,  # 15 second timeout for this query
                "fallback_data": [],
                "transform_func": None
            },
            {
                "query": date_query,
                "result_key": "date",
                "cache_key": None,
                "timeout": 5,  # 5 second timeout for this simple query
                "fallback_data": None,
                "transform_func": None
            }
        ]
        
        # Execute queries asynchronously
        results = await async_query_service.execute_queries_parallel(bq_client, query_configs)
        
        alerts_results = results.get("alerts")
        date_results = results.get("date")
        
        # Process the date results for logging
        if date_results and len(date_results) > 0 and "latest_date" in date_results[0]:
            logger.info(f"Price alerts using data from: {date_results[0]['latest_date']}")
            historical_date = date_results[0]["latest_date"] - timedelta(days=14)
            logger.info(f"Historical comparison date: {historical_date}")
            
        # Process alerts results
        if alerts_results and len(alerts_results) > 0:
            response_data = process_alerts_results(alerts_results)
            
            # Cache the successful results for 15 minutes
            cache_service.set(cache_key, response_data, ttl_seconds=900)
            
            return response_data
        
        return fallback_data
        
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
        elif "Unrecognized name" in error_message and retailer != "all" and not retailer.isdigit():
            # Provide a more helpful error message for retailer name issues
            raise HTTPException(
                status_code=404, 
                detail=f"Retailer '{retailer}' not found. Please verify the retailer name or use a retailer ID instead."
            )
        else:
            raise HTTPException(status_code=500, detail=f"Error retrieving price alerts: {error_message}")