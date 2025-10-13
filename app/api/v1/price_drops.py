"""
API endpoints for price drops.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from typing import Dict, List, Optional, Any
from enum import Enum
from google.cloud import bigquery
import logging
import datetime

from app.config import settings
from app.api.deps import get_bigquery_client
from app.services.cache_service import cache_service
from app.services.async_query_service import async_query_service
from app.schemas.price_drops import PriceDropResponse, PriceDropStatsResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()


class TimeRangeEnum(str, Enum):
    """Time range options for price drops."""
    LAST_24H = "24h"
    LAST_7D = "7d"
    LAST_30D = "30d"
    LAST_90D = "90d"


class SortByEnum(str, Enum):
    """Sort options for price drops."""
    DISCOUNT_PERCENTAGE = "discount_percentage"
    DISCOUNT_AMOUNT = "discount_amount"
    MOST_RECENT = "most_recent"
    PRICE = "price"


def get_days_from_time_range(time_range: TimeRangeEnum) -> int:
    """Convert time range enum to number of days."""
    mapping = {
        TimeRangeEnum.LAST_24H: 1,
        TimeRangeEnum.LAST_7D: 7,
        TimeRangeEnum.LAST_30D: 30,
        TimeRangeEnum.LAST_90D: 90
    }
    return mapping.get(time_range, 7)


def sanitize_string_for_sql(input_str: str) -> str:
    """Sanitize a string for use in SQL queries."""
    if not input_str:
        return ""
    return input_str.replace("'", "''")


@router.get("/price-drops", response_model=PriceDropResponse)
async def get_price_drops(
    response: Response,
    time_range: TimeRangeEnum = TimeRangeEnum.LAST_7D,
    category: Optional[str] = None,
    retailer: Optional[str] = None,
    min_discount: float = Query(5.0, ge=0, le=100),
    sort_by: SortByEnum = SortByEnum.DISCOUNT_PERCENTAGE,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get products with price drops based on specified filters.
    
    - **time_range**: Time range for price drops (24h, 7d, 30d, 90d)
    - **category**: Filter by category ID or name
    - **retailer**: Filter by retailer ID or name
    - **min_discount**: Minimum discount percentage
    - **sort_by**: Sort by discount percentage, amount, recency, or price
    - **page**: Page number for pagination
    - **limit**: Number of results per page
    """
    # Calculate offset for pagination
    offset = (page - 1) * limit
    
    # Create a cache key based on all parameters
    cache_key = f"price_drops:{time_range}:{category or 'all'}:{retailer or 'all'}:{min_discount}:{sort_by}:{page}:{limit}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    # Set up filters
    days = get_days_from_time_range(time_range)
    
    # Category filter
    if category:
        if category.isdigit():
            category_filter = f"sp.predicted_master_category_id = {category}"
        else:
            sanitized_category = sanitize_string_for_sql(category)
            category_filter = f"c.category_name = '{sanitized_category}'"
    else:
        category_filter = "TRUE"
    
    # Retailer filter
    if retailer:
        if retailer.isdigit():
            retailer_filter = f"sp.shop_id = {retailer}"
        else:
            sanitized_retailer = sanitize_string_for_sql(retailer)
            retailer_filter = f"s.shop_name = '{sanitized_retailer}'"
    else:
        retailer_filter = "TRUE"
    
    # Discount filter - we look for price drops (negative percentage change)
    discount_filter = f"pc.percentage_change < 0 AND ABS(pc.percentage_change) >= {min_discount}"
    
    # Sort order
    if sort_by == SortByEnum.DISCOUNT_PERCENTAGE:
        sort_order = "pc.percentage_change ASC"  # ASC because negative changes are price drops
    elif sort_by == SortByEnum.DISCOUNT_AMOUNT:
        sort_order = "pc.price_change ASC"  # ASC because negative changes are price drops
    elif sort_by == SortByEnum.MOST_RECENT:
        sort_order = "pc.change_date DESC"
    else:  # PRICE
        sort_order = "pc.current_price ASC"
    
    try:
        # Create the query for price drops data
        data_query = f"""
        WITH
          -- Get all price changes within the specified time range
          PriceHistory AS (
            SELECT
              fpp.variant_id,
              dd.full_date AS date,
              fpp.current_price,
              LAG(fpp.current_price, 1) OVER(PARTITION BY fpp.variant_id ORDER BY dd.full_date) AS previous_price
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` dd ON fpp.date_id = dd.date_id
            WHERE dd.full_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          ),
          
          -- Get the primary image for each product
          ProductImages AS (
            SELECT 
              shop_product_id,
              image_url
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage`
            QUALIFY ROW_NUMBER() OVER(PARTITION BY shop_product_id ORDER BY sort_order ASC) = 1
          ),
          
          -- Find price changes that are drops (current < previous)
          PriceChanges AS (
            SELECT
              variant_id,
              date AS change_date,
              current_price,
              previous_price,
              (current_price - previous_price) AS price_change,
              ROUND(((current_price - previous_price) / NULLIF(previous_price, 0)) * 100, 2) AS percentage_change
            FROM PriceHistory
            WHERE 
              previous_price IS NOT NULL 
              AND current_price < previous_price  -- Only price drops
          ),
          
          -- Count total drops that match filters (for pagination)
          TotalCount AS (
            SELECT 
              COUNT(*) AS total
            FROM PriceChanges pc
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON pc.variant_id = v.variant_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON v.shop_product_id = sp.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
            WHERE
              {discount_filter}
              AND {category_filter}
              AND {retailer_filter}
          )
          
        SELECT
          sp.shop_product_id AS id,
          sp.product_title_native AS name,
          sp.brand_native AS brand,
          COALESCE(c.category_name, 'Uncategorized') AS category,
          pc.current_price,
          pc.previous_price,
          pc.price_change,
          pc.percentage_change,
          s.shop_name AS retailer,
          s.shop_id AS retailer_id,
          pi.image_url AS image,
          CAST(pc.change_date AS STRING) AS change_date,
          TRUE AS in_stock,
          (SELECT total FROM TotalCount) AS total_count
        FROM PriceChanges pc
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON pc.variant_id = v.variant_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON v.shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
        LEFT JOIN ProductImages pi ON sp.shop_product_id = pi.shop_product_id
        WHERE
          {discount_filter}
          AND {category_filter}
          AND {retailer_filter}
        ORDER BY
          {sort_order}
        LIMIT {limit}
        OFFSET {offset}
        """
        
        # Use the async query service with a timeout
        results = await async_query_service.execute_query(
            bq_client=bq_client,
            query=data_query,
            cache_key=None,  # Don't cache intermediate results
            timeout=15,  # 15 second timeout
            fallback_data=[]
        )
        
        if not results or len(results) == 0:
            return {
                "price_drops": [],
                "total_count": 0,
                "next_page": None
            }
        
        # Extract the total count from the first result
        total_count = results[0].get("total_count", len(results))
        
        # Process the results
        price_drops = []
        for item in results:
            # Remove the total_count field which we've already extracted
            if "total_count" in item:
                del item["total_count"]
            price_drops.append(item)
        
        # Calculate next page
        next_page = page + 1 if total_count > (page * limit) else None
        
        # Prepare response
        response_data = {
            "price_drops": price_drops,
            "total_count": total_count,
            "next_page": next_page
        }
        
        # Cache the results for 15 minutes
        cache_service.set(cache_key, response_data, ttl_seconds=900)
        
        return response_data
        
    except Exception as e:
        logger.error(f"Error in get_price_drops: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while querying BigQuery: {str(e)}"
        )


