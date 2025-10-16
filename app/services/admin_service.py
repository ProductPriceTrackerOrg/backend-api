# This service will contain all the business logic for the admin dashboard,
# such as querying BigQuery for anomalies or PostgreSQL for user data.
import logging
import pandas as pd
import numpy as np
from google.cloud import bigquery
from app.config import settings
from google.api_core.exceptions import GoogleAPICallError
from app.services.user_service import get_total_users_count
from app.db.supabase_client  import get_supabase_client
from typing import Dict, Any, List
from datetime import date, timedelta

logger = logging.getLogger(__name__)

def get_dashboard_stats_from_db(bq_client: bigquery.Client):
    """
    Fetches live statistics for the admin dashboard directly from BigQuery,
    matching the frontend UI cards.
    """
    try:
        # Query 1: Get total products from DimShopProduct
        products_query = f"""
            SELECT COUNT(DISTINCT shop_product_id) as total_products
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct`
        """
        products_result = bq_client.query(products_query).to_dataframe()
        total_products = int(products_result['total_products'][0]) if not products_result.empty else 0
        
        

        # Query 2: Get total retailers from DimShop
        retailers_query = f"""
            SELECT COUNT(DISTINCT shop_id) as total_retailers
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop`
        """
        retailers_result = bq_client.query(retailers_query).to_dataframe()
        total_retailers = int(retailers_result['total_retailers'][0]) if not retailers_result.empty else 0
        
        # Query 3: Get total categories from DimCategory
        categories_query = f"""
            SELECT COUNT(DISTINCT category_id) as total_categories
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory`
        """
        # Check if DimCategory table exists, if not provide a default value
        try:
            categories_result = bq_client.query(categories_query).to_dataframe()
            total_categories = int(categories_result['total_categories'][0]) if not categories_result.empty else 0
        except Exception as e:
            print(f"Warning: Could not fetch categories count. Table might not exist yet: {e}")
            total_categories = 0

        # Get total users from Supabase via the user service
        total_users = get_total_users_count()
        
        
        # Return stats with explicit type conversion to ensure all values are standard Python types
        stats = {
            "totalProducts": int(total_products),
            "totalRetailers": int(total_retailers),
            "totalUsers": int(total_users),
            "totalCategories": int(total_categories)
        }
        return stats

    except GoogleAPICallError as e:
        # Handle potential API errors (e.g., permissions, table not found)
        print(f"An error occurred while querying BigQuery for dashboard stats: {e}")
        # Return a default/error state that matches the expected keys
        return {
            "totalProducts": 0,
            "totalRetailers": 0,
            "totalUsers": 0,
            "totalCategories": 0,
            "error": str(e)
        }

def get_pipeline_status_from_db():
    """
    Placeholder for fetching pipeline status.
    """
    pass

# Get Pending Anomalies 
def get_pending_anomalies(bq_client: bigquery.Client, page: int = 1, per_page: int = 20):
    """
    Fetches a paginated list of anomalies that are pending review.
    This version now correctly calculates the 'oldPrice' by looking at the
    price from the day before the anomaly.
    """
    offset = (page - 1) * per_page
    # This query is now more advanced. It uses a CTE and a LAG window function
    # to find the price of each product on the day before the anomaly.
    query = f"""
        WITH PriceHistory AS (
            -- Step 1: Create a history of prices for each variant, including the previous day's price.
            SELECT
                price_fact_id,
                variant_id,
                date_id,
                current_price,
                -- The LAG function looks back one row in the partition (ordered by date)
                -- to get the price from the previous day for that specific variant.
                LAG(current_price, 1) OVER (PARTITION BY variant_id ORDER BY date_id) as previous_day_price
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
        )
        -- Step 2: Join the anomaly data with our enriched price history.
        SELECT
            fa.anomaly_id,
            dp.product_title_native AS productName,
            ph.current_price AS anomalousPrice,
            -- This is the key change: 'oldPrice' is now the actual previous day's price.
            ph.previous_day_price AS oldPrice,
            dp.product_url AS productUrl,
            ds.website_url AS vendorUrl,
            fa.anomaly_type
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` AS fa
        -- Join to our enriched price history instead of the raw price table
        LEFT JOIN PriceHistory AS ph ON fa.price_fact_id = ph.price_fact_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` AS dv ON ph.variant_id = dv.variant_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` AS dp ON dv.shop_product_id = dp.shop_product_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` AS ds ON dp.shop_id = ds.shop_id
        WHERE fa.status = 'PENDING_REVIEW'
        ORDER BY fa.anomaly_id DESC
        LIMIT {per_page} OFFSET {offset}
    """
    try:
        df = bq_client.query(query).to_dataframe()

        if df.empty:
            return []
        
        # --- Data Sanitization and Transformation ---
        if 'anomaly_id' in df.columns:
            df['anomaly_id'] = df['anomaly_id'].astype(str)

        float_columns = ['anomalousPrice', 'oldPrice']
        for col in float_columns:
            if col in df.columns:
                df[col] = df[col].replace([np.inf, -np.inf], np.nan)

        return df.to_dict('records')

    except (GoogleAPICallError, Exception) as e:
        print(f"An error occurred while fetching anomalies: {e}")
        return [{"error": str(e)}]
    
      
    
