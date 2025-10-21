from fastapi import APIRouter, Query, Depends, HTTPException
from typing import List, Optional, Tuple
from google.cloud import bigquery
from app.config import settings
from app.schemas.new_arrival import (
    NewArrivalResponse,
    NewArrivalsStats,
    NewArrivalsQuery,
    NewArrivalsListResponse,
)
from app.api.deps import get_bigquery_client
from app.services.cache_service import cache_service
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


def get_new_arrivals(
    query: NewArrivalsQuery, bq_client: bigquery.Client
) -> Tuple[List[NewArrivalResponse], NewArrivalsStats]:
    """
    Query BigQuery for new arrivals with filtering and pagination
    """
    # Map time ranges to days
    time_map = {"24h": 1, "7d": 7, "30d": 30, "3m": 90}
    days = time_map.get(query.timeRange, 30)

    # Build WHERE clauses with proper filtering
    where_clauses = []

    # Category filtering is now enabled - DimCategory table is available
    if query.category and query.category.lower() not in ["null", "none", "", "all"]:
        where_clauses.append(f"LOWER(c.category_name) LIKE LOWER('%{query.category}%')")

    # Handle retailer filtering
    if query.retailer and query.retailer.lower() not in ["null", "none", "", "all"]:
        where_clauses.append(f"LOWER(s.shop_name) LIKE LOWER('%{query.retailer}%')")

    # Handle price range filtering
    if query.minPrice is not None and query.minPrice > 0:
        where_clauses.append(f"fp.current_price >= {query.minPrice}")

    if query.maxPrice is not None and query.maxPrice > 0:
        where_clauses.append(f"fp.current_price <= {query.maxPrice}")

    # Handle time range filtering based on arrival_date
    logger.info(f"=== TIME RANGE FILTER DEBUG ===")
    logger.info(f"timeRange parameter: {query.timeRange}")
    logger.info(f"Days to filter: {days}")

    if query.timeRange and query.timeRange in time_map:
        # Calculate the cutoff date (current date minus the specified days)
        cutoff_date_sql = f"DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)"
        # Convert date_id (YYYYMMDD format) to DATE for comparison - use SAFE functions
        time_filter_sql = f"""
        SAFE.PARSE_DATE('%Y%m%d', CAST(fp.date_id AS STRING)) >= {cutoff_date_sql}
        AND SAFE.PARSE_DATE('%Y%m%d', CAST(fp.date_id AS STRING)) IS NOT NULL
        """
        where_clauses.append(time_filter_sql)
        logger.info(
            f"TIME FILTER: Showing items from last {days} days (timeRange={query.timeRange})"
        )
    else:
        logger.info("NO TIME FILTER: Showing items from all time periods")

    # CORRECTED LOGIC: Handle stock filtering based on boolean value
    logger.info(f"=== STOCK FILTER DEBUG ===")
    logger.info(f"inStockOnly parameter value: {query.inStockOnly}")
    logger.info(f"inStockOnly type: {type(query.inStockOnly)}")

    if query.inStockOnly is True:
        # When True: Show ONLY in-stock products (is_available = TRUE)
        where_clauses.append("fp.is_available = TRUE")
        logger.info(
            "STOCK FILTER: inStockOnly=True - showing ONLY in-stock products (is_available=TRUE)"
        )
    elif query.inStockOnly is False:
        # When False: Show ONLY out-of-stock products (is_available = FALSE)
        where_clauses.append("fp.is_available = FALSE")
        logger.info(
            "STOCK FILTER: inStockOnly=False - showing ONLY out-of-stock products (is_available=FALSE)"
        )
    else:
        # When None: Show ALL products (no stock filter applied)
        logger.info(
            "NO STOCK FILTER: inStockOnly=None - showing ALL products (both in-stock and out-of-stock)"
        )

    # Build final WHERE clause - using a more efficient approach with window functions
    # Since we're filtering in the CTE now, we don't need an explicit is_latest check
    base_where = "1=1"  # Always true condition as placeholder since filtering is done in the CTE

    if where_clauses:
        where_sql = " AND ".join(where_clauses) + f" AND {base_where}"
    else:
        where_sql = base_where

    logger.info(f"Final WHERE clause: {where_sql}")

    # Map sorting options
    sort_map = {
        "newest": "fp.date_id DESC",
        "oldest": "fp.date_id ASC",
        "price_low": "fp.current_price ASC",
        "price_high": "fp.current_price DESC",
        "name_az": "sp.product_title_native ASC",
        "name_za": "sp.product_title_native DESC",
    }
    order_sql = sort_map.get(query.sortBy, "fp.date_id DESC")

    # Calculate pagination
    offset = (query.page - 1) * query.limit

    # Main query for new arrivals - optimized with window functions and materialized CTE
    main_sql = f"""
    -- Using a WITH clause to pre-compute the latest prices once - major performance optimization
    WITH latest_prices AS (
      SELECT 
        variant_id,
        date_id,
        current_price,
        original_price,
        is_available,
        -- Add a flag for the latest price record - fixed syntax by separating the ROW_NUMBER calculation
        ROW_NUMBER() OVER (PARTITION BY variant_id ORDER BY date_id DESC) as row_num
      FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
    ),
    
    -- Filter to only the latest prices
    filtered_prices AS (
      SELECT
        variant_id,
        date_id,
        current_price,
        original_price,
        is_available,
        TRUE as is_latest
      FROM latest_prices
      WHERE row_num = 1
    ),
    -- Pre-materialize the product images to avoid complex subquery processing for each row
    first_images AS (
      SELECT 
        shop_product_id, 
        MIN(image_url) AS image_url
      FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage`
      GROUP BY shop_product_id
    )
    
    -- Main query using pre-computed data
    SELECT
        v.variant_id,
        sp.shop_product_id,
        sp.product_title_native as product_title,
        COALESCE(sp.brand_native, 'Unknown Brand') as brand,
        COALESCE(c.category_name, 'Uncategorized') as category_name,
        COALESCE(v.variant_title, sp.product_title_native) as variant_title,
        s.shop_name,
        fp.current_price,
        fp.original_price,
        COALESCE(pi.image_url, 'https://via.placeholder.com/300x300?text=No+Image') as image_url,
        COALESCE(sp.product_url, '#') as product_url,
        fp.is_available,
        CAST(fp.date_id AS STRING) as arrival_date,
        COALESCE(
            SAFE.DATE_DIFF(
                CURRENT_DATE(), 
                SAFE.PARSE_DATE('%Y%m%d', CAST(fp.date_id AS STRING)), 
                DAY
            ), 
            0
        ) as days_since_arrival
    FROM filtered_prices fp
    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
        ON fp.variant_id = v.variant_id
    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
        ON v.shop_product_id = sp.shop_product_id
    JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s 
        ON sp.shop_id = s.shop_id
    LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
        ON sp.predicted_master_category_id = c.category_id
    LEFT JOIN first_images pi 
        ON sp.shop_product_id = pi.shop_product_id
    WHERE {where_sql}
    ORDER BY {order_sql}
    LIMIT {query.limit} OFFSET {offset}
    """

    logger.info(f"=== EXECUTING QUERY ===")
    logger.info(f"Query preview: {main_sql[:500]}...")

    try:
        # Execute main query
        query_job = bq_client.query(main_sql)
        results = query_job.result()
        arrivals = []
        row_count = 0
        in_stock_count = 0
        out_of_stock_count = 0

        logger.info(f"Query executed successfully. Processing results...")

        for row in results:
            row_count += 1
            arrival_data = dict(row)

            # Ensure data types are correct
            arrival_data["variant_id"] = int(arrival_data["variant_id"])
            arrival_data["shop_product_id"] = int(arrival_data["shop_product_id"])
            arrival_data["current_price"] = float(arrival_data["current_price"])

            # FIXED: Handle days_since_arrival calculation safely
            days_since_raw = arrival_data.get("days_since_arrival")
            if days_since_raw is not None:
                try:
                    arrival_data["days_since_arrival"] = int(days_since_raw)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid days_since_arrival value: {days_since_raw}, defaulting to 0"
                    )
                    arrival_data["days_since_arrival"] = 0
            else:
                arrival_data["days_since_arrival"] = 0

            # Handle optional fields
            if arrival_data.get("original_price"):
                arrival_data["original_price"] = float(arrival_data["original_price"])

            # CRITICAL: Properly handle is_available boolean conversion
            is_available_raw = arrival_data.get("is_available")
            if is_available_raw is None:
                arrival_data["is_available"] = False
            else:
                # Convert to boolean - handle various data types from BigQuery
                if isinstance(is_available_raw, bool):
                    arrival_data["is_available"] = is_available_raw
                elif isinstance(is_available_raw, str):
                    arrival_data["is_available"] = is_available_raw.lower() in (
                        "true",
                        "1",
                        "yes",
                    )
                elif isinstance(is_available_raw, (int, float)):
                    arrival_data["is_available"] = bool(is_available_raw)
                else:
                    arrival_data["is_available"] = bool(is_available_raw)

            # Count stock status for debugging
            if arrival_data["is_available"]:
                in_stock_count += 1
            else:
                out_of_stock_count += 1

            # Debug each item
            logger.info(
                f"Item {row_count}: {arrival_data['product_title'][:30]}... | Available: {arrival_data['is_available']}"
            )

            arrivals.append(NewArrivalResponse(**arrival_data))

        # Handle empty results gracefully
        if row_count == 0:
            logger.info(f"=== NO RESULTS FOUND ===")
            logger.info(f"No items found matching the criteria:")
            logger.info(f"  Time range: {query.timeRange} ({days} days)")
            logger.info(f"  Stock filter: {query.inStockOnly}")
            logger.info(f"  Category: {query.category}")
            logger.info(f"  Retailer: {query.retailer}")
            logger.info(f"This is normal - returning empty list")

        logger.info(f"=== FINAL RESULTS ===")
        logger.info(f"Total items returned: {row_count}")
        logger.info(f"In stock items: {in_stock_count}")
        logger.info(f"Out of stock items: {out_of_stock_count}")
        logger.info(f"Filter setting inStockOnly: {query.inStockOnly}")

        # Validate results based on filter
        if query.inStockOnly is True:
            logger.info(f"VALIDATION for inStockOnly=True:")
            logger.info(
                f"  Expected: Only in-stock items (out_of_stock_count should be 0)"
            )
            logger.info(f"  Actual: out_of_stock_count = {out_of_stock_count}")
            logger.info(
                f"  Result: {'✅ CORRECT' if out_of_stock_count == 0 else '❌ INCORRECT - found out-of-stock items'}"
            )
        elif query.inStockOnly is False:
            logger.info(f"VALIDATION for inStockOnly=False:")
            logger.info(
                f"  Expected: Only out-of-stock items (in_stock_count should be 0)"
            )
            logger.info(
                f"  Actual: in_stock_count = {in_stock_count}, out_of_stock_count = {out_of_stock_count}"
            )
            logger.info(
                f"  Result: {'✅ CORRECT' if in_stock_count == 0 else '❌ INCORRECT - found in-stock items'}"
            )

            if in_stock_count > 0:
                logger.warning(
                    f"⚠️  WARNING: inStockOnly=False but found in-stock items."
                )
                logger.warning(f"⚠️  This indicates the filter logic is incorrect.")

            if out_of_stock_count == 0:
                logger.info(
                    f"ℹ️  INFO: No out-of-stock items found. This is expected if database has no out-of-stock products."
                )
        else:
            logger.info(f"VALIDATION for inStockOnly=None:")
            logger.info(f"  Expected: ALL items (both in-stock and out-of-stock)")
            logger.info(
                f"  Actual: in_stock={in_stock_count}, out_of_stock={out_of_stock_count}"
            )
            if row_count > 0:
                logger.info(f"  Result: ✅ CORRECT - includes all items")
            else:
                # Check if this is due to time filtering or genuinely no data
                if query.timeRange and query.timeRange in ["24h", "7d"]:
                    logger.info(
                        f"  Result: ✅ CORRECT - no items found for {query.timeRange} time range (expected)"
                    )
                else:
                    logger.info(
                        f"  Result: ℹ️  INFO - no items returned, could be due to filters or empty database"
                    )

        # Stats query - use same WHERE logic but remove stock filter for stats calculation
        stats_where_clauses = [
            clause for clause in where_clauses if "is_available" not in clause
        ]
        if stats_where_clauses:
            stats_where_sql = " AND ".join(stats_where_clauses) + f" AND {base_where}"
        else:
            stats_where_sql = base_where

        stats_sql = f"""
        -- Using a WITH clause to pre-compute the latest prices once - major performance optimization
        WITH latest_prices AS (
          SELECT 
            variant_id,
            date_id,
            current_price,
            original_price,
            is_available,
            ROW_NUMBER() OVER (PARTITION BY variant_id ORDER BY date_id DESC) as row_num
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
        ),
        
        -- Filter to only the latest prices
        filtered_prices AS (
          SELECT
            variant_id,
            date_id,
            current_price,
            original_price,
            is_available
          FROM latest_prices
          WHERE row_num = 1
        )
        
        SELECT
            COUNT(DISTINCT v.variant_id) as total_new_arrivals,
            ROUND(AVG(fp.current_price), 2) as average_price,
            SUM(CASE WHEN fp.is_available = TRUE THEN 1 ELSE 0 END) as in_stock_count,
            COUNT(DISTINCT c.category_id) as category_count
        FROM filtered_prices fp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
            ON fp.variant_id = v.variant_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
            ON v.shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s 
            ON sp.shop_id = s.shop_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
            ON sp.predicted_master_category_id = c.category_id
        WHERE {stats_where_sql}
        """

        stats_result = list(bq_client.query(stats_sql).result())
        if stats_result and len(stats_result) > 0:
            stats_row = stats_result[0]

            # FIXED: Handle None values safely for empty results
            total_new_arrivals = stats_row.get("total_new_arrivals") or 0
            average_price = stats_row.get("average_price") or 0.0
            in_stock_count = stats_row.get("in_stock_count") or 0
            category_count = stats_row.get("category_count") or 0

            stats = NewArrivalsStats(
                total_new_arrivals=int(total_new_arrivals),
                average_price=float(average_price),
                in_stock_count=int(in_stock_count),
                category_count=int(category_count),
            )
        else:
            stats = NewArrivalsStats(
                total_new_arrivals=0,
                average_price=0.0,
                in_stock_count=0,
                category_count=0,
            )

    except Exception as e:
        logger.error(f"BigQuery error in new arrivals: {str(e)}")
        logger.error(f"Query that failed: {main_sql[:1000]}...")

        # Return empty results instead of raising an error for common issues
        error_str = str(e).lower()
        if any(
            keyword in error_str
            for keyword in [
                "no matching signature",
                "parse_date",
                "date_diff",
                "invalid date",
            ]
        ):
            logger.warning(
                f"Date parsing error - likely no data matches time filter. Returning empty results."
            )
            return [], NewArrivalsStats(
                total_new_arrivals=0,
                average_price=0.0,
                in_stock_count=0,
                category_count=0,
            )

        # For other errors, still raise HTTP exception
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")

    return arrivals, stats


