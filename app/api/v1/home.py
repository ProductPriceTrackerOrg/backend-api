from fastapi import APIRouter, Depends, HTTPException, Query, Response
from typing import Dict, List, Optional, Any
from google.cloud import bigquery
from app.config import settings
from app.api.deps import get_current_user, get_current_admin_user, get_bigquery_client
from app.services.cache_service import cache_service
from app.schemas.home import (
    HomeStats, 
    CategoriesResponse, 
    TrendingResponse, 
    NewLaunchResponse,
    LatestProductsResponse, 
    PriceChangeResponse, 
    RetailersResponse,
    SearchSuggestions,
    RecommendationsResponse
)

router = APIRouter()

@router.get("/stats", response_model=HomeStats)
async def get_home_stats(
    response: Response,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get homepage statistics including total products, categories, users, suppliers, 
    and price updates.
    """
    cache_key = "home:stats"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        # Query the Supabase database for user count via an HTTP call
        # This would typically be done using a repository pattern or a database access service
        # For now, we'll skip implementing this and use a placeholder
        
        # Improved query to get accurate warehouse statistics
        query = f"""
        WITH
          ProductCount AS (
            SELECT COUNT(DISTINCT shop_product_id) AS count
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct`
          ),
          CategoryCount AS (
            SELECT COUNT(DISTINCT category_id) AS count
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory`
            WHERE parent_category_id IS NULL -- Counts only top-level categories
          ),
          ShopCount AS (
            SELECT COUNT(DISTINCT shop_id) AS count
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop`
          ),
          TodayPriceUpdates AS (
            SELECT COUNT(*) AS count
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` dd ON fpp.date_id = dd.date_id
            WHERE dd.full_date = CURRENT_DATE()
          ),
          ActiveDeals AS (
            SELECT COUNT(*) AS count
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
            WHERE is_available = TRUE AND original_price IS NOT NULL AND current_price < original_price
          )
        SELECT
          -- Use CASE statements for robust and readable number formatting
          CASE
            WHEN pc.count >= 1000000 THEN FORMAT('%.1fM+', ROUND(pc.count / 1000000, 1))
            WHEN pc.count >= 1000 THEN FORMAT('%.1fK+', ROUND(pc.count / 1000, 1))
            ELSE CAST(pc.count AS STRING)
          END AS total_products,
        
          CAST(cc.count AS STRING) || '+' AS product_categories,
          
          -- Placeholder for total_users (to be implemented with Supabase integration)
          '100K+' AS total_users,
          
          CAST(sc.count AS STRING) || '+' AS total_suppliers,
        
          CASE
            WHEN tpu.count >= 1000000 THEN FORMAT('%.1fM+', ROUND(tpu.count / 1000000, 1))
            WHEN tpu.count >= 1000 THEN FORMAT('%.1fK+', ROUND(tpu.count / 1000, 1))
            ELSE CAST(tpu.count AS STRING)
          END || '+' AS price_updates_today,
        
          CASE
            WHEN ad.count >= 1000000 THEN FORMAT('%.1fM+', ROUND(ad.count / 1000000, 1))
            WHEN ad.count >= 1000 THEN FORMAT('%.1fK+', ROUND(ad.count / 1000, 1))
            ELSE CAST(ad.count AS STRING)
          END || '+' AS active_deals
        FROM
          ProductCount pc,
          CategoryCount cc,
          ShopCount sc,
          TodayPriceUpdates tpu,
          ActiveDeals ad
        """
        
        query_job = bq_client.query(query)
        results = list(query_job.result())
        
        if not results:
            data = {
                "total_products": "0+",
                "product_categories": "0+",
                "total_users": "0+", 
                "total_suppliers": "0+",
                "price_updates_today": "0+",
                "active_deals": "0+"
            }
        else:
            data = dict(results[0])
            
            # TODO: For a complete implementation, we should query Supabase for the actual user count
            # Example implementation would be:
            # supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            # response = supabase_client.table('profiles').select('count', count='exact').execute()
            # user_count = response.count or 0
            # data["total_users"] = f"{user_count}+"
            
        # Cache the data for 1 hour (3600 seconds)
        cache_service.set(cache_key, data, 3600)
            
        return data
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while querying BigQuery: {e}"
        )


@router.get("/categories", response_model=CategoriesResponse)
async def get_home_categories(
    response: Response,
    limit: int = Query(10, ge=1, le=50),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get product categories with product counts and trending scores.
    """
    try:
        query = f"""
        SELECT
            c.category_id,
            c.category_name as name,
            COUNT(DISTINCT sp.shop_product_id) as product_count,
            COALESCE(AVG(pa.anomaly_score), 0) as trending_score,
            -- Static values for demo purposes, in production these would come from your database
            CASE
                WHEN c.category_name LIKE '%phone%' THEN 'smartphone'
                WHEN c.category_name LIKE '%laptop%' THEN 'laptop'
                WHEN c.category_name LIKE '%watch%' THEN 'watch'
                WHEN c.category_name LIKE '%tablet%' THEN 'tablet'
                WHEN c.category_name LIKE '%camera%' THEN 'camera'
                WHEN c.category_name LIKE '%headphone%' THEN 'headphone'
                ELSE 'gadget'
            END as icon,
            CONCAT('/category/', LOWER(REPLACE(c.category_name, ' ', '-'))) as href,
            CASE
                WHEN c.category_id % 5 = 0 THEN 'blue'
                WHEN c.category_id % 5 = 1 THEN 'green'
                WHEN c.category_id % 5 = 2 THEN 'red'
                WHEN c.category_id % 5 = 3 THEN 'purple'
                ELSE 'orange'
            END as color
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON c.category_id = sp.predicted_master_category_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` pa ON fpp.price_fact_id = pa.price_fact_id
        WHERE c.parent_category_id IS NULL
        GROUP BY c.category_id, c.category_name
        ORDER BY trending_score DESC
        LIMIT {limit}
        """
        
        query_job = bq_client.query(query)
        results = [dict(row) for row in query_job.result()]
        
        # Format product count to human-readable format
        for category in results:
            count = category['product_count']
            if count >= 1000000:
                category['product_count'] = f"{count // 1000000}M+"
            elif count >= 1000:
                category['product_count'] = f"{count // 1000}K+"
            else:
                category['product_count'] = f"{count}+"
                
        return {"categories": results}
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while querying BigQuery: {e}"
        )


