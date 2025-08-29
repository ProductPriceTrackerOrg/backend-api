from fastapi import APIRouter, Depends, HTTPException, Query, Response, Path
from typing import Dict, List, Optional, Any
from google.cloud import bigquery
import supabase
from app.config import settings
from app.api.deps import get_current_user, get_bigquery_client, get_current_user_optional
from app.services.cache_service import cache_service
from app.schemas.product import (
    ProductDetailsResponse, 
    PriceHistoryResponse, 
    ForecastResponse,
    AnomalyResponse,
    SimilarProductsResponse,
    RecommendationsResponse,
    ComparisonResponse,
    FavoriteResponse,
    ViewLogResponse
)

router = APIRouter()

# Supabase client initialization function
def get_supabase_client():
    """Returns a Supabase client using the URL and key from settings."""
    try:
        client = supabase.create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        return client
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create Supabase client: {e}"
        )

@router.get("/{product_id}", response_model=ProductDetailsResponse)
async def get_product_details(
    product_id: int = Path(..., description="The ID of the specific shop product to retrieve"),
    # This dependency attempts to get a user if a token is provided, but doesn't fail if not.
    current_user: Optional[Dict] = Depends(get_current_user_optional),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get detailed information for a specific product listing from a single retailer,
    including all its variants and their latest prices.
    """
    # Cache key based on product ID
    cache_key = f"product:{product_id}"
    
    # Try to get from cache first if not authenticated (personalized results can't be cached)
    if not current_user:
        cached_data = cache_service.get(cache_key)
        if cached_data:
            return cached_data
    
    try:
        # This simpler query targets the exact product listing and gets the latest prices
        query = f"""
        WITH LatestPrices AS (
            -- This CTE ensures we only get the most recent price for each variant.
            SELECT variant_id, current_price, original_price, is_available, date_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
            QUALIFY ROW_NUMBER() OVER(PARTITION BY variant_id ORDER BY date_id DESC) = 1
        )
        SELECT
          sp.shop_product_id as id,
          sp.product_title_native as name,
          sp.brand_native as brand,
          '' as description,  -- Placeholder for description since description_native may not exist
          c.category_name as category,
          c.category_id,
          v.variant_id,
          v.variant_title as title,  -- Renamed to match our schema
          s.shop_id,
          s.shop_name as retailer,
          s.contact_phone,
          s.contact_whatsapp,
          lp.current_price as price,
          lp.original_price,
          lp.is_available,
          pi.image_url as image,
          CASE
            WHEN lp.original_price > 0 AND lp.original_price > lp.current_price
            THEN ROUND(((lp.original_price - lp.current_price) / lp.original_price) * 100, 0)
            ELSE 0
          END as discount
        FROM
          `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
        JOIN LatestPrices lp ON v.variant_id = lp.variant_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
        -- Filtering directly by the specific shop_product_id
        WHERE sp.shop_product_id = {product_id}
        """

        # Get all product images in a separate query
        images_query = f"""
        SELECT image_url
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage`
        WHERE shop_product_id = {product_id}
        ORDER BY sort_order ASC
        """

        # Execute the main product query
        query_job = bq_client.query(query)
        results = [dict(row) for row in query_job.result()]

        # Execute the images query
        images_job = bq_client.query(images_query)
        images = [row['image_url'] for row in images_job.result()]

        if not results:
            raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found")

        # Reshape the data into a nested structure
        first_row = results[0]
        product_data = {
            "id": first_row["id"],
            "name": first_row["name"],
            "brand": first_row["brand"],
            "description": first_row["description"],
            "category": first_row["category"],
            "category_id": first_row["category_id"],
            "image": first_row["image"],  # Primary image
            "images": images,  # All images
            "retailer": first_row["retailer"],
            "retailer_phone": first_row["contact_phone"],
            "retailer_whatsapp": first_row["contact_whatsapp"],
            "variants": [],
            "is_favorited": False  # Default to false for all users (anonymous or not)
        }

        # Collect all variant IDs for favorites checking
        all_variant_ids = []
        for row in results:
            variant = {
                "variant_id": row["variant_id"],
                "title": row["title"],  # Now using the consistent field name
                "price": row["price"],
                "original_price": row["original_price"],
                "is_available": row["is_available"],
                "discount": row["discount"]
            }
            product_data["variants"].append(variant)
            all_variant_ids.append(row["variant_id"])

        # Check favorites ONLY if the user is logged in
        if current_user:
            try:
                supabase_client = get_supabase_client()
                user_id = current_user.get("sub")
                
                # Check if ANY of this product's variants are in the user's favorites list
                response = supabase_client.table("UserFavorites") \
                    .select("variant_id", count='exact') \
                    .eq("user_id", user_id) \
                    .in_("variant_id", all_variant_ids) \
                    .execute()
                
                # Set favorited to True if any variant was found in favorites
                if response.count is not None and response.count > 0:
                    product_data["is_favorited"] = True
            except Exception as e:
                print(f"Error checking favorites status: {e}")
                # Continue without the favorites info if there's an error

        result = {"product": product_data}
        
        # Cache the result for non-authenticated requests
        if not current_user:
            cache_service.set(cache_key, result, 3600)  # Cache for 1 hour
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred: {e}"
        )


@router.get("/{product_id}/price-history", response_model=PriceHistoryResponse)
async def get_price_history(
    product_id: int = Path(..., description="The ID of the product"),
    retailer_id: Optional[int] = Query(None, description="Filter by specific retailer"),
    days: int = Query(90, ge=1, le=365, description="Number of days of history to retrieve"),
    response: Response = None,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get the price history of a product over time.
    
    Shows how the price has changed over the specified number of days.
    """
    cache_key = f"product:{product_id}:history:days{days}"
    if retailer_id:
        cache_key += f":retailer:{retailer_id}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        query = f"""
        -- Price history with changes
        WITH PriceHistory AS (
            SELECT
                d.full_date as date,
                v.variant_id,
                fpp.current_price as price,
                LAG(fpp.current_price) OVER(PARTITION BY v.variant_id ORDER BY d.full_date) as previous_price,
                MIN(fpp.current_price) OVER(PARTITION BY v.variant_id) as min_price,
                MAX(fpp.current_price) OVER(PARTITION BY v.variant_id) as max_price
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` d ON fpp.date_id = d.date_id
            WHERE sp.shop_product_id = {product_id}
            {f"AND s.shop_id = {retailer_id}" if retailer_id else ""}
            AND d.full_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            ORDER BY d.full_date DESC
        )
        
        SELECT
            CAST(date AS STRING) as date,
            price,
            previous_price,
            price - previous_price as change,
            CASE WHEN previous_price > 0 
                THEN ROUND(((price - previous_price) / previous_price) * 100, 2)
                ELSE 0
            END as change_percentage,
            price = min_price as is_minimum,
            price = max_price as is_maximum
        FROM PriceHistory
        ORDER BY date ASC
        """
        
        query_job = bq_client.query(query)
        results = list(query_job.result())
        
        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"Price history not found for product ID {product_id}"
            )
        
        # Calculate statistics
        prices = [row["price"] for row in results]
        current_price = prices[-1] if prices else 0
        min_price = min(prices) if prices else 0
        max_price = max(prices) if prices else 0
        
        # Prepare the response
        price_history_data = []
        for row in results:
            point = {
                "date": row["date"],
                "price": row["price"],
                "is_minimum": row["is_minimum"],
                "is_maximum": row["is_maximum"]
            }
            
            # Add change data if available
            if row["previous_price"] is not None:
                point["change"] = row["change"]
                point["change_percentage"] = row["change_percentage"]
            
            price_history_data.append(point)
        
        result = {
            "price_history": price_history_data,
            "statistics": {
                "current_price": current_price,
                "min_price": min_price,
                "max_price": max_price,
                "price_drop_percent": round(((max_price - current_price) / max_price * 100), 2) if max_price > 0 else 0,
                "total_days": len(results),
                "price_changes": sum(1 for row in results if row["change"] is not None and row["change"] != 0)
            }
        }
        
        # Cache the result
        cache_service.set(cache_key, result, 1800)  # Cache for 30 minutes
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while fetching price history: {e}"
        )


@router.get("/{product_id}/forecast", response_model=ForecastResponse)
async def get_price_forecast(
    product_id: int = Path(..., description="The ID of the product"),
    days: int = Query(7, ge=1, le=30, description="Number of days to forecast"),
    retailer_id: Optional[int] = Query(None, description="Filter by specific retailer"),
    response: Response = None,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get price forecast for a product.
    
    Predicts how the price might change in the coming days.
    """
    cache_key = f"product:{product_id}:forecast:days{days}"
    if retailer_id:
        cache_key += f":retailer:{retailer_id}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        query = f"""
        -- Get price forecasts
        SELECT
            CAST(fpf.forecast_date AS STRING) as date,
            fpf.predicted_price,
            fpf.confidence_upper as upper_bound,
            fpf.confidence_lower as lower_bound,
            dm.model_name,
            dm.model_version,
            CAST(dm.training_date AS STRING) as last_trained
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceForecast` fpf
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON fpf.variant_id = v.variant_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON v.shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimModel` dm ON fpf.model_id = dm.model_id
        WHERE sp.shop_product_id = {product_id}
        {f"AND s.shop_id = {retailer_id}" if retailer_id else ""}
        AND fpf.forecast_date > CURRENT_DATE()
        AND fpf.forecast_date <= DATE_ADD(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY fpf.forecast_date ASC
        """
        
        query_job = bq_client.query(query)
        results = list(query_job.result())
        
        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"Price forecast not available for product ID {product_id}"
            )
        
        # Extract model info from the first result
        model_info = {
            "model_name": results[0]["model_name"],
            "model_version": results[0]["model_version"],
            "last_trained": results[0]["last_trained"]
        }
        
        # Format forecast points
        forecast_points = []
        for row in results:
            forecast_points.append({
                "date": row["date"],
                "predicted_price": row["predicted_price"],
                "upper_bound": row["upper_bound"],
                "lower_bound": row["lower_bound"],
                # Calculate confidence as the range between upper and lower bounds
                "confidence": round(100 - ((row["upper_bound"] - row["lower_bound"]) / row["predicted_price"] * 100), 0) if row["predicted_price"] > 0 else 0
            })
        
        result = {
            "forecasts": forecast_points,
            "model_info": model_info
        }
        
        # Cache the result
        cache_service.set(cache_key, result, 21600)  # Cache for 6 hours
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while fetching price forecast: {e}"
        )


@router.get("/{product_id}/anomalies", response_model=AnomalyResponse)
async def get_price_anomalies(
    product_id: int = Path(..., description="The ID of the product"),
    days: int = Query(30, ge=1, le=90, description="Number of days to check for anomalies"),
    min_score: float = Query(0.7, ge=0, le=1, description="Minimum anomaly score threshold"),
    response: Response = None,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get price anomalies detected for a product.
    
    Identifies unusual price changes that might indicate special offers or pricing errors.
    """
    cache_key = f"product:{product_id}:anomalies:days{days}:score{min_score}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        query = f"""
        -- Get price anomalies
        WITH AnomaliesWithPrices AS (
            SELECT
                fpa.anomaly_id,
                CAST(dd.full_date AS STRING) as date,
                fpp.current_price as price,
                LAG(fpp.current_price) OVER(PARTITION BY v.variant_id ORDER BY dd.full_date) as previous_price,
                fpa.anomaly_score,
                fpa.anomaly_type,
                dm.model_name
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPriceAnomaly` fpa
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON fpa.price_fact_id = fpp.price_fact_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimDate` dd ON fpp.date_id = dd.date_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON fpp.variant_id = v.variant_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON v.shop_product_id = sp.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimModel` dm ON fpa.model_id = dm.model_id
            WHERE sp.shop_product_id = {product_id}
            AND dd.full_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND fpa.anomaly_score >= {min_score}
        )
        
        SELECT
            anomaly_id,
            date,
            price,
            previous_price,
            anomaly_score,
            anomaly_type,
            model_name,
            CASE WHEN previous_price > 0 
                THEN ROUND(((price - previous_price) / previous_price) * 100, 2)
                ELSE 0
            END as change_percentage
        FROM AnomaliesWithPrices
        WHERE previous_price IS NOT NULL
        ORDER BY anomaly_score DESC, date DESC
        """
        
        query_job = bq_client.query(query)
        results = list(query_job.result())
        
        # Format the anomalies
        anomalies = []
        for row in results:
            anomalies.append({
                "anomaly_id": row["anomaly_id"],
                "date": row["date"],
                "price": row["price"],
                "previous_price": row["previous_price"],
                "change_percentage": row["change_percentage"],
                "anomaly_score": row["anomaly_score"],
                "anomaly_type": row["anomaly_type"],
                "model_name": row["model_name"]
            })
        
        result = {"anomalies": anomalies}
        
        # Cache the result
        cache_service.set(cache_key, result, 3600)  # Cache for 1 hour
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while fetching price anomalies: {e}"
        )


@router.get("/{product_id}/similar", response_model=SimilarProductsResponse)
async def get_similar_products(
    product_id: int = Path(..., description="The ID of the product"),
    limit: int = Query(6, ge=1, le=20, description="Number of similar products to return"),
    response: Response = None,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Get products similar to the specified product using a single, efficient, and secure query.
    
    Finds products in the same category with similar attributes.
    """
    cache_key = f"product:{product_id}:similar:limit{limit}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    try:
        # This single query is parameterized, efficient, and handles all logic in BigQuery.
        query = f"""
        WITH
          -- Step 1: Get the attributes and average price of our base product ONCE.
          BaseProduct AS (
            SELECT
              p.brand_native,
              p.predicted_master_category_id AS category_id,
              AVG(lp.current_price) AS avg_price
            FROM
              `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` AS p
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` AS v ON p.shop_product_id = v.shop_product_id
            JOIN (
                SELECT variant_id, current_price FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
                QUALIFY ROW_NUMBER() OVER(PARTITION BY variant_id ORDER BY date_id DESC) = 1
            ) AS lp ON v.variant_id = lp.variant_id
            WHERE p.shop_product_id = @product_id
            GROUP BY 1, 2
          ),
          
          -- Step 2: Get latest prices for all products (to avoid duplicate QUALIFY statements)
          LatestPrices AS (
            SELECT
              v.variant_id, 
              v.shop_product_id,
              fpp.current_price,
              fpp.original_price,
              fpp.is_available
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` AS v
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` AS fpp ON v.variant_id = fpp.variant_id
            QUALIFY ROW_NUMBER() OVER(PARTITION BY v.variant_id ORDER BY fpp.date_id DESC) = 1
          ),

          -- Step 3: Calculate similarity scores for all other products.
          SimilarProducts AS (
            SELECT
              sp.shop_product_id AS id,
              sp.product_title_native AS name,
              sp.brand_native AS brand,
              c.category_name AS category,
              lp.current_price AS price,
              lp.original_price,
              s.shop_name AS retailer,
              pi.image_url AS image,
              -- This calculation uses a CROSS JOIN with our base product data
              (
                CASE WHEN sp.brand_native = bp.brand_native THEN 50 ELSE 0 END +
                CASE WHEN sp.predicted_master_category_id = bp.category_id THEN 30 ELSE 0 END +
                CASE WHEN lp.current_price BETWEEN bp.avg_price * 0.7 AND bp.avg_price * 1.3 THEN 20 ELSE 0 END
              ) AS similarity_score
            FROM
              `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` AS sp
            CROSS JOIN BaseProduct AS bp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` AS c ON sp.predicted_master_category_id = c.category_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` AS v ON sp.shop_product_id = v.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` AS s ON sp.shop_id = s.shop_id
            JOIN LatestPrices AS lp ON v.variant_id = lp.variant_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` AS pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
            WHERE
              sp.shop_product_id != @product_id AND lp.is_available = TRUE
          )

        -- Step 3: First filter products based on similarity, then group
        SELECT
            id, name, brand, category,
            -- This pattern ensures the other fields correspond to the row with the minimum price.
            ARRAY_AGG(STRUCT(price, original_price, retailer, image) ORDER BY price ASC LIMIT 1)[OFFSET(0)].*,
            MAX(similarity_score) AS similarity_score
        FROM SimilarProducts
        WHERE similarity_score > 30 -- Filter out products that are not very similar
        GROUP BY id, name, brand, category
        ORDER BY similarity_score DESC, price ASC
        LIMIT @limit
        """
        
        # Use query parameters to prevent SQL injection
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("product_id", "INT64", product_id),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
            ]
        )
        
        query_job = bq_client.query(query, job_config=job_config)
        results = [dict(row) for row in query_job.result()]
        
        # Format the similar products (no transformation needed with new query)
        result = {"similar_products": results}
        
        # Cache the result
        cache_service.set(cache_key, result, 86400)  # Cache for 24 hours
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred: {e}"
        )


