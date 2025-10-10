# This service will contain all the business logic for the admin dashboard,
# such as querying BigQuery for anomalies or PostgreSQL for user data.
import logging
import pandas as pd
import numpy as np
from google.cloud import bigquery
from app.config import settings
from google.api_core.exceptions import GoogleAPICallError
from app.services.user_service import get_total_users_count

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

# 1: Get Pending Anomalies 
def get_pending_anomalies(bq_client: bigquery.Client, page: int = 1, per_page: int = 20):
    """
    Fetches a paginated list of anomalies that are pending review.
    It joins across multiple tables to enrich the data for the frontend.
    """
    offset = (page - 1) * per_page
    query = f"""
        SELECT
            fa.anomaly_id,
            dp.product_title_native AS productName,
            fp.current_price AS anomalousPrice,
            fp.original_price AS oldPrice,
            dp.product_url AS productUrl,
            ds.website_url AS vendorUrl
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` AS fa
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` AS fp ON fa.price_fact_id = fp.price_fact_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` AS dv ON fp.variant_id = dv.variant_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` AS dp ON dv.shop_product_id = dp.shop_product_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` AS ds ON dp.shop_id = ds.shop_id
        WHERE fa.status = 'PENDING_REVIEW'
        ORDER BY fa.created_at DESC
        LIMIT {per_page} OFFSET {offset}
    """
    try:
        df = bq_client.query(query).to_dataframe()
        
        # --- MORE ROBUST DATA SANITIZATION ---
        # 1. Replace any special float values (Infinity, -Infinity) with pandas' standard Not a Number (NaN).
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        
        # 2. Force the DataFrame to use standard Python objects instead of NumPy types.
        #    This is the key step. It allows us to replace NaN with Python's `None`.
        # 3. Use .where() to replace all NaN values with `None`, which is JSON compliant (becomes null).
        cleaned_data = df.astype(object).where(pd.notna(df), None).to_dict('records')
        
        return cleaned_data
    
    except GoogleAPICallError as e:
        print(f"An error occurred while fetching anomalies: {e}")
        return {"error": str(e)}

# 2: Resolve an Anomaly
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

