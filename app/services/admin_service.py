# This service contains all the business logic for the admin dashboard,
# with caching implementation for performance optimization.
import logging
import pandas as pd
import numpy as np
from google.cloud import bigquery
from app.config import settings
from google.api_core.exceptions import GoogleAPICallError
from app.services.user_service import get_total_users_count
from app.db.supabase_client import get_supabase_client
from app.services.cache_service import cache_service
from typing import Dict, Any, List, Optional
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Cache keys and TTLs for admin services
DASHBOARD_STATS_CACHE_KEY = "admin:dashboard:stats"
DASHBOARD_STATS_CACHE_TTL = 600  # 10 minutes

PENDING_ANOMALIES_CACHE_KEY_PREFIX = "admin:anomalies:page:"
ANOMALIES_CACHE_TTL = 600  # Increased to 10 minutes for better performance

CATEGORY_DISTRIBUTION_CACHE_KEY_PREFIX = "admin:category_distribution:"
CATEGORY_DISTRIBUTION_CACHE_TTL = 3600  # 1 hour

TOP_TRACKED_PRODUCTS_CACHE_KEY_PREFIX = "admin:top_tracked_products:"
TOP_TRACKED_PRODUCTS_CACHE_TTL = 1800  # 30 minutes

RECENT_ADMIN_ACTIVITY_CACHE_KEY = "admin:recent_activity"
RECENT_ADMIN_ACTIVITY_CACHE_TTL = 300  # 5 minutes

PRICE_HISTORY_CACHE_KEY_PREFIX = "admin:anomaly:price_history:"
PRICE_HISTORY_CACHE_TTL = 3600  # 1 hour

def get_dashboard_stats_from_db(bq_client: bigquery.Client):
    """
    Fetches live statistics for the admin dashboard directly from BigQuery,
    matching the frontend UI cards. Uses cache for better performance.
    """
    # Try to get from cache first
    cached_stats = cache_service.get(DASHBOARD_STATS_CACHE_KEY)
    if cached_stats is not None:
        return cached_stats
        
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
            logger.warning(f"Could not fetch categories count. Table might not exist yet: {e}")
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
        
        # Cache the result
        cache_service.set(DASHBOARD_STATS_CACHE_KEY, stats, DASHBOARD_STATS_CACHE_TTL)
        
        return stats

    except GoogleAPICallError as e:
        # Handle potential API errors (e.g., permissions, table not found)
        logger.error(f"An error occurred while querying BigQuery for dashboard stats: {e}")
        # Return a default/error state that matches the expected keys
        return {
            "totalProducts": 0,
            "totalRetailers": 0,
            "totalUsers": 0,
            "totalCategories": 0,
            "error": str(e)
        }

def invalidate_dashboard_stats_cache():
    """Invalidate dashboard stats cache when data changes"""
    return cache_service.delete(DASHBOARD_STATS_CACHE_KEY)


def get_pipeline_status_from_db():
    """
    Placeholder for fetching pipeline status.
    """
    pass

# Get Pending Anomalies 
def get_pending_anomalies(bq_client: bigquery.Client, page: int = 1, per_page: int = 20):
    """
    Fetches a paginated list of anomalies that are pending review.
    Uses caching for better performance.
    """
    cache_key = f"{PENDING_ANOMALIES_CACHE_KEY_PREFIX}{page}:{per_page}"
    
    # Try to get from cache first
    cached_anomalies = cache_service.get(cache_key)
    if cached_anomalies is not None:
        logger.info(f"Using cached anomalies for page {page}")
        return cached_anomalies
        
    logger.info(f"Cache miss for anomalies page {page}, querying database")
    
    offset = (page - 1) * per_page
    # This query uses a CTE and a LAG window function
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
            result = []
            # Cache empty result
            cache_service.set(cache_key, result, ANOMALIES_CACHE_TTL)
            return result
        
        # --- Data Sanitization and Transformation ---
        if 'anomaly_id' in df.columns:
            df['anomaly_id'] = df['anomaly_id'].astype(str)

        float_columns = ['anomalousPrice', 'oldPrice']
        for col in float_columns:
            if col in df.columns:
                df[col] = df[col].replace([np.inf, -np.inf], np.nan)

        result = df.to_dict('records')
        
        # Cache the result with optimized TTL
        cache_service.set(cache_key, result, ANOMALIES_CACHE_TTL)
        logger.info(f"Cached {len(result)} anomalies for page {page}")
        
        return result

    except (GoogleAPICallError, Exception) as e:
        logger.error(f"An error occurred while fetching anomalies: {e}")
        return [{"error": str(e)}]
    
      