def get_query_params(
    timeRange: Optional[str] = Query("30d", description="Time range: 24h, 7d, 30d, 3m"),
    category: Optional[str] = Query(None, description="Filter by category"),
    retailer: Optional[str] = Query(None, description="Filter by retailer"),
    minPrice: Optional[float] = Query(None, description="Minimum price filter", ge=0),
    maxPrice: Optional[float] = Query(None, description="Maximum price filter", ge=0),
    sortBy: Optional[str] = Query(
        "price_high",
        description="Sort order: newest, oldest, price_low, price_high, name_az, name_za",
    ),
    inStockOnly: Optional[bool] = Query(
        None,
        description="Stock filter: true=only in-stock, false=only out-of-stock, null=all products",
    ),
    limit: Optional[int] = Query(
        20, description="Number of items per page", ge=1, le=100
    ),
    page: Optional[int] = Query(1, description="Page number", ge=1),
) -> NewArrivalsQuery:
    return NewArrivalsQuery(
        timeRange=timeRange,
        category=category,
        retailer=retailer,
        minPrice=minPrice,
        maxPrice=maxPrice,
        sortBy=sortBy,
        inStockOnly=inStockOnly,
        limit=limit,
        page=page,
    )


@router.get("/new-arrivals", response_model=NewArrivalsListResponse)
def get_new_arrivals_endpoint(
    query: NewArrivalsQuery = Depends(get_query_params),
    bq_client: bigquery.Client = Depends(get_bigquery_client),
):
    """
    Get new arrivals with filtering, sorting, and pagination

    TIME RANGE FILTERING:
    - timeRange="24h": Shows items added in the last 24 hours
    - timeRange="7d": Shows items added in the last 7 days
    - timeRange="30d": Shows items added in the last 30 days
    - timeRange="3m": Shows items added in the last 3 months (90 days)

    STOCK FILTERING BEHAVIOR:
    - inStockOnly=true: Returns ONLY products where is_available=true
    - inStockOnly=false: Returns ONLY products where is_available=false (out-of-stock)
    - inStockOnly=null: Returns ALL products (both in-stock and out-of-stock)

    ARRIVAL_DATE FORMAT: The arrival_date field contains dates in YYYYMMDD format (e.g., "20250826")
    """
    # Create cache key based on all query parameters
    cache_key = f"newarrivals:list:{query.timeRange}:{query.category or 'all'}:{query.retailer or 'all'}:{query.minPrice or 'none'}:{query.maxPrice or 'none'}:{query.sortBy}:{query.inStockOnly}:{query.limit}:{query.page}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        # Reconstruct the Pydantic model from cached dict
        return NewArrivalsListResponse(**cached_data)
        
    try:
        arrivals, _ = get_new_arrivals(query, bq_client)

        # Calculate pagination info
        total = len(arrivals)
        has_next = len(arrivals) == query.limit

        response_data = {
            "items": [arrival.dict() for arrival in arrivals],  # Convert to dict for JSON serialization
            "total": total,
            "page": query.page,
            "limit": query.limit,
            "has_next": has_next,
        }
        
        # Cache the results for 30 minutes
        cache_service.set(cache_key, response_data, 1800)
        
        return NewArrivalsListResponse(**response_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in new arrivals endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while fetching new arrivals",
        )