@router.get("/price-drops/stats", response_model=PriceDropStatsResponse)
async def get_price_drops_stats(
    time_range: TimeRangeEnum = TimeRangeEnum.LAST_7D,
    category: Optional[str] = None,
    retailer: Optional[str] = None,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get statistics about price drops.
    
    - **time_range**: Time range for statistics (24h, 7d, 30d, 90d)
    - **category**: Filter by category ID or name
    - **retailer**: Filter by retailer ID or name
    """
    # Create a cache key based on parameters
    cache_key = f"price_drops_stats:{time_range}:{category or 'all'}:{retailer or 'all'}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    # Set up filters
    days = get_days_from_time_range(time_range)
    
    # Category filter
    if category:
        if category.isdigit():
            category_filter = f"sp.predicted_master_category_id = {category}"
        else:
            sanitized_category = sanitize_string_for_sql(category)
            category_filter = f"c.category_name = '{sanitized_category}'"
    else:
        category_filter = "TRUE"
    
    # Retailer filter
    if retailer:
        if retailer.isdigit():
            retailer_filter = f"sp.shop_id = {retailer}"
        else:
            sanitized_retailer = sanitize_string_for_sql(retailer)
            retailer_filter = f"s.shop_name = '{sanitized_retailer}'"
    else:
        retailer_filter = "TRUE"
    
    try:
        # Create the query for statistics
        stats_query = f"""
        WITH
          -- Get all price changes within the specified time range
          PriceHistory AS (
            SELECT
              fpp.variant_id,
              dd.full_date AS date,
              fpp.current_price,
              LAG(fpp.current_price, 1) OVER(PARTITION BY fpp.variant_id ORDER BY dd.full_date) AS previous_price
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` dd ON fpp.date_id = dd.date_id
            WHERE dd.full_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          ),
          
          -- Find price changes that are drops (current < previous)
          PriceChanges AS (
            SELECT
              variant_id,
              date AS change_date,
              current_price,
              previous_price,
              (current_price - previous_price) AS price_change,
              ROUND(((current_price - previous_price) / NULLIF(previous_price, 0)) * 100, 2) AS percentage_change
            FROM PriceHistory
            WHERE 
              previous_price IS NOT NULL 
              AND current_price < previous_price  -- Only price drops
          ),
          
          -- Join with product data for filtering
          FilteredChanges AS (
            SELECT
              pc.*,
              sp.shop_id,
              sp.predicted_master_category_id
            FROM PriceChanges pc
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON pc.variant_id = v.variant_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON v.shop_product_id = sp.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
            WHERE
              {category_filter}
              AND {retailer_filter}
          )
          
        -- Calculate aggregate statistics
        SELECT
          COUNT(*) AS total_drops,
          AVG(ABS(percentage_change)) AS average_discount_percentage,
          COUNT(DISTINCT shop_id) AS retailers_with_drops,
          COUNT(DISTINCT predicted_master_category_id) AS categories_with_drops,
          MAX(ABS(percentage_change)) AS largest_drop_percentage,
          SUM(ABS(price_change)) AS total_savings,
          COUNTIF(DATE(change_date) = CURRENT_DATE()) AS drops_last_24h,
          COUNTIF(change_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) AS drops_last_7d
        FROM FilteredChanges
        """
        
        # Use the async query service with a timeout
        results = await async_query_service.execute_query(
            bq_client=bq_client,
            query=stats_query,
            cache_key=None,  # Don't cache intermediate results
            timeout=10,  # 10 second timeout
            fallback_data=[]
        )
        
        if not results or len(results) == 0:
            # Return default stats if no results
            default_stats = {
                "stats": {
                    "total_drops": 0,
                    "average_discount_percentage": 0.0,
                    "retailers_with_drops": 0,
                    "categories_with_drops": 0,
                    "largest_drop_percentage": 0.0,
                    "total_savings": 0.0,
                    "drops_last_24h": 0,
                    "drops_last_7d": 0
                }
            }
            return default_stats
        
        # Process the first (and only) row of results
        stats_data = results[0]
        
        # Prepare response
        response_data = {
            "stats": {
                "total_drops": stats_data.get("total_drops", 0),
                "average_discount_percentage": round(stats_data.get("average_discount_percentage", 0.0), 2),
                "retailers_with_drops": stats_data.get("retailers_with_drops", 0),
                "categories_with_drops": stats_data.get("categories_with_drops", 0),
                "largest_drop_percentage": round(stats_data.get("largest_drop_percentage", 0.0), 2),
                "total_savings": round(stats_data.get("total_savings", 0.0), 2),
                "drops_last_24h": stats_data.get("drops_last_24h", 0),
                "drops_last_7d": stats_data.get("drops_last_7d", 0)
            }
        }
        
        # Cache the results for 1 hour
        cache_service.set(cache_key, response_data, ttl_seconds=3600)
        
        return response_data
        
    except Exception as e:
        logger.error(f"Error in get_price_drops_stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while querying BigQuery: {str(e)}"
        )