# Resolve an Anomaly
def resolve_anomaly(bq_client: bigquery.Client, anomaly_id: int, resolution: str, user_id: str):
    """
    Updates the status and reviewed_by_user_id of a specific anomaly in BigQuery.
    """
    query = f"""
        UPDATE `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly`
        SET status = @resolution, reviewed_by_user_id = @user_id
        WHERE anomaly_id = @anomaly_id
    """
    # Use query parameters to prevent SQL injection
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("resolution", "STRING", resolution),
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("anomaly_id", "INT64", anomaly_id),
        ]
    )
    try:
        # Execute the query and wait for the job to complete
        bq_client.query(query, job_config=job_config).result()
        return {"status": "success", "message": f"Anomaly {anomaly_id} resolved as {resolution}"}
    except GoogleAPICallError as e:
        print(f"An error occurred while resolving anomaly {anomaly_id}: {e}")
        return {"error": str(e)}


# Category distribution
def get_category_distribution(bq_client: bigquery.Client, start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Fetches the distribution of products across different categories for a pie chart.
    """
    try:
        if bq_client is None: raise Exception("BigQuery client not provided.")

        # This query joins products with categories, filters by date,
        # groups by category name, and counts the products in each.
        query = f"""
            SELECT
                cat.category_name AS name,
                COUNT(prod.shop_product_id) AS value
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` AS prod
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` AS cat
                ON prod.predicted_master_category_id = cat.category_id
            WHERE prod.scraped_date BETWEEN @start_date AND @end_date
            AND cat.category_name IS NOT NULL
            GROUP BY cat.category_name
            ORDER BY value DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )
        
        df = bq_client.query(query, job_config=job_config).to_dataframe()

        if df.empty:
            return []
        
        # The frontend pie chart expects a 'name' and a 'value' for each slice.
        # We can return the raw counts, and the frontend can calculate percentages for the labels.
        return df.to_dict('records')

    except (GoogleAPICallError, Exception) as e:
        print(f"An error occurred while fetching category distribution: {e}")
        return [{"error": str(e)}]