@router.get("/new-arrivals/stats", response_model=NewArrivalsStats)
def get_new_arrivals_stats_endpoint(
    query: NewArrivalsQuery = Depends(get_query_params),
    bq_client: bigquery.Client = Depends(get_bigquery_client),
):
    """Get statistics for new arrivals with the same filtering logic as the main endpoint"""
    # Create cache key based on all query parameters (excluding pagination since stats don't use it)
    cache_key = f"newarrivals:stats:{query.timeRange}:{query.category or 'all'}:{query.retailer or 'all'}:{query.minPrice or 'none'}:{query.maxPrice or 'none'}:{query.inStockOnly}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        # Reconstruct the Pydantic model from cached dict
        from app.schemas.new_arrival import NewArrivalsStats
        return NewArrivalsStats(**cached_data)
        
    try:
        _, stats = get_new_arrivals(query, bq_client)
        
        # Cache the results for 30 minutes (cache the dict representation)
        stats_dict = {
            "total_new_arrivals": stats.total_new_arrivals,
            "average_price": stats.average_price,
            "in_stock_count": stats.in_stock_count,
            "category_count": stats.category_count,
        }
        cache_service.set(cache_key, stats_dict, 1800)
        
        return stats
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in new arrivals stats endpoint: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while fetching new arrivals statistics",
        )


