# app/api/v1/analytics/price_history.py

from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Literal, Optional
from app.schemas.analytics.price_history import PriceHistoryResponse
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


@router.get("/price-history", response_model=PriceHistoryResponse, summary="Get price history data")
async def get_price_history(
    time_range: Literal["7d", "30d", "90d", "1y"] = "30d",
    category: str = "all",
    retailer: str = "all",
    view: Literal["detailed", "compact"] = "detailed",
    bq_client=Depends(get_bigquery_client),
):
    """
    Get historical price data for visualization and trend analysis.
    
    - **time_range**: The time period for analysis (7d, 30d, 90d, 1y)
    - **category**: Category ID or "all"
    - **retailer**: Shop ID or "all"
    - **view**: Data view mode (detailed or compact)
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
        
        if retailer == "all":
            retailer_filter = "TRUE"
        elif retailer.isdigit():
            retailer_filter = f"s.shop_id = {retailer}"
        else:
            sanitized_retailer = sanitize_string_for_sql(retailer)
            if not sanitized_retailer:
                raise ValueError("Retailer name cannot be empty")
            retailer_filter = f"s.shop_name = '{sanitized_retailer}'"
            
        time_range_value = get_time_range_value(time_range)
        
        # SQL query for price history
        query = f"""
        WITH date_range AS (
          SELECT date_id, full_date
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate`
          WHERE full_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {time_range_value} DAY)
        ),
        category_filter AS (
          SELECT variant_id
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
          {f'JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id' if not category.isdigit() and category != 'all' else ''}
          WHERE {category_filter}
        ),
        shop_filter AS (
          SELECT v.variant_id
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
          WHERE {retailer_filter}
        ),
        daily_prices AS (
        SELECT
            full_date as date,
            AVG(current_price) as avg_price,
            MIN(current_price) as lowest_price,
            SUM(CASE WHEN current_price < prev_price THEN 1 ELSE 0 END) as price_drops
        FROM (
            SELECT
                pp.variant_id,
                d.full_date,
                pp.current_price,
                LAG(pp.current_price) OVER(PARTITION BY pp.variant_id ORDER BY d.full_date) as prev_price
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
            JOIN date_range d ON pp.date_id = d.date_id
            JOIN category_filter cf ON pp.variant_id = cf.variant_id
            JOIN shop_filter sf ON pp.variant_id = sf.variant_id
            WHERE pp.is_available = TRUE
        ) t
        GROUP BY full_date
        ORDER BY full_date
        )
        SELECT
          FORMAT_DATE('%Y-%m-%d', date) as date,
          ROUND(avg_price, 2) as avg_price,
          ROUND(lowest_price, 2) as lowest_price,
          price_drops,
          -- Logic to determine if it's a good time to buy
          CASE WHEN price_drops > (SELECT AVG(price_drops) * 1.5 FROM daily_prices)
               THEN TRUE ELSE FALSE END as is_good_time_to_buy
        FROM daily_prices
        """
        
        # Execute query
        query_job = bq_client.query(query)
        results = list(query_job.result())
        
        # Format results based on view type
        if view == "compact" and len(results) > 5:
            # For compact view, downsample to reduce data points
            step = len(results) // 5
            price_history_data = [results[i] for i in range(0, len(results), step)]
            # Always include most recent data point
            if price_history_data[-1] != results[-1]:
                price_history_data.append(results[-1])
        else:
            price_history_data = results
            
        # Transform into response format
        price_history = [
            {
                "date": item.date,
                "avg_price": item.avg_price,
                "lowest_price": item.lowest_price,
                "price_drops": item.price_drops,
                "is_good_time_to_buy": item.is_good_time_to_buy
            }
            for item in price_history_data
        ]
        
        # Generate buying recommendation based on the data
        recommendation, confidence = generate_buying_recommendation(price_history)
        
        return {
            "price_history": price_history,
            "best_time_to_buy": {
                "recommendation": recommendation,
                "confidence": confidence
            }
        }
        
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
            raise HTTPException(status_code=500, detail=f"Error retrieving price history data: {error_message}")


def generate_buying_recommendation(price_history):
    """Generate recommendation about buying timing based on price history data"""
    if not price_history:
        return "Insufficient data to make a recommendation.", 0
    
    # Simple algorithm for recommendation - this can be enhanced
    price_drops_count = sum(1 for item in price_history if item.get("is_good_time_to_buy", False))
    recent_trends = price_history[-3:] if len(price_history) >= 3 else price_history
    
    recent_drops = sum(1 for item in recent_trends if item.get("is_good_time_to_buy", False))
    
    if recent_drops >= 2:
        return "Consider buying now. Prices have been trending downward recently.", 85
    elif price_drops_count > len(price_history) * 0.4:
        return "Prices are fluctuating but generally trending down. Consider waiting for another drop.", 70
    elif any(item.get("is_good_time_to_buy", False) for item in recent_trends):
        return "Recent price activity suggests there may be further price drops soon.", 60
    else:
        return "Prices have been stable. You may want to wait for a price drop.", 50