def invalidate_anomalies_cache():
    """
    Invalidates all anomalies cache when data changes.
    Uses pattern deletion to clear all pages.
    """
    return cache_service.delete_pattern(f"{PENDING_ANOMALIES_CACHE_KEY_PREFIX}*")
    
      
    
# Resolve an Anomaly
def resolve_anomaly(bq_client: bigquery.Client, anomaly_id: int, resolution: str, user_id: str):
    """
    Updates the status and reviewed_by_user_id of a specific anomaly in BigQuery.
    Also invalidates related caches.
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
        
        # Invalidate anomalies cache after resolution
        invalidate_anomalies_cache()
        
        # Also invalidate dashboard stats as they might change
        invalidate_dashboard_stats_cache()
        
        # Invalidate price history for this anomaly if it exists
        cache_service.delete(f"{PRICE_HISTORY_CACHE_KEY_PREFIX}{anomaly_id}")
        
        # Invalidate admin activity cache
        cache_service.delete(RECENT_ADMIN_ACTIVITY_CACHE_KEY)
        
        return {"status": "success", "message": f"Anomaly {anomaly_id} resolved as {resolution}"}
    except GoogleAPICallError as e:
        logger.error(f"An error occurred while resolving anomaly {anomaly_id}: {e}")
        return {"error": str(e)}


# Category distribution
def get_category_distribution(bq_client: bigquery.Client, start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Fetches the distribution of products across different categories for a pie chart.
    Uses caching for better performance.
    """
    # Simplify cache key to increase hit rate - cache by date range in days instead of exact dates
    days_range = (end_date - start_date).days
    cache_key = f"{CATEGORY_DISTRIBUTION_CACHE_KEY_PREFIX}days:{days_range}"
    
    # Try to get from cache first
    cached_distribution = cache_service.get(cache_key)
    if cached_distribution is not None:
        logger.info(f"Using cached category distribution for {days_range} days")
        return cached_distribution
        
    logger.info(f"Cache miss for category distribution ({days_range} days), querying database")
    
    try:
        if bq_client is None: 
            raise Exception("BigQuery client not provided.")

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
            result = []
            cache_service.set(cache_key, result, CATEGORY_DISTRIBUTION_CACHE_TTL)
            return result
        
        # The frontend pie chart expects a 'name' and a 'value' for each slice.
        result = df.to_dict('records')
        
        # Cache the result
        cache_service.set(cache_key, result, CATEGORY_DISTRIBUTION_CACHE_TTL)
        
        return result

    except (GoogleAPICallError, Exception) as e:
        logger.error(f"An error occurred while fetching category distribution: {e}")
        return [{"error": str(e)}]