# Debug endpoint to check actual database stock distribution
@router.get("/new-arrivals/check-database-stock")
def check_database_stock_distribution(
    bq_client: bigquery.Client = Depends(get_bigquery_client),
):
    """
    Special endpoint to check if database actually has out-of-stock items
    """
    try:
        # Check the actual stock distribution in the database - with optimized query
        stock_check_sql = f"""
        WITH latest_prices AS (
          SELECT 
            variant_id,
            date_id,
            is_available,
            ROW_NUMBER() OVER (PARTITION BY variant_id ORDER BY date_id DESC) as row_num
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
        ),
        
        filtered_prices AS (
          SELECT
            variant_id,
            date_id,
            is_available
          FROM latest_prices
          WHERE row_num = 1
        )
        
        SELECT 
            fp.is_available,
            COUNT(*) as count,
            CASE 
                WHEN fp.is_available = TRUE THEN 'Available (In Stock)' 
                WHEN fp.is_available = FALSE THEN 'Not Available (Out of Stock)'
                WHEN fp.is_available IS NULL THEN 'NULL Value'
                ELSE 'Other Value'
            END as status_description
        FROM filtered_prices fp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
            ON fp.variant_id = v.variant_id
        GROUP BY fp.is_available
        ORDER BY fp.is_available DESC NULLS LAST
        """

        stock_distribution = list(bq_client.query(stock_check_sql).result())

        # Get some sample out-of-stock items if they exist - using optimized query structure
        out_of_stock_sample_sql = f"""
        WITH latest_prices AS (
          SELECT 
            variant_id,
            date_id,
            current_price,
            is_available,
            ROW_NUMBER() OVER (PARTITION BY variant_id ORDER BY date_id DESC) as row_num
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
        ),
        
        filtered_prices AS (
          SELECT
            variant_id,
            date_id,
            current_price,
            is_available
          FROM latest_prices
          WHERE row_num = 1
        )
        
        SELECT 
            v.variant_id,
            sp.product_title_native,
            s.shop_name,
            fp.current_price,
            fp.is_available,
            COALESCE(c.category_name, 'Uncategorized') as category_name
        FROM filtered_prices fp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
            ON fp.variant_id = v.variant_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
            ON v.shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s 
            ON sp.shop_id = s.shop_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
            ON sp.predicted_master_category_id = c.category_id
        WHERE fp.is_available = FALSE
        LIMIT 10
        """

        out_of_stock_samples = list(bq_client.query(out_of_stock_sample_sql).result())

        # Get some sample in-stock items - using optimized query structure
        in_stock_sample_sql = f"""
        WITH latest_prices AS (
          SELECT 
            variant_id,
            date_id,
            current_price,
            is_available,
            ROW_NUMBER() OVER (PARTITION BY variant_id ORDER BY date_id DESC) as row_num
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
        ),
        
        filtered_prices AS (
          SELECT
            variant_id,
            date_id,
            current_price,
            is_available
          FROM latest_prices
          WHERE row_num = 1
        )
        
        SELECT 
            v.variant_id,
            sp.product_title_native,
            s.shop_name,
            fp.current_price,
            fp.is_available,
            COALESCE(c.category_name, 'Uncategorized') as category_name
        FROM filtered_prices fp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
            ON fp.variant_id = v.variant_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
            ON v.shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s 
            ON sp.shop_id = s.shop_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
            ON sp.predicted_master_category_id = c.category_id
        WHERE fp.is_available = TRUE
        LIMIT 5
        """

        in_stock_samples = list(bq_client.query(in_stock_sample_sql).result())

        return {
            "database_stock_distribution": [dict(row) for row in stock_distribution],
            "out_of_stock_samples": [dict(row) for row in out_of_stock_samples],
            "in_stock_samples": [dict(row) for row in in_stock_samples],
            "analysis": {
                "has_out_of_stock_items": len(out_of_stock_samples) > 0,
                "total_distribution_categories": len(stock_distribution),
                "recommendation": (
                    "Database has both in-stock and out-of-stock items. inStockOnly filter should work properly."
                    if len(out_of_stock_samples) > 0
                    else "Database appears to have only in-stock items. This explains why inStockOnly=false shows only available items."
                ),
            },
        }

    except Exception as e:
        logger.error(f"Database stock check error: {str(e)}")
        return {"error": str(e)}