# Top Tracked Products Chart
def get_top_tracked_products(bq_client: bigquery.Client, start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Fetches the top 10 most tracked products by users within a date range.
    This version correctly joins Supabase 'variant_id' with BigQuery 'shop_product_id'.
    """
    try:
        # Step 1: Query Supabase to get the top 10 product IDs and their favorite counts
        supabase = get_supabase_client()
        
        rpc_params = {'start_date_param': str(start_date), 'end_date_param': str(end_date)}
        top_products_response = supabase.rpc('get_top_tracked_products', rpc_params).execute()
        
        top_products_data = top_products_response.data
        if not top_products_data:
            return []

        # Extract the shop_product_ids to use in the BigQuery query
        shop_product_ids = [item['shop_product_id_result'] for item in top_products_data]
        
        # Create a mapping of shop_product_id to user_count for later joining
        user_counts = {item['shop_product_id_result']: item['user_count_result'] for item in top_products_data}

        # Step 2: Query BigQuery to get the product names for those shop_product_ids
        if not bq_client: raise Exception("BigQuery client not provided.")

        # This query is now much simpler and correct.
        query = f"""
            SELECT
                p.shop_product_id,
                p.product_title_native AS productName
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` AS p
            WHERE p.shop_product_id IN UNNEST(@shop_product_ids)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("shop_product_ids", "INT64", shop_product_ids),
            ]
        )
        product_names_df = bq_client.query(query, job_config=job_config).to_dataframe()

        if product_names_df.empty:
            return []

        # Step 3: Combine the results in Python
        # Add the 'userCount' to our DataFrame of product names
        product_names_df['userCount'] = product_names_df['shop_product_id'].map(user_counts)
        
        # Drop the shop_product_id as it's not needed by the frontend
        final_df = product_names_df.drop(columns=['shop_product_id'])
        
        # Sort by userCount descending to ensure the chart is ordered correctly
        final_df = final_df.sort_values('userCount', ascending=False)
        
        # Sanitize data to prevent JSON errors
        final_df.replace([np.inf, -np.inf], np.nan, inplace=True)
        return final_df.where(pd.notna(final_df), None).to_dict('records')

    except (GoogleAPICallError, Exception) as e:
        print(f"An error occurred while fetching top tracked products: {e}")
        return [{"error": str(e)}]

# Function for getting the recent admin activities
def get_recent_admin_activity() -> List[Dict[str, Any]]:
    """
    Fetches the 5 most recent admin activities from the audit log table in Supabase.
    """
    try:
        supabase = get_supabase_client()
        
        # Query the new log table, order by the creation time, and get the latest 10.
        response = supabase.table('adminactivitylog').select(
            'admin_user_id, action_type, target_entity_id, details_json, activity_timestamp'
        ).order('activity_timestamp', desc=True).limit(10).execute()

        activities = []
        for item in response.data:
            action_string = ""
            # Construct the human-readable "Action" string based on the structured data
            if item['action_type'] == 'RESOLVE_ANOMALY':
                resolution = item.get('details_json', {}).get('resolution', 'resolved')
                action_string = f"Marked anomaly #{item['target_entity_id']} as '{resolution}'."
            elif item['action_type'] == 'UPDATE_USER_STATUS':
                new_status = item.get('details_json', {}).get('new_status', 'updated')
                action_string = f"Changed status of user #{item['target_entity_id']} to {new_status}."
            else:
                action_string = item.get('action_type', 'Performed an unknown action.').replace('_', ' ').title()

            activities.append({
                "admin": item['admin_user_id'], # In a real app, you'd join to get the email
                "action": action_string,
                "timestamp": item['activity_timestamp']
            })
        
        return activities
    except Exception as e:
        print(f"An error occurred while fetching admin activity from Supabase: {e}")
        return [{"error": str(e)}]


# Function for getting the price history of an anomalous product
def get_price_history_for_anomaly(bq_client: bigquery.Client, anomaly_id: int, days: int = 30) -> List[Dict[str, Any]]:
    """
    Fetches the price history for the variant associated with a specific anomaly.
    It performs a lookup to find the variant_id from the anomaly_id.
    """
    try:
        if bq_client is None: raise Exception("BigQuery client not provided.")

        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)

        # This single, efficient query performs the exact lookup you described:
        # Anomaly ID -> Price Fact ID -> Variant ID -> Price History
        query = f"""
            -- Step 2: Fetch the price history for the variant_id we found.
            SELECT
                d.full_date AS date,
                fp.current_price AS price
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` AS fp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` AS d ON fp.date_id = d.date_id
            WHERE
                -- This subquery is the key. It finds the correct variant_id.
                fp.variant_id = (
                    SELECT price_table.variant_id
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` AS anomaly_table
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` AS price_table
                        ON anomaly_table.price_fact_id = price_table.price_fact_id
                    WHERE anomaly_table.anomaly_id = @anomaly_id
                    LIMIT 1
                )
            AND d.full_date BETWEEN @start_date AND @end_date
            ORDER BY d.full_date ASC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("anomaly_id", "INT64", anomaly_id),
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )

        df = bq_client.query(query, job_config=job_config).to_dataframe()

        if df.empty:
            return []

        # Sanitize and convert to records
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        return df.where(pd.notna(df), None).to_dict('records')

    except (GoogleAPICallError, Exception) as e:
        print(f"An error occurred while fetching price history for anomaly {anomaly_id}: {e}")
        return [{"error": str(e)}]