@router.get("/trending", response_model=TrendingResponse)
async def get_trending_products(
    response: Response,
    limit: int = Query(8, ge=1, le=50),
    type: str = Query("trends", regex="^(trends|launches)$"),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get trending products or new product launches.
    """
    try:
        if type == "trends":
            query = f"""
            SELECT
                sp.shop_product_id as id,
                sp.product_title_native as name,
                sp.brand_native as brand,
                c.category_name as category,
                v.variant_id,
                v.variant_title,
                s.shop_name as retailer,
                s.shop_id as retailer_id,
                fpp.current_price as price,
                fpp.original_price,
                fpp.is_available as in_stock,
                pi.image_url as image,
                CASE
                    WHEN fpp.original_price > 0
                    THEN ROUND(((fpp.original_price - fpp.current_price) / fpp.original_price) * 100, 0)
                    ELSE 0
                END as discount,
                AVG(pa.anomaly_score) as trend_score,
                CONCAT('+', CAST(ROUND(RAND() * 200 + 50, 0) AS STRING), '%') as search_volume,
                ROUND(fpp.original_price - fpp.current_price, 2) as price_change,
                TRUE as is_trending
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` pa ON fpp.price_fact_id = pa.price_fact_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
            WHERE fpp.is_available = TRUE
            GROUP BY 
                sp.shop_product_id, sp.product_title_native, sp.brand_native, c.category_name, 
                v.variant_id, v.variant_title, s.shop_name, s.shop_id, 
                fpp.current_price, fpp.original_price, fpp.is_available, pi.image_url
            ORDER BY trend_score DESC
            LIMIT {limit}
            """
            
            query_job = bq_client.query(query)
            results = [dict(row) for row in query_job.result()]
            
            return {
                "products": results,
                "stats": {
                    "trending_searches": "2.5M+",
                    "accuracy_rate": "95%",
                    "update_frequency": "Real-time"
                }
            }
        else:  # type == "launches"
            query = f"""
            WITH RecentProducts AS (
                SELECT
                    sp.shop_product_id,
                    sp.product_title_native,
                    sp.brand_native,
                    c.category_name,
                    MIN(d.full_date) as first_seen_date
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
                JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON fpp.date_id = d.date_id
                GROUP BY sp.shop_product_id, sp.product_title_native, sp.brand_native, c.category_name
                HAVING DATE_DIFF(CURRENT_DATE(), MIN(d.full_date), DAY) <= 30
            )
            
            SELECT
                rp.shop_product_id as id,
                rp.product_title_native as name,
                rp.brand_native as brand,
                rp.category_name as category,
                fpp.current_price as price,
                s.shop_name as retailer,
                s.shop_id as retailer_id,
                TRUE as in_stock,
                pi.image_url as image,
                rp.first_seen_date as launch_date,
                CAST(ROUND(RAND() * 20000 + 5000, 0) AS INT64) as pre_orders,
                4.0 + RAND() * 1.0 as rating,
                TRUE as is_new
            FROM RecentProducts rp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON rp.shop_product_id = sp.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
            ORDER BY rp.first_seen_date DESC
            LIMIT {limit}
            """
            
            query_job = bq_client.query(query)
            results = [dict(row) for row in query_job.result()]
            
            return {
                "products": results,
                "stats": {
                    "new_launches": "450+",
                    "update_frequency": "24h",
                    "tracking_type": "Pre-order"
                }
            }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while querying BigQuery: {e}"
        )


@router.get("/latest", response_model=LatestProductsResponse)
async def get_latest_products(
    response: Response,
    limit: int = Query(12, ge=1, le=50),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get the latest products added to the database.
    """
    try:
        query = f"""
        WITH LatestProducts AS (
            SELECT
                sp.shop_product_id,
                sp.product_title_native,
                sp.brand_native,
                c.category_name,
                CURRENT_TIMESTAMP() as added_date,
                ROW_NUMBER() OVER (PARTITION BY sp.shop_id ORDER BY sp.shop_product_id DESC) as row_num
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
        )
        
        SELECT
            lp.shop_product_id as id,
            lp.product_title_native as name,
            lp.brand_native as brand,
            lp.category_name as category,
            fpp.current_price as price,
            fpp.original_price,
            s.shop_name as retailer,
            s.shop_id as retailer_id,
            fpp.is_available as in_stock,
            pi.image_url as image,
            CASE
                WHEN fpp.original_price > 0
                THEN ROUND(((fpp.original_price - fpp.current_price) / fpp.original_price) * 100, 0)
                ELSE 0
            END as discount,
            4.0 + RAND() * 1.0 as rating,
            CAST(ROUND(RAND() * 2000 + 100, 0) AS INT64) as reviews_count,
            lp.added_date
        FROM LatestProducts lp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON lp.shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
        WHERE lp.row_num <= {limit}
        ORDER BY lp.added_date DESC
        LIMIT {limit}
        """
        
        query_job = bq_client.query(query)
        results = [dict(row) for row in query_job.result()]
        
        return {"products": results}
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while querying BigQuery: {e}"
        )


@router.get("/price-changes", response_model=PriceChangeResponse)
async def get_price_changes(
    response: Response,
    limit: int = Query(8, ge=1, le=50),
    type: str = Query("drops", regex="^(drops|increases)$"),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get products with price drops or price increases.
    """
    try:
        # Get the last two date_ids to compare prices
        date_query = f"""
        SELECT date_id
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate`
        ORDER BY full_date DESC
        LIMIT 2
        """
        date_job = bq_client.query(date_query)
        date_results = list(date_job.result())
        
        if len(date_results) < 2:
            raise HTTPException(
                status_code=500,
                detail="Not enough date data available to calculate price changes"
            )
        
        current_date_id = date_results[0]['date_id']
        previous_date_id = date_results[1]['date_id']
        
        comparison_operator = "<" if type == "drops" else ">"
        
        query = f"""
        WITH PriceChanges AS (
            SELECT
                sp.shop_product_id as id,
                sp.product_title_native as name,
                sp.brand_native as brand,
                c.category_name as category,
                current_prices.current_price,
                previous_prices.current_price as previous_price,
                (current_prices.current_price - previous_prices.current_price) as price_change,
                ROUND(((current_prices.current_price - previous_prices.current_price) / 
                      NULLIF(previous_prices.current_price, 0)) * 100, 2) as percentage_change,
                s.shop_name as retailer,
                s.shop_id as retailer_id,
                pi.image_url as image,
                d.full_date as change_date,
                current_prices.is_available as in_stock
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
            JOIN (
                SELECT variant_id, current_price, date_id, is_available
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
                WHERE date_id = {current_date_id}
            ) current_prices ON v.variant_id = current_prices.variant_id
            JOIN (
                SELECT variant_id, current_price
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
                WHERE date_id = {previous_date_id}
            ) previous_prices ON v.variant_id = previous_prices.variant_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON current_prices.date_id = d.date_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
            WHERE current_prices.current_price != previous_prices.current_price
        )
        SELECT * FROM PriceChanges
        WHERE price_change {comparison_operator} 0
        ORDER BY ABS(percentage_change) DESC
        LIMIT {limit}
        """
        
        query_job = bq_client.query(query)
        results = [dict(row) for row in query_job.result()]
        
        return {"price_changes": results}
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while querying BigQuery: {e}"
        )


@router.get("/retailers", response_model=RetailersResponse)
async def get_featured_retailers(
    response: Response,
    limit: int = Query(8, ge=1, le=50),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get featured retailers with product counts and ratings.
    """
    try:
        query = f"""
        SELECT
            s.shop_id,
            s.shop_name as name,
            s.website_url,
            s.contact_phone,
            s.contact_whatsapp,
            COUNT(DISTINCT v.variant_id) as product_count,
            4.0 + RAND() * 1.0 as avg_rating,
            CASE
                WHEN s.shop_name LIKE '%tech%' OR s.shop_name LIKE '%electron%' THEN 'Electronics'
                WHEN s.shop_name LIKE '%fashion%' OR s.shop_name LIKE '%cloth%' THEN 'Fashion'
                WHEN s.shop_name LIKE '%home%' OR s.shop_name LIKE '%furniture%' THEN 'Home'
                WHEN s.shop_name LIKE '%sport%' THEN 'Sports'
                ELSE 'General'
            END as specialty
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON s.shop_id = sp.shop_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        GROUP BY s.shop_id, s.shop_name, s.website_url, s.contact_phone, s.contact_whatsapp
        HAVING COUNT(DISTINCT v.variant_id) > 0
        ORDER BY product_count DESC, avg_rating DESC
        LIMIT {limit}
        """
        
        query_job = bq_client.query(query)
        results = [dict(row) for row in query_job.result()]
        
        # Add placeholder logo URLs since they're not in the schema
        for retailer in results:
            retailer['logo'] = f"https://placekitten.com/200/200?retailer={retailer['shop_id']}"
            
        return {"retailers": results}
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while querying BigQuery: {e}"
        )


