# app/api/v1/analytics/market_summary.py

from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Literal, Optional, List
from app.schemas.analytics.market_summary import MarketSummaryResponse
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


@router.get("/market-summary", response_model=MarketSummaryResponse, summary="Get market summary data")
async def get_market_summary(
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
            
        time_range_value = get_time_range_value(time_range)
        
        # SQL query for market summary
        query = f"""
        WITH sample_data_check AS (
          -- Check if we have any data in the tables at all
          SELECT COUNT(*) as product_count
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant`
          LIMIT 1
        ),
        current_date_id AS (
          SELECT date_id 
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate`
          WHERE full_date = CURRENT_DATE()
        ),
        historical_date_id AS (
          SELECT date_id 
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate`
          WHERE full_date = DATE_SUB(CURRENT_DATE(), INTERVAL {time_range_value} DAY)
        ),
        market_metrics AS (
          SELECT
            COALESCE(COUNT(DISTINCT v.variant_id), 0) as total_products,
            COALESCE(COUNT(DISTINCT sp.shop_id), 0) as total_shops,
            COALESCE(
              AVG(
                CASE WHEN historical_pp.current_price IS NOT NULL AND historical_pp.current_price != 0
                THEN (current_pp.current_price - historical_pp.current_price) / historical_pp.current_price * 100
                ELSE 0 END
              ), 
              0
            ) as avg_price_change,
            (COUNT(CASE WHEN current_pp.current_price < historical_pp.current_price THEN 1 END) * 100.0 /
              NULLIF(COUNT(v.variant_id), 0)) as price_drop_percentage
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON v.shop_product_id = sp.shop_product_id
          {f'JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id' if not category.isdigit() and category != 'all' else ''}
          {f'JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id' if not retailer.isdigit() and retailer != 'all' else ''}
          -- Current prices (today)
          JOIN current_date_id cdi ON 1=1
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` current_pp
            ON v.variant_id = current_pp.variant_id
            AND current_pp.date_id = cdi.date_id
          -- Historical prices (for comparison)
          LEFT JOIN historical_date_id hdi ON 1=1
          LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` historical_pp
            ON v.variant_id = historical_pp.variant_id
            AND historical_pp.date_id = hdi.date_id
          WHERE
            current_pp.is_available = TRUE
            AND {category_filter}
            AND {retailer_filter}
        ),
        category_distribution AS (
          SELECT
            c.category_name,
            COUNT(DISTINCT v.variant_id) as product_count,
            ROW_NUMBER() OVER (ORDER BY COUNT(DISTINCT v.variant_id) DESC) as category_rank
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON c.category_id = sp.predicted_master_category_id
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
          {f'JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id' if not retailer.isdigit() and retailer != 'all' else ''}
          JOIN current_date_id cdi ON 1=1
          JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` pp
            ON v.variant_id = pp.variant_id
            AND pp.date_id = cdi.date_id
          WHERE
            pp.is_available = TRUE
            AND {retailer_filter}
          GROUP BY c.category_name
          ORDER BY product_count DESC
          LIMIT {max_categories}
        ),
        top_categories AS (
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
            END as color
          FROM category_distribution
        )
        SELECT
          mm.total_products,
          mm.total_shops,
          ROUND(mm.avg_price_change, 2) as average_price_change,
          ROUND(mm.price_drop_percentage, 2) as price_drop_percentage,
          -- Calculate buying score based on price drops and availability
          CASE
            WHEN mm.avg_price_change < -5 AND mm.price_drop_percentage > 40 THEN 85
            WHEN mm.avg_price_change < -3 AND mm.price_drop_percentage > 30 THEN 75
            WHEN mm.avg_price_change < 0 THEN 65
            WHEN mm.avg_price_change < 3 THEN 45
            ELSE 30
          END as best_buying_score,
          ARRAY_AGG(
            STRUCT(
              tc.category_name as name,
              tc.product_count as value,
              tc.color as color
            )
            ORDER BY tc.category_rank ASC
          ) as category_distribution
        FROM market_metrics mm
        CROSS JOIN top_categories tc
        GROUP BY mm.total_products, mm.total_shops, mm.avg_price_change, mm.price_drop_percentage
        """
        
        # Execute query
        try:
            # First check if the date_id exists
            date_check_query = f"""
            SELECT COUNT(*) as date_count 
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate`
            WHERE full_date = CURRENT_DATE()
            """
            date_check_job = bq_client.query(date_check_query)
            date_check_result = list(date_check_job.result())[0]
            
            if date_check_result.date_count == 0:
                # We're missing date entries for today, so we'll use the most recent date instead
                latest_date_query = f"""
                SELECT MAX(full_date) as latest_date
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate`
                """
                latest_date_job = bq_client.query(latest_date_query)
                latest_date = list(latest_date_job.result())[0].latest_date
                
                # Update the main query with the latest date
                query = query.replace("CURRENT_DATE()", f"DATE('{latest_date}')")
            
            # Now execute the main query
            query_job = bq_client.query(query)
            results = list(query_job.result())
            
            # Handle case where no results were found
            if not results:
                return {
                    "summary": {
                        "total_products": 0,
                        "total_shops": 0,
                        "average_price_change": 0.0,
                        "price_drop_percentage": 0.0,
                        "best_buying_score": 0,
                        "category_distribution": []
                    }
                }
                
            result = results[0]
        except Exception as e:
            # Add more detailed error handling for BigQuery issues
            raise HTTPException(
                status_code=500, 
                detail=f"BigQuery execution error: {str(e)}"
            )
        
        # Transform into response format
        # Handle category distribution conversion from BigQuery ARRAY to Python list
        category_distribution = []
        
        # Check if category_distribution exists and is not None
        if hasattr(result, 'category_distribution') and result.category_distribution is not None:
            try:
                for item in result.category_distribution:
                    # Handle different ways items might be represented in the BigQuery response
                    item_dict = {}
                    if hasattr(item, '__dict__'):  # If it's an object we can convert to dict
                        item_dict = {
                            "name": getattr(item, 'name', None),
                            "value": getattr(item, 'value', 0),
                            "color": getattr(item, 'color', '#3B82F6')
                        }
                    elif isinstance(item, dict):  # If it's already a dict
                        item_dict = {
                            "name": item.get('name', None),
                            "value": item.get('value', 0),
                            "color": item.get('color', '#3B82F6')
                        }
                    else:
                        # Try other ways to access data
                        try:
                            # Some BigQuery results provide dict-like access without being a dict
                            item_dict = {
                                "name": item['name'] if 'name' in item else None,
                                "value": item['value'] if 'value' in item else 0,
                                "color": item['color'] if 'color' in item else '#3B82F6'
                            }
                        except (TypeError, KeyError):
                            print(f"Could not process category item: {item}, type: {type(item)}")
                            continue
                    
                    # Only add if we have a name
                    if item_dict.get("name") is not None:
                        category_distribution.append(item_dict)
            except Exception as e:
                print(f"Error processing category distribution: {e}")
                # In case of any error, provide empty category distribution
                category_distribution = []
        
        return {
            "summary": {
                "total_products": result.total_products,
                "total_shops": result.total_shops,
                "average_price_change": result.average_price_change,
                "price_drop_percentage": result.price_drop_percentage,
                "best_buying_score": result.best_buying_score,
                "category_distribution": category_distribution
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
            raise HTTPException(status_code=500, detail=f"Error retrieving market summary data: {error_message}")