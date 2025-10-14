from fastapi import APIRouter, Query, Depends, HTTPException, Response
from typing import List, Optional, Tuple
from google.cloud import bigquery
import logging
from app.config import settings
from app.schemas.topdeals import (
    DealResponse,
    DealsStats,
    DealsQuery,
    DealsListResponse,
    DealsAnalyticsResponse,
    CategoryDealsStats,
    RetailerDealsStats,
)
from app.api.deps import get_bigquery_client
from app.services.cache_service import cache_service
import logging
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


def calculate_deal_score(
    discount_percentage: float, current_price: float, original_price: float
) -> float:
    """
    Calculate a deal quality score based on discount percentage and price range
    Returns a score between 0-100
    """
    # Base score from discount percentage (0-70 points)
    discount_score = min(discount_percentage * 1.4, 70)

    # Bonus points for higher value items (0-20 points)
    if original_price >= 1000:
        value_bonus = 20
    elif original_price >= 500:
        value_bonus = 15
    elif original_price >= 100:
        value_bonus = 10
    else:
        value_bonus = 5

    # Bonus for deep discounts (0-10 points)
    deep_discount_bonus = max(0, (discount_percentage - 30) * 0.5)

    total_score = min(discount_score + value_bonus + deep_discount_bonus, 100)
    return round(total_score, 2)