# Top Tracked Products Chart
def get_top_tracked_products(bq_client: bigquery.Client, start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Fetches the top 10 most tracked products by users within a date range.
    Uses caching for better performance.
    """
    cache_key = f"{TOP_TRACKED_PRODUCTS_CACHE_KEY_PREFIX}{start_date}:{end_date}"
    
    # Try to get from cache first
    cached_products = cache_service.get(cache_key)
    if cached_products is not None:
        return cached_products
    
    try:
        # Step 1: Query Supabase to get the top 10 product IDs and their favorite counts
        supabase = get_supabase_client()
        
        rpc_params = {'start_date_param': str(start_date), 'end_date_param': str(end_date)}
        top_products_response = supabase.rpc('get_top_tracked_products', rpc_params).execute()
        
        top_products_data = top_products_response.data
        if not top_products_data:
            result = []
            cache_service.set(cache_key, result, TOP_TRACKED_PRODUCTS_CACHE_TTL)
            return result

        # Extract the shop_product_ids to use in the BigQuery query
        shop_product_ids = [item['shop_product_id_result'] for item in top_products_data]
        
        # Create a mapping of shop_product_id to user_count for later joining
        user_counts = {item['shop_product_id_result']: item['user_count_result'] for item in top_products_data}

        # Step 2: Query BigQuery to get the product names for those shop_product_ids
        if not bq_client: 
            raise Exception("BigQuery client not provided.")

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
            result = []
            cache_service.set(cache_key, result, TOP_TRACKED_PRODUCTS_CACHE_TTL)
            return result

        # Step 3: Combine the results in Python
        # Add the 'userCount' to our DataFrame of product names
        product_names_df['userCount'] = product_names_df['shop_product_id'].map(user_counts)
        
        # Drop the shop_product_id as it's not needed by the frontend
        final_df = product_names_df.drop(columns=['shop_product_id'])
        
        # Sort by userCount descending to ensure the chart is ordered correctly
        final_df = final_df.sort_values('userCount', ascending=False)
        
        # Sanitize data to prevent JSON errors
        final_df.replace([np.inf, -np.inf], np.nan, inplace=True)
        result = final_df.where(pd.notna(final_df), None).to_dict('records')
        
        # Cache the result
        cache_service.set(cache_key, result, TOP_TRACKED_PRODUCTS_CACHE_TTL)
        
        return result

    except (GoogleAPICallError, Exception) as e:
        logger.error(f"An error occurred while fetching top tracked products: {e}")
        return [{"error": str(e)}]

# Function for getting the recent admin activities
def get_recent_admin_activity() -> List[Dict[str, Any]]:
    """
    Fetches the 10 most recent admin activities from the audit log table in Supabase.
    Uses caching for better performance.
    """
    # Try to get from cache first
    cached_activities = cache_service.get(RECENT_ADMIN_ACTIVITY_CACHE_KEY)
    if cached_activities is not None:
        return cached_activities
        
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
        
        # Cache the result
        cache_service.set(RECENT_ADMIN_ACTIVITY_CACHE_KEY, activities, RECENT_ADMIN_ACTIVITY_CACHE_TTL)
        
        return activities
    except Exception as e:
        logger.error(f"An error occurred while fetching admin activity from Supabase: {e}")
        return [{"error": str(e)}]


# Function for getting the price history of an anomalous product
def get_price_history_for_anomaly(bq_client: bigquery.Client, anomaly_id: int, days: int = 90) -> List[Dict[str, Any]]:
    """
    Fetches the price history for a product associated with a specific anomaly.
    Uses caching for better performance.
    """
    cache_key = f"{PRICE_HISTORY_CACHE_KEY_PREFIX}{anomaly_id}:{days}"
    
    # Try to get from cache first
    cached_history = cache_service.get(cache_key)
    if cached_history is not None:
        return cached_history
        
    try:
        # First, we need to find the variant_id associated with this anomaly.
        anomaly_query = f"""
            SELECT 
                fpa.price_fact_id,
                fpp.variant_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` AS fpa
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` AS fpp
                ON fpa.price_fact_id = fpp.price_fact_id
            WHERE fpa.anomaly_id = @anomaly_id
        """
        
        anomaly_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("anomaly_id", "INT64", anomaly_id)
            ]
        )
        
        anomaly_df = bq_client.query(anomaly_query, job_config=anomaly_job_config).to_dataframe()
        
        if anomaly_df.empty:
            logger.warning(f"No anomaly found with ID {anomaly_id}")
            result = []
            cache_service.set(cache_key, result, PRICE_HISTORY_CACHE_TTL)
            return result
            
        variant_id = int(anomaly_df['variant_id'].iloc[0])
        
        # Now fetch the price history for this variant over the last 'days' days.
        today = date.today()
        start_date = today - timedelta(days=days)
        
        history_query = f"""
            SELECT
                dd.full_date AS date,
                fpp.current_price AS price
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` AS fpp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` AS dd
                ON fpp.date_id = dd.date_id
            WHERE fpp.variant_id = @variant_id
                AND dd.full_date BETWEEN @start_date AND @end_date
            ORDER BY dd.full_date ASC
        """
        
        history_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("variant_id", "INT64", variant_id),
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", today)
            ]
        )
        
        history_df = bq_client.query(history_query, job_config=history_job_config).to_dataframe()
        
        if history_df.empty:
            logger.warning(f"No price history found for variant {variant_id} in the last {days} days")
            result = []
            cache_service.set(cache_key, result, PRICE_HISTORY_CACHE_TTL)
            return result
        
        # Convert to dictionary records for JSON serialization
        # Make sure to handle any inf or NaN values
        history_df.replace([np.inf, -np.inf], np.nan, inplace=True)
        result = history_df.where(pd.notna(history_df), None).to_dict('records')
        
        # Cache the result
        cache_service.set(cache_key, result, PRICE_HISTORY_CACHE_TTL)
        
        return result
        
    except (GoogleAPICallError, Exception) as e:
        logger.error(f"An error occurred while fetching price history for anomaly {anomaly_id}: {e}")
        return [{"error": str(e)}]


def invalidate_all_admin_caches():
    """
    Invalidates all admin caches when there are major data changes.
    """
    cache_keys = [
        DASHBOARD_STATS_CACHE_KEY,
        f"{PENDING_ANOMALIES_CACHE_KEY_PREFIX}*",
        f"{CATEGORY_DISTRIBUTION_CACHE_KEY_PREFIX}*",
        f"{TOP_TRACKED_PRODUCTS_CACHE_KEY_PREFIX}*",
        RECENT_ADMIN_ACTIVITY_CACHE_KEY,
        f"{PRICE_HISTORY_CACHE_KEY_PREFIX}*"
    ]
    
    success = True
    for key_pattern in cache_keys:
        if "*" in key_pattern:
            if not cache_service.delete_pattern(key_pattern):
                success = False
        else:
            if not cache_service.delete(key_pattern):
                success = False
                
    return success


# --- NEW FUNCTION TO PROMOTE A USER ---
def promote_user_to_admin(user_id: str) -> Dict[str, Any]:
    """
    Assigns the 'Admin' role to a specific user.

    This function is designed to be called by a protected admin endpoint.
    It finds the role_id for 'Admin', checks for existing mappings,
    and inserts a new record if one doesn't exist.

    Args:
        user_id: The UUID of the user to be promoted.

    Returns:
        A dictionary with the status and a message.
    """
    try:
        logger.info(f"Attempting to promote user {user_id} to admin role")
        
        # Get Supabase client
        try:
            supabase = get_supabase_client()
            logger.info("Successfully got Supabase client")
        except Exception as client_error:
            logger.error(f"Failed to get Supabase client: {client_error}")
            return {"error": f"Database connection error: {str(client_error)}"}
        
        # Step 1: Find the role_id for the 'Admin' role.
        try:
            role_query = supabase.from_("roles").select("role_id").eq("role_name", "Admin").single()
            role_response = role_query.execute()
            
            if not role_response.data:
                logger.error("Critical: 'Admin' role not found in the roles table.")
                return {"error": "Configuration error: Admin role not found."}
                
            admin_role_id = role_response.data['role_id']
            logger.info(f"Found Admin role with ID: {admin_role_id}")
        except Exception as role_error:
            logger.error(f"Error querying for Admin role: {role_error}")
            return {"error": f"Failed to query admin role: {str(role_error)}"}

        # Step 2: Check if the user already has this role to prevent duplicates.
        try:
            mapping_query = supabase.from_("userrolemapping").select("user_id").eq("user_id", user_id).eq("role_id", admin_role_id)
            mapping_response = mapping_query.execute()

            if mapping_response.data:
                logger.warning(f"Attempted to re-promote user {user_id} who is already an admin.")
                return {"status": "success", "message": "User is already an administrator."}
            
            logger.info(f"User {user_id} is not yet an admin, proceeding with role assignment")
        except Exception as mapping_error:
            logger.error(f"Error checking existing role mappings: {mapping_error}")
            return {"error": f"Failed to check existing roles: {str(mapping_error)}"}

        # Step 3: Insert the new role mapping into the table.
        try:
            insert_query = supabase.from_("userrolemapping").insert({
                "user_id": user_id,
                "role_id": admin_role_id
            })
            insert_response = insert_query.execute()

            # The response from an insert contains the inserted data in a list.
            # If the list is empty, the insert likely failed.
            if not insert_response.data:
                 logger.error(f"Failed to insert admin role mapping for user {user_id}.")
                 return {"error": "Database operation failed: Could not assign admin role."}

            logger.info(f"Successfully promoted user {user_id} to an administrator.")
            return {"status": "success", "message": f"User {user_id} promoted to administrator."}
        except Exception as insert_error:
            logger.error(f"Error inserting new role mapping: {insert_error}")
            return {"error": f"Failed to assign admin role: {str(insert_error)}"}

    except Exception as e:
        logger.error(f"An unexpected error occurred while promoting user {user_id}: {e}")
        return {"error": f"An unexpected error occurred: {str(e)}"}