@router.get("/search-suggestions", response_model=SearchSuggestions)
async def get_search_suggestions(
    response: Response
) -> Dict:
    """
    Get popular and trending search suggestions.
    """
    # Since we don't have actual search data yet, this is mocked
    popular_searches = [
        "iPhone 15",
        "Samsung Galaxy S24",
        "MacBook Pro",
        "AirPods Pro",
        "PlayStation 5",
        "Xbox Series X",
        "iPad Pro",
        "Google Pixel"
    ]
    
    trending_searches = [
        "Nothing Phone 2a",
        "Google Pixel 8",
        "Steam Deck OLED",
        "Samsung Galaxy Z Fold 5",
        "Apple Vision Pro"
    ]
    
    return {
        "popular_searches": popular_searches,
        "trending_searches": trending_searches
    }


@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_personalized_recommendations(
    response: Response,
    limit: int = Query(6, ge=1, le=50),
    user = Depends(get_current_user),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get personalized product recommendations for authenticated users.
    """
    try:
        # In a real application, you would use the user's ID to fetch personalized recommendations
        # Since we don't have that functionality yet, we'll simulate it
        
        query = f"""
        SELECT
            sp.shop_product_id as id,
            sp.product_title_native as name,
            sp.brand_native as brand,
            c.category_name as category,
            fpp.current_price as price,
            fpp.original_price,
            s.shop_name as retailer,
            pi.image_url as image,
            0.7 + RAND() * 0.3 as recommendation_score,
            CASE
                WHEN RAND() < 0.33 THEN 'Based on your browsing history'
                WHEN RAND() < 0.66 THEN 'Based on your previous purchases'
                ELSE 'Popular in your area'
            END as recommendation_reason
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
        WHERE fpp.is_available = TRUE
        ORDER BY RAND()
        LIMIT {limit}
        """
        
        query_job = bq_client.query(query)
        results = [dict(row) for row in query_job.result()]
        
        return {"recommended_products": results}
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while querying BigQuery: {e}"
        )