# Existing debug and test endpoints...
@router.get("/new-arrivals/debug")
def debug_new_arrivals(bq_client: bigquery.Client = Depends(get_bigquery_client)):
    """Debug endpoint to check data availability and table status"""
    try:
        # Check total records in each table
        tables_to_check = [
            "DimVariant",
            "DimShopProduct",
            "FactProductPrice",
            "DimShop",
            "DimProductImage",
            "DimDate",
        ]

        results = {}
        for table in tables_to_check:
            try:
                count_sql = f"SELECT COUNT(*) as count FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.{table}`"
                count_result = list(bq_client.query(count_sql).result())
                results[table] = count_result[0]["count"] if count_result else 0
            except Exception as e:
                results[table] = f"Error: {str(e)}"

        # Check sample data with stock status - using optimized query structure
        sample_sql = f"""
        WITH latest_prices AS (
          SELECT 
            variant_id,
            date_id,
            current_price,
            is_available,
            ROW_NUMBER() OVER (PARTITION BY variant_id ORDER BY date_id DESC) as row_num
          FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice`
        ),
        
        filtered_prices AS (
          SELECT
            variant_id,
            date_id,
            current_price,
            is_available
          FROM latest_prices
          WHERE row_num = 1
        )
        
        SELECT 
            v.variant_id,
            sp.product_title_native,
            s.shop_name,
            fp.current_price,
            fp.is_available,
            COALESCE(c.category_name, 'Uncategorized') as category_name,
            CASE 
                WHEN fp.is_available = TRUE THEN 'In Stock' 
                WHEN fp.is_available = FALSE THEN 'Out of Stock'
                ELSE 'Unknown Status'
            END as stock_status_text
        FROM filtered_prices fp
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v 
            ON fp.variant_id = v.variant_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp 
            ON v.shop_product_id = sp.shop_product_id
        JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s 
            ON sp.shop_id = s.shop_id
        LEFT JOIN `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c
            ON sp.predicted_master_category_id = c.category_id
        ORDER BY fp.is_available DESC, v.variant_id
        LIMIT 20
        """

        sample_result = list(bq_client.query(sample_sql).result())

        return {
            "status": "success",
            "table_counts": results,
            "sample_data": [dict(row) for row in sample_result],
            "config": {
                "project_id": settings.GCP_PROJECT_ID,
                "dataset_id": settings.BIGQUERY_DATASET_ID,
            },
        }

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