def get_deals(
    query: DealsQuery, bq_client: bigquery.Client
) -> Tuple[List[DealResponse], DealsStats]:
    """
    Query BigQuery for deals with filtering and pagination
    """
    # Build WHERE clauses with proper filtering
    where_clauses = [
        "fp.original_price > fp.current_price"
    ]  # Only products with discounts
    where_clauses.append("fp.original_price IS NOT NULL")  # Must have original price
    where_clauses.append("fp.current_price > 0")  # Must have valid current price

    # Handle category filtering
    if query.category and query.category.lower() not in ["null", "none", "", "all"]:
        if query.category.lower() == "uncategorized":
            where_clauses.append("c.category_name IS NULL OR LOWER(c.category_name) = 'uncategorized'")
        else:
            where_clauses.append(f"LOWER(COALESCE(c.category_name, 'Uncategorized')) LIKE LOWER('%{query.category}%')")

    # Handle retailer filtering
    if query.retailer and query.retailer.lower() not in ["null", "none", "", "all"]:
        where_clauses.append(f"LOWER(s.shop_name) LIKE LOWER('%{query.retailer}%')")

    # Handle brand filtering
    if query.brand and query.brand.lower() not in ["null", "none", "", "all"]:
        where_clauses.append(f"LOWER(sp.brand_native) LIKE LOWER('%{query.brand}%')")

    # Handle discount percentage filtering
    if query.min_discount is not None:
        where_clauses.append(
            f"((fp.original_price - fp.current_price) / fp.original_price * 100) >= {query.min_discount}"
        )

    if query.max_discount is not None:
        where_clauses.append(
            f"((fp.original_price - fp.current_price) / fp.original_price * 100) <= {query.max_discount}"
        )

    # Handle price range filtering (on current price)
    if query.min_price is not None and query.min_price > 0:
        where_clauses.append(f"fp.current_price >= {query.min_price}")

    if query.max_price is not None and query.max_price > 0:
        where_clauses.append(f"fp.current_price <= {query.max_price}")

    # Handle stock filtering
    if query.in_stock_only is True:
        where_clauses.append("fp.is_available = TRUE")

    logger.info(f"=== DEALS FILTER DEBUG ===")
    logger.info(f"Filters applied: {len(where_clauses)}")
    for i, clause in enumerate(where_clauses):
        logger.info(f"  {i+1}. {clause}")

    # Build final WHERE clause
    base_where = """
    fp.date_id = (
        SELECT MAX(date_id) 
        FROM `{}.{}.FactProductPrice` 
        WHERE variant_id = v.variant_id
    )
    """.format(
        settings.GCP_PROJECT_ID, settings.BIGQUERY_DATASET_ID
    )

    where_sql = " AND ".join(where_clauses) + f" AND {base_where}"

    # Map sorting options
    sort_map = {
        "discount_desc": "discount_percentage DESC",
        "discount_asc": "discount_percentage ASC",
        "price_low": "fp.current_price ASC",
        "price_high": "fp.current_price DESC",
        "deal_score": "deal_score DESC",
        "newest": "fp.date_id DESC",
    }
    order_sql = sort_map.get(query.sort_by, "discount_percentage DESC")

    # Calculate pagination
    offset = (query.page - 1) * query.limit

    # Main query for deals
    main_sql = f"""
    SELECT
        v.variant_id,
        sp.shop_product_id,
        sp.shop_product_id as product_id,
        sp.product_title_native as product_title,
        sp.brand_native as brand,
        COALESCE(c.category_name, 'Uncategorized') as category_name,
        COALESCE(v.variant_title, sp.product_title_native) as variant_title,
        s.shop_name,
        fp.current_price,
        fp.original_price,
        COALESCE(pi.image_url, 'https://via.placeholder.com/300x300?text=No+Image') as image_url,
        COALESCE(sp.product_url, '#') as product_url,
        fp.is_available,
        CAST(fp.date_id AS STRING) as updated_date,
        
        -- Calculate discount metrics
        ROUND(((fp.original_price - fp.current_price) / fp.original_price * 100), 2) as discount_percentage,
        ROUND((fp.original_price - fp.current_price), 2) as discount_amount,
        
        -- Calculate deal score (will be computed in Python)
        0.0 as deal_score
        
    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fp
    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
        ON fp.variant_id = v.variant_id
    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
        ON v.shop_product_id = sp.shop_product_id
    LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c 
        ON sp.predicted_master_category_id = c.category_id
    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s 
        ON sp.shop_id = s.shop_id
    LEFT JOIN (
        SELECT 
            shop_product_id, 
            image_url, 
            ROW_NUMBER() OVER (PARTITION BY shop_product_id ORDER BY COALESCE(sort_order, 999)) as rn
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage`
    ) pi ON sp.shop_product_id = pi.shop_product_id AND pi.rn = 1
    WHERE {where_sql}
    QUALIFY ROW_NUMBER() OVER(PARTITION BY sp.shop_product_id ORDER BY ((fp.original_price - fp.current_price) / fp.original_price * 100) DESC, fp.current_price ASC) = 1
    ORDER BY {order_sql}
    LIMIT {query.limit} OFFSET {offset}
    """

    logger.info(f"=== EXECUTING DEALS QUERY ===")
    logger.info(f"Query preview: {main_sql[:500]}...")

    try:
        # Execute main query
        query_job = bq_client.query(main_sql)
        results = query_job.result()
        deals = []
        row_count = 0

        logger.info(f"Query executed successfully. Processing results...")

        for row in results:
            row_count += 1
            deal_data = dict(row)

            # Ensure data types are correct
            deal_data["variant_id"] = int(deal_data["variant_id"])
            deal_data["shop_product_id"] = int(deal_data["shop_product_id"])
            deal_data["product_id"] = int(deal_data["product_id"])
            deal_data["current_price"] = float(deal_data["current_price"])
            deal_data["original_price"] = float(deal_data["original_price"])
            deal_data["discount_percentage"] = float(deal_data["discount_percentage"])
            deal_data["discount_amount"] = float(deal_data["discount_amount"])

            # Calculate deal score
            deal_data["deal_score"] = calculate_deal_score(
                deal_data["discount_percentage"],
                deal_data["current_price"],
                deal_data["original_price"],
            )

            # Handle boolean conversion for availability
            is_available_raw = deal_data.get("is_available")
            if isinstance(is_available_raw, bool):
                deal_data["is_available"] = is_available_raw
            elif isinstance(is_available_raw, str):
                deal_data["is_available"] = is_available_raw.lower() in (
                    "true",
                    "1",
                    "yes",
                )
            else:
                deal_data["is_available"] = bool(is_available_raw)

            # Debug logging
            logger.info(
                f"Deal {row_count}: {deal_data['product_title'][:30]}... | "
                f"Discount: {deal_data['discount_percentage']}% | "
                f"Score: {deal_data['deal_score']} | "
                f"Available: {deal_data['is_available']}"
            )

            deals.append(DealResponse(**deal_data))

        # Stats query - get overall statistics
        stats_sql = f"""
        WITH deal_data AS (
            SELECT
                v.variant_id,
                fp.current_price,
                fp.original_price,
                COALESCE(c.category_name, 'Uncategorized') as category_name,
                s.shop_name,
                fp.is_available,
                ROUND(((fp.original_price - fp.current_price) / fp.original_price * 100), 2) as discount_percentage,
                ROUND((fp.original_price - fp.current_price), 2) as discount_amount,
                sp.shop_product_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
                ON fp.variant_id = v.variant_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
                ON v.shop_product_id = sp.shop_product_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c 
                ON sp.predicted_master_category_id = c.category_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s 
                ON sp.shop_id = s.shop_id
            WHERE fp.original_price > fp.current_price
                AND fp.original_price IS NOT NULL
                AND fp.current_price > 0
                AND fp.date_id = (
                    SELECT MAX(date_id) 
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` 
                    WHERE variant_id = v.variant_id
                )
            QUALIFY ROW_NUMBER() OVER(PARTITION BY sp.shop_product_id ORDER BY 
                ROUND(((fp.original_price - fp.current_price) / fp.original_price * 100), 2) DESC) = 1
        )
        SELECT
            COUNT(DISTINCT variant_id) as total_deals,
            ROUND(AVG(discount_percentage), 2) as average_discount,
            ROUND(MAX(discount_percentage), 2) as highest_discount,
            ROUND(SUM(discount_amount), 2) as total_savings,
            COUNT(DISTINCT category_name) as categories_with_deals,
            COUNT(DISTINCT shop_name) as retailers_with_deals
        FROM deal_data
        """

        stats_result = list(bq_client.query(stats_sql).result())
        if stats_result and len(stats_result) > 0:
            stats_row = stats_result[0]
            stats = DealsStats(
                total_deals=int(stats_row.get("total_deals") or 0),
                average_discount=float(stats_row.get("average_discount") or 0.0),
                highest_discount=float(stats_row.get("highest_discount") or 0.0),
                total_savings=float(stats_row.get("total_savings") or 0.0),
                categories_with_deals=int(stats_row.get("categories_with_deals") or 0),
                retailers_with_deals=int(stats_row.get("retailers_with_deals") or 0),
            )
        else:
            stats = DealsStats(
                total_deals=0,
                average_discount=0.0,
                highest_discount=0.0,
                total_savings=0.0,
                categories_with_deals=0,
                retailers_with_deals=0,
            )

        logger.info(f"=== DEALS RESULTS ===")
        logger.info(f"Total deals returned: {row_count}")
        logger.info(f"Stats - Total deals in DB: {stats.total_deals}")
        logger.info(f"Stats - Average discount: {stats.average_discount}%")
        logger.info(f"Stats - Highest discount: {stats.highest_discount}%")

    except Exception as e:
        logger.error(f"BigQuery error in deals: {str(e)}")
        logger.error(f"Query that failed: {main_sql[:1000]}...")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return deals, stats