@router.get("/{product_id}/recommendations", response_model=RecommendationsResponse)
async def get_product_recommendations(
    product_id: int = Path(..., description="The ID of the product"),
    limit: int = Query(6, ge=1, le=20, description="Number of recommendations to return"),
    current_user: Optional[Dict] = Depends(get_current_user),
    bq_client: bigquery.Client = Depends(get_bigquery_client),
    supabase_client = Depends(get_supabase_client)
) -> Dict:
    """
    Get personalized product recommendations.
    
    If authenticated, returns personalized recommendations based on user browsing history.
    Otherwise, returns product-to-product recommendations.
    """
    try:
        # Different logic based on whether user is authenticated
        if current_user:
            # Personalized recommendations for authenticated users
            user_id = current_user.get("sub")
            
            # If we have personalized recommendations in the warehouse, use those
            personalized_query = f"""
            SELECT
                sp.shop_product_id as id,
                sp.product_title_native as name,
                sp.brand_native as brand,
                c.category_name as category,
                fpp.current_price as price,
                fpp.original_price,
                s.shop_name as retailer,
                pi.image_url as image,
                fpr.recommendation_score,
                fpr.recommendation_type
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactPersonalizedRecommendation` fpr
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON fpr.recommended_variant_id = v.variant_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON v.shop_product_id = sp.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
            WHERE fpr.user_id = '{user_id}'
            AND sp.shop_product_id != {product_id}
            AND fpp.is_available = TRUE
            -- Get the latest price info
            QUALIFY ROW_NUMBER() OVER(PARTITION BY v.variant_id ORDER BY fpp.date_id DESC) = 1
            ORDER BY fpr.recommendation_score DESC
            LIMIT {limit}
            """
            
            personalized_job = bq_client.query(personalized_query)
            personalized_results = list(personalized_job.result())
            
            if personalized_results:
                # We have personalized recommendations
                recommendations = []
                for row in personalized_results:
                    recommendations.append({
                        "id": row["id"],
                        "name": row["name"],
                        "brand": row["brand"],
                        "category": row["category"],
                        "price": row["price"],
                        "original_price": row["original_price"],
                        "retailer": row["retailer"],
                        "image": row["image"],
                        "recommendation_score": row["recommendation_score"],
                        "recommendation_type": row["recommendation_type"]
                    })
                
                return {"recommendations": recommendations}
            
            # Fallback to product-to-product recommendations if no personalized ones
        
        # Product-to-product recommendations (for non-authenticated users or as fallback)
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
            fpr.recommendation_score,
            fpr.recommendation_type
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductRecommendation` fpr
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON fpr.recommended_shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
        WHERE fpr.source_shop_product_id = {product_id}
        AND fpp.is_available = TRUE
        -- Get the latest price info
        QUALIFY ROW_NUMBER() OVER(PARTITION BY v.variant_id ORDER BY fpp.date_id DESC) = 1
        ORDER BY fpr.recommendation_score DESC, fpp.current_price ASC
        LIMIT {limit}
        """
        
        query_job = bq_client.query(query)
        results = list(query_job.result())
        
        # Format the recommendations
        recommendations = []
        for row in results:
            recommendations.append({
                "id": row["id"],
                "name": row["name"],
                "brand": row["brand"],
                "category": row["category"],
                "price": row["price"],
                "original_price": row["original_price"],
                "retailer": row["retailer"],
                "image": row["image"],
                "recommendation_score": row["recommendation_score"],
                "recommendation_type": row["recommendation_type"]
            })
        
        # If we still don't have enough recommendations, fetch some from the same category
        if len(recommendations) < limit:
            needed = limit - len(recommendations)
            
            # Get the category of the current product
            category_query = f"""
            SELECT c.category_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
            WHERE sp.shop_product_id = {product_id}
            """
            
            category_job = bq_client.query(category_query)
            category_results = list(category_job.result())
            
            if category_results:
                category_id = category_results[0]["category_id"]
                
                # Get popular products from the same category
                popular_query = f"""
                WITH RankedProducts AS (
                    SELECT
                        sp.shop_product_id as id,
                        sp.product_title_native as name,
                        sp.brand_native as brand,
                        c.category_name as category,
                        fpp.current_price as price,
                        fpp.original_price,
                        s.shop_name as retailer,
                        pi.image_url as image,
                        ROW_NUMBER() OVER(PARTITION BY sp.shop_product_id ORDER BY fpp.current_price ASC) as rn
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
                    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
                    LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
                    WHERE c.category_id = {category_id}
                    AND sp.shop_product_id != {product_id}
                    AND fpp.is_available = TRUE
                    -- Get the latest price info
                    QUALIFY ROW_NUMBER() OVER(PARTITION BY v.variant_id ORDER BY fpp.date_id DESC) = 1
                )
                SELECT * FROM RankedProducts 
                WHERE rn = 1
                ORDER BY RAND()
                LIMIT {needed}
                """
                
                popular_job = bq_client.query(popular_query)
                popular_results = list(popular_job.result())
                
                for row in popular_results:
                    recommendations.append({
                        "id": row["id"],
                        "name": row["name"],
                        "brand": row["brand"],
                        "category": row["category"],
                        "price": row["price"],
                        "original_price": row["original_price"],
                        "retailer": row["retailer"],
                        "image": row["image"],
                        "recommendation_score": 0.5,  # Default score
                        "recommendation_type": "category_match"
                    })
        
        return {"recommendations": recommendations}
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while fetching product recommendations: {e}"
        )


@router.get("/compare", response_model=ComparisonResponse)
async def compare_products(
    product_ids: str = Query(..., description="Comma-separated list of product IDs to compare"),
    retailer_id: Optional[int] = Query(None, description="Compare prices from specific retailer"),
    response: Response = None,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Compare multiple products side by side.
    
    Shows specifications and prices for multiple products to aid comparison.
    """
    try:
        # Parse the product IDs
        try:
            ids = [int(id.strip()) for id in product_ids.split(",")]
            if len(ids) < 2 or len(ids) > 5:  # Limit comparisons to between 2 and 5 products
                raise HTTPException(
                    status_code=400,
                    detail="Please provide between 2 and 5 product IDs to compare"
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid product IDs. Please provide comma-separated integer IDs."
            )
        
        # Generate a placeholder query for product comparison
        # In a real implementation, you would need to fetch product specifications
        # Here we'll just get basic product info
        ids_str = ", ".join(str(id) for id in ids)
        
        query = f"""
        WITH ProductInfo AS (
            SELECT
                sp.shop_product_id as id,
                sp.product_title_native as name,
                sp.brand_native as brand,
                c.category_name as category,
                v.variant_id,
                s.shop_id,
                s.shop_name as retailer,
                fpp.current_price as price,
                fpp.original_price,
                fpp.is_available,
                pi.image_url as image,
                CASE
                    WHEN fpp.original_price > 0 AND fpp.original_price > fpp.current_price
                    THEN ROUND(((fpp.original_price - fpp.current_price) / fpp.original_price) * 100, 0)
                    ELSE 0
                END as discount,
                ROW_NUMBER() OVER(PARTITION BY sp.shop_product_id ORDER BY
                    -- If retailer_id is specified, prioritize that retailer
                    {f"CASE WHEN s.shop_id = {retailer_id} THEN 0 ELSE 1 END," if retailer_id else ""}
                    fpp.is_available DESC, 
                    fpp.current_price ASC
                ) as rn
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fpp ON v.variant_id = fpp.variant_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi ON sp.shop_product_id = pi.shop_product_id AND pi.sort_order = 1
            WHERE sp.shop_product_id IN ({ids_str})
            -- Get the latest price info
            QUALIFY ROW_NUMBER() OVER(PARTITION BY v.variant_id ORDER BY fpp.date_id DESC) = 1
        )
        SELECT * FROM ProductInfo WHERE rn = 1
        """
        
        query_job = bq_client.query(query)
        results = list(query_job.result())
        
        if len(results) < len(ids):
            # Some products were not found
            found_ids = [row["id"] for row in results]
            missing_ids = [id for id in ids if id not in found_ids]
            raise HTTPException(
                status_code=404,
                detail=f"Products not found: {missing_ids}"
            )
        
        # Format the comparison data
        compared_products = []
        for row in results:
            # In a real implementation, you would include detailed specs here
            # For now, we'll use placeholder data
            specs = {
                "processor": f"Sample Processor {row['id']}",
                "memory": f"{4 + (row['id'] % 4) * 4}GB",
                "storage": f"{128 * (1 + row['id'] % 4)}GB",
                "screen": f"{10 + (row['id'] % 8)}\"",
                "battery": f"{3000 + (row['id'] % 10) * 500}mAh"
            }
            
            attributes = {
                "color": ["Black", "White", "Silver", "Blue"][row["id"] % 4],
                "weight": f"{100 + (row['id'] % 10) * 50}g",
                "dimensions": f"{140 + (row['id'] % 5)}x{70 + (row['id'] % 3)}x{8 + (row['id'] % 3)}mm",
                "warranty": "1 year"
            }
            
            compared_products.append({
                "id": row["id"],
                "name": row["name"],
                "brand": row["brand"],
                "category": row["category"],
                "price": row["price"],
                "original_price": row["original_price"],
                "discount": row["discount"],
                "retailer": row["retailer"],
                "image": row["image"],
                "specs": specs,
                "attributes": attributes
            })
        
        # Determine common attributes to use as comparison points
        common_attributes = ["processor", "memory", "storage", "screen", "battery", "color", "weight", "dimensions", "warranty"]
        
        return {
            "comparison": compared_products,
            "common_attributes": common_attributes
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while comparing products: {e}"
        )


@router.post("/{product_id}/favorite", response_model=FavoriteResponse)
async def add_to_favorites(
    product_id: int = Path(..., description="The ID of the product to favorite"),
    current_user: Dict = Depends(get_current_user),
    bq_client: bigquery.Client = Depends(get_bigquery_client),
    supabase_client = Depends(get_supabase_client)
) -> Dict:
    """
    Add a product to the user's favorites.
    
    Requires authentication.
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required"
            )
        
        # First, get the variant ID for this product
        variant_query = f"""
        SELECT v.variant_id
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        WHERE sp.shop_product_id = {product_id}
        LIMIT 1
        """
        
        variant_job = bq_client.query(variant_query)
        variant_results = list(variant_job.result())
        
        if not variant_results:
            raise HTTPException(
                status_code=404,
                detail=f"Product with ID {product_id} not found"
            )
        
        variant_id = variant_results[0]["variant_id"]
        
        # Check if already favorited
        check_response = supabase_client.table("UserFavorites") \
            .select("favorite_id") \
            .eq("user_id", user_id) \
            .eq("variant_id", variant_id) \
            .execute()
        
        if check_response.data:
            return {
                "is_favorited": True,
                "message": "Product was already in favorites"
            }
        
        # Add to favorites
        insert_response = supabase_client.table("UserFavorites") \
            .insert({
                "user_id": user_id,
                "variant_id": variant_id
            }) \
            .execute()
        
        if not insert_response.data:
            raise HTTPException(
                status_code=500,
                detail="Failed to add product to favorites"
            )
        
        return {
            "is_favorited": True,
            "message": "Product added to favorites"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while adding to favorites: {e}"
        )


@router.delete("/{product_id}/favorite", response_model=FavoriteResponse)
async def remove_from_favorites(
    product_id: int = Path(..., description="The ID of the product to unfavorite"),
    current_user: Dict = Depends(get_current_user),
    bq_client: bigquery.Client = Depends(get_bigquery_client),
    supabase_client = Depends(get_supabase_client)
) -> Dict:
    """
    Remove a product from the user's favorites.
    
    Requires authentication.
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required"
            )
        
        # First, get the variant ID for this product
        variant_query = f"""
        SELECT v.variant_id
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        WHERE sp.shop_product_id = {product_id}
        """
        
        variant_job = bq_client.query(variant_query)
        variant_results = list(variant_job.result())
        
        if not variant_results:
            raise HTTPException(
                status_code=404,
                detail=f"Product with ID {product_id} not found"
            )
        
        # Get all variant IDs for this product
        variant_ids = [row["variant_id"] for row in variant_results]
        
        # Remove from favorites
        delete_response = supabase_client.table("UserFavorites") \
            .delete() \
            .eq("user_id", user_id) \
            .in_("variant_id", variant_ids) \
            .execute()
        
        return {
            "is_favorited": False,
            "message": "Product removed from favorites"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while removing from favorites: {e}"
        )


@router.post("/{product_id}/view", response_model=ViewLogResponse)
async def log_product_view(
    product_id: int = Path(..., description="The ID of the product viewed"),
    session_id: Optional[str] = Query(None, description="Session ID for anonymous users"),
    variant_id: Optional[int] = Query(None, description="Specific variant viewed"),
    current_user: Optional[Dict] = Depends(get_current_user),
    supabase_client = Depends(get_supabase_client)
) -> Dict:
    """
    Log that a user viewed a product.
    
    This helps with personalized recommendations and analytics.
    """
    try:
        user_id = None
        if current_user:
            user_id = current_user.get("sub")
        
        # If no session_id and no user_id, we can't log the view
        if not session_id and not user_id:
            raise HTTPException(
                status_code=400,
                detail="Either session_id or authentication is required"
            )
        
        # If variant_id is not provided, try to get it from the product
        if not variant_id:
            variant_query = f"""
            SELECT v.variant_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
            WHERE sp.shop_product_id = {product_id}
            LIMIT 1
            """
            
            bq_client = get_bigquery_client()
            variant_job = bq_client.query(variant_query)
            variant_results = list(variant_job.result())
            
            if variant_results:
                variant_id = variant_results[0]["variant_id"]
        
        # Log the view
        insert_response = supabase_client.table("UserActivityLog") \
            .insert({
                "user_id": user_id,
                "session_id": session_id,
                "activity_type": "PRODUCT_VIEW",
                "variant_id": variant_id
            }) \
            .execute()
        
        if not insert_response.data:
            raise HTTPException(
                status_code=500,
                detail="Failed to log product view"
            )
        
        return {"logged": True}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while logging product view: {e}"
        )