def get_query_params(
    category: Optional[str] = Query(None, description="Filter by category"),
    retailer: Optional[str] = Query(None, description="Filter by retailer"),
    brand: Optional[str] = Query(None, description="Filter by brand"),
    min_discount: Optional[float] = Query(
        None, description="Minimum discount percentage", ge=0, le=100
    ),
    max_discount: Optional[float] = Query(
        None, description="Maximum discount percentage", ge=0, le=100
    ),
    min_price: Optional[float] = Query(None, description="Minimum current price", ge=0),
    max_price: Optional[float] = Query(None, description="Maximum current price", ge=0),
    sort_by: Optional[str] = Query(
        "discount_desc",
        description="Sort order: discount_desc, discount_asc, price_low, price_high, deal_score, newest",
    ),
    in_stock_only: Optional[bool] = Query(
        True, description="Show only in-stock products"
    ),
    limit: Optional[int] = Query(
        20, description="Number of items per page", ge=1, le=100
    ),
    page: Optional[int] = Query(1, description="Page number", ge=1),
) -> DealsQuery:
    return DealsQuery(
        category=category,
        retailer=retailer,
        brand=brand,
        min_discount=min_discount,
        max_discount=max_discount,
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by,
        in_stock_only=in_stock_only,
        limit=limit,
        page=page,
    )


@router.get("/deals", response_model=DealsListResponse)
def get_deals_endpoint(
    response: Response,
    query: DealsQuery = Depends(get_query_params),
    bq_client: bigquery.Client = Depends(get_bigquery_client),
):
    """
    Get top deals with filtering, sorting, and pagination

    DEAL CRITERIA:
    - Only products with original_price > current_price (actual discounts)
    - Must have valid original_price and current_price
    - Calculates real discount percentage and amount
    - Includes deal quality score (0-100)

    FILTERING OPTIONS:
    - category: Filter by product category
    - retailer: Filter by retailer/shop
    - brand: Filter by product brand
    - min_discount/max_discount: Filter by discount percentage (0-100)
    - min_price/max_price: Filter by current price range
    - in_stock_only: Show only available products (default: true)

    SORTING OPTIONS:
    - discount_desc: Highest discount first (default)
    - discount_asc: Lowest discount first
    - price_low: Lowest price first
    - price_high: Highest price first
    - deal_score: Best deal score first
    - newest: Most recently updated first

    DEAL SCORE CALCULATION:
    - Based on discount percentage (0-70 points)
    - Value bonus for higher-priced items (0-20 points)
    - Deep discount bonus for 30%+ discounts (0-10 points)
    - Total score: 0-100 (higher is better)
    """
    # Cache key based on all query parameters
    cache_key = f"topdeals:deals:{query.category}:{query.retailer}:{query.brand}:{query.min_discount}:{query.max_discount}:{query.min_price}:{query.max_price}:{query.sort_by}:{query.in_stock_only}:{query.limit}:{query.page}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
        
    try:
        deals, stats = get_deals(query, bq_client)

        # Calculate pagination info
        total = len(deals)
        has_next = len(deals) == query.limit

        response_data = DealsListResponse(
            items=deals,
            total=total,
            page=query.page,
            limit=query.limit,
            has_next=has_next,
            stats=stats,
        )
        
        # Cache the data for 15 minutes (900 seconds)
        cache_service.set(cache_key, response_data, ttl_seconds=900)
        
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in deals endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while fetching deals",
        )


@router.get("/deals/stats", response_model=DealsStats)
def get_deals_stats_endpoint(
    response: Response,
    bq_client: bigquery.Client = Depends(get_bigquery_client),
):
    """Get overall deals statistics"""
    # Cache key for stats
    cache_key = "topdeals:stats"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
        
    try:
        dummy_query = DealsQuery()  # Use default query
        _, stats = get_deals(dummy_query, bq_client)
        
        # Cache the data for 1 hour (3600 seconds)
        cache_service.set(cache_key, stats, ttl_seconds=3600)
        
        return stats
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in deals stats endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while fetching deals statistics",
        )


@router.get("/deals/analytics", response_model=DealsAnalyticsResponse)
def get_deals_analytics_endpoint(
    response: Response,
    bq_client: bigquery.Client = Depends(get_bigquery_client),
):
    """
    Get comprehensive deals analytics including category and retailer breakdowns
    """
    # Cache key for analytics
    cache_key = "topdeals:analytics"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
        
    try:
        # Get overall stats
        dummy_query = DealsQuery()
        _, overall_stats = get_deals(dummy_query, bq_client)

        # Category breakdown query
        category_sql = f"""
        WITH deal_data AS (
            SELECT
                c.category_name,
                ROUND(((fp.original_price - fp.current_price) / fp.original_price * 100), 2) as discount_percentage,
                sp.shop_product_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
                ON fp.variant_id = v.variant_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
                ON v.shop_product_id = sp.shop_product_id
            LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c 
                ON sp.predicted_master_category_id = c.category_id
            WHERE fp.original_price > fp.current_price
                AND fp.original_price IS NOT NULL
                AND fp.current_price > 0
                AND fp.date_id = (
                    SELECT MAX(date_id) 
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` 
                    WHERE variant_id = v.variant_id
                )
            QUALIFY ROW_NUMBER() OVER(PARTITION BY sp.shop_product_id ORDER BY ((fp.original_price - fp.current_price) / fp.original_price * 100) DESC) = 1
        )
        SELECT
            COALESCE(category_name, 'Uncategorized') as category_name,
            COUNT(*) as deal_count,
            ROUND(AVG(discount_percentage), 2) as average_discount,
            ROUND(MAX(discount_percentage), 2) as highest_discount
        FROM deal_data
        GROUP BY COALESCE(category_name, 'Uncategorized')
        ORDER BY deal_count DESC
        LIMIT 10
        """

        category_results = list(bq_client.query(category_sql).result())
        category_breakdown = [
            CategoryDealsStats(
                category_name=row["category_name"],
                deal_count=int(row["deal_count"]),
                average_discount=float(row["average_discount"]),
                highest_discount=float(row["highest_discount"]),
            )
            for row in category_results
        ]

        # Retailer breakdown query
        retailer_sql = f"""
        WITH deal_data AS (
            SELECT
                s.shop_name,
                ROUND(((fp.original_price - fp.current_price) / fp.original_price * 100), 2) as discount_percentage,
                sp.shop_product_id
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fp
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
                ON fp.variant_id = v.variant_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
                ON v.shop_product_id = sp.shop_product_id
            JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s
                ON sp.shop_id = s.shop_id
            WHERE fp.original_price > fp.current_price
                AND fp.original_price IS NOT NULL
                AND fp.current_price > 0
                AND fp.date_id = (
                    SELECT MAX(date_id) 
                    FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` 
                    WHERE variant_id = v.variant_id
                )
            QUALIFY ROW_NUMBER() OVER(PARTITION BY sp.shop_product_id ORDER BY ((fp.original_price - fp.current_price) / fp.original_price * 100) DESC) = 1
        )
        SELECT
            shop_name,
            COUNT(*) as deal_count,
            ROUND(AVG(discount_percentage), 2) as average_discount,
            ROUND(MAX(discount_percentage), 2) as highest_discount
        FROM deal_data
        GROUP BY shop_name
        ORDER BY deal_count DESC
        LIMIT 10
        """

        retailer_results = list(bq_client.query(retailer_sql).result())
        retailer_breakdown = [
            RetailerDealsStats(
                shop_name=row["shop_name"],
                deal_count=int(row["deal_count"]),
                average_discount=float(row["average_discount"]),
                highest_discount=float(row["highest_discount"]),
            )
            for row in retailer_results
        ]

        # Extract trending categories and top retailers
        trending_categories = [cat.category_name for cat in category_breakdown[:5]]
        top_retailers = [ret.shop_name for ret in retailer_breakdown[:5]]

        response_data = DealsAnalyticsResponse(
            overall_stats=overall_stats,
            category_breakdown=category_breakdown,
            retailer_breakdown=retailer_breakdown,
            trending_categories=trending_categories,
            top_retailers=top_retailers,
        )
        
        # Cache the data for 2 hours (7200 seconds)
        cache_service.set(cache_key, response_data, ttl_seconds=7200)
        
        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in deals analytics endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while fetching deals analytics",
        )


# Debug endpoint
@router.get("/deals/debug")
def debug_deals(response: Response, bq_client: bigquery.Client = Depends(get_bigquery_client)):
    """Debug endpoint to check deals data availability"""
    # Cache key for debug info
    cache_key = "topdeals:debug"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
        
    try:
        # Check products with discounts
        discount_check_sql = f"""
        SELECT 
            COUNT(*) as total_products,
            SUM(CASE WHEN original_price > current_price THEN 1 ELSE 0 END) as products_with_discounts,
            SUM(CASE WHEN original_price IS NOT NULL THEN 1 ELSE 0 END) as products_with_original_price,
            ROUND(AVG(CASE WHEN original_price > current_price 
                          THEN (original_price - current_price) / original_price * 100 
                          ELSE NULL END), 2) as avg_discount_percentage
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fp
        WHERE fp.date_id = (
            SELECT MAX(date_id) 
            FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` 
            WHERE variant_id = fp.variant_id
        )
        """

        discount_stats = list(bq_client.query(discount_check_sql).result())

        # Sample deals
        sample_deals_sql = f"""
        SELECT 
            sp.product_title_native,
            s.shop_name,
            c.category_name,
            fp.current_price,
            fp.original_price,
            ROUND(((fp.original_price - fp.current_price) / fp.original_price * 100), 2) as discount_percentage
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
            ON fp.variant_id = v.variant_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
            ON v.shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c 
            ON sp.predicted_master_category_id = c.category_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s 
            ON sp.shop_id = s.shop_id
        WHERE fp.original_price > fp.current_price
            AND fp.original_price IS NOT NULL
            AND fp.current_price > 0
            AND fp.date_id = (
                SELECT MAX(date_id) 
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` 
                WHERE variant_id = v.variant_id
            )
        ORDER BY discount_percentage DESC
        LIMIT 10
        """

        sample_deals = list(bq_client.query(sample_deals_sql).result())

        response_data = {
            "status": "success",
            "discount_stats": [dict(row) for row in discount_stats],
            "sample_deals": [dict(row) for row in sample_deals],
            "config": {
                "project_id": settings.GCP_PROJECT_ID,
                "dataset_id": settings.BIGQUERY_DATASET_ID,
            },
        }
        
        # Cache the debug data for 1 hour (3600 seconds)
        cache_service.set(cache_key, response_data, ttl_seconds=3600)
        
        return response_data

    except Exception as e:
        logger.error(f"Debug endpoint error: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "config": {
                "project_id": settings.GCP_PROJECT_ID,
                "dataset_id": settings.BIGQUERY_DATASET_ID,
            },
        }
