from fastapi import APIRouter, Depends, HTTPException, Query, Response, Path
from typing import Dict, List, Optional, Any
from google.cloud import bigquery
from app.config import settings
from app.api.deps import get_current_user, get_bigquery_client, get_current_user_optional
from app.services.cache_service import cache_service
from app.schemas.retailer import (
    RetailerListResponse,
    RetailerDetailResponse,
    RetailerStatsResponse,
    CategoriesResponse,
    BrandsResponse
)

router = APIRouter()

# Cache duration constants
CACHE_TTL_SHORT = 300  # 5 minutes
CACHE_TTL_MEDIUM = 1800  # 30 minutes
CACHE_TTL_LONG = 86400  # 24 hours


@router.get("/", response_model=RetailerListResponse)
async def get_retailers(
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(10, ge=1, le=100, description="Number of retailers per page"),
    search: Optional[str] = Query(None, description="Search query for retailer name or description"),
    sort: str = Query("name", description="Sort by field: name, product_count, rating"),
    order: str = Query("asc", description="Sort order: asc or desc"),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Retrieve a paginated list of retailers with optional filtering.
    """
    # Cache key based on parameters
    cache_key = f"retailers:list:{page}:{limit}:{search}:{sort}:{order}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    # Validate sort and order parameters
    valid_sort_fields = {"name", "product_count", "rating"}
    if sort not in valid_sort_fields:
        sort = "name"
        
    valid_order_values = {"asc", "desc"}
    if order not in valid_order_values:
        order = "asc"
    
    # Map sort fields to actual BigQuery column names
    sort_field_mapping = {
        "name": "shop_name",
        "product_count": "product_count",
        "rating": "rating"
    }
    
    # Build the ORDER BY clause
    order_by_clause = f"{sort_field_mapping[sort]} {order.upper()}"
    
    # Build the WHERE clause for search if provided
    search_clause = ""
    search_params = {}
    if search:
        search_clause = "AND (LOWER(shop_name) LIKE LOWER(@search_term) OR LOWER(IFNULL(description, '')) LIKE LOWER(@search_term))"
        search_params["search_term"] = f"%{search}%"
    
    # Calculate pagination parameters
    offset = (page - 1) * limit
    
    # Build the optimized query with pagination
    query = f"""
    WITH retailer_counts AS (
        SELECT 
            s.shop_id,
            s.shop_name,
            s.website_url,
            COUNT(DISTINCT sp.shop_product_id) as product_count,
            -- Placeholder for rating calculation (can be replaced with actual logic)
            4.5 as rating,
            -- Additional fields to match schema
            TRUE as verified,
            CASE WHEN s.shop_id IN (1, 2, 3) THEN TRUE ELSE FALSE END as is_featured,
            'Colombo, Sri Lanka' as headquarters,
            2015 as founded_year,
            s.contact_phone,
            s.contact_whatsapp
        FROM 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s
        LEFT JOIN 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON s.shop_id = sp.shop_id
        WHERE 
            1=1
            {search_clause}
        GROUP BY 
            s.shop_id, s.shop_name, s.website_url, s.contact_phone, s.contact_whatsapp
    ),
    total_count AS (
        SELECT COUNT(*) as total FROM retailer_counts
    )
    SELECT 
        rc.*, 
        t.total as total_count
    FROM 
        retailer_counts rc,
        total_count t
    ORDER BY {order_by_clause}
    LIMIT {limit}
    OFFSET {offset}
    """
    
    try:
        # Execute query with parameters if search is provided
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("search_term", "STRING", f"%{search}%")
            ] if search else []
        )
        
        query_job = bq_client.query(query, job_config=job_config)
        results = query_job.result()
        
        # Extract retailer data from query results
        retailers = []
        total_count = 0
        
        for row in results:
            # Set total_count from the first row (it will be the same for all rows)
            if total_count == 0:
                total_count = row.total_count
                
            # Map retailer data to schema
            retailer = {
                "id": row.shop_id,
                "name": row.shop_name,
                "logo": f"https://example.com/logos/{row.shop_id}.png",  # Placeholder
                "website": row.website_url,
                "rating": row.rating,
                "product_count": row.product_count,
                "description": f"Leading retailer of consumer goods",  # Placeholder
                "verified": row.verified,
                "is_featured": row.is_featured,
                "headquarters": row.headquarters,
                "founded_year": row.founded_year,
                "contact": {
                    "email": f"info@{row.shop_name.lower().replace(' ', '')}.lk",  # Placeholder
                    "phone": row.contact_phone,
                    "address": "123 Main St, Colombo 03, Sri Lanka"  # Placeholder
                }
            }
            retailers.append(retailer)
        
        # Calculate pagination metadata
        total_pages = (total_count + limit - 1) // limit
        
        response = {
            "retailers": retailers,
            "meta": {
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "limit": limit
            }
        }
        
        # Cache the result for a medium duration
        cache_service.set(cache_key, response, ttl_seconds=CACHE_TTL_MEDIUM)
        
        return response
    
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to retrieve retailers: {str(e)}"
        )


@router.get("/{id}", response_model=RetailerDetailResponse)
async def get_retailer_by_id(
    id: int = Path(..., ge=0, description="The ID of the retailer to retrieve"),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Retrieve detailed information about a specific retailer.
    """
    # Cache key based on retailer ID
    cache_key = f"retailers:detail:{id}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    # Query to get retailer details and product count in one efficient query
    query = f"""
    SELECT 
        s.shop_id,
        s.shop_name,
        s.website_url,
        COUNT(DISTINCT sp.shop_product_id) as product_count,
        -- Placeholder for rating calculation (can be replaced with actual logic)
        4.5 as rating,
        s.contact_phone,
        s.contact_whatsapp
    FROM 
        `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s
    LEFT JOIN 
        `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON s.shop_id = sp.shop_id
    WHERE 
        s.shop_id = @shop_id
    GROUP BY 
        s.shop_id, s.shop_name, s.website_url, s.contact_phone, s.contact_whatsapp
    """
    
    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("shop_id", "INTEGER", id)
            ]
        )
        
        query_job = bq_client.query(query, job_config=job_config)
        results = query_job.result()
        
        # Check if retailer exists
        row = next(iter(results), None)
        if not row:
            raise HTTPException(status_code=404, detail=f"Retailer with ID {id} not found")
        
        # Map retailer data to schema
        retailer = {
            "id": row.shop_id,
            "name": row.shop_name,
            "logo": f"https://example.com/logos/{row.shop_id}.png",  # Placeholder
            "website": row.website_url,
            "rating": row.rating,
            "product_count": row.product_count,
            "description": f"Leading retailer of consumer goods",  # Placeholder
            "verified": True,  # Placeholder
            "is_featured": row.shop_id in [1, 2, 3],  # Placeholder logic for featured retailers
            "headquarters": "Colombo, Sri Lanka",  # Placeholder
            "founded_year": 2015,  # Placeholder
            "contact": {
                "email": f"info@{row.shop_name.lower().replace(' ', '')}.lk",  # Placeholder
                "phone": row.contact_phone,
                "address": "123 Main St, Colombo 03, Sri Lanka"  # Placeholder
            }
        }
        
        response = {"retailer": retailer}
        
        # Cache the result for a medium duration
        cache_service.set(cache_key, response, ttl_seconds=CACHE_TTL_MEDIUM)
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to retrieve retailer details: {str(e)}"
        )


@router.get("/aggregate/stats", response_model=RetailerStatsResponse)
async def get_retailer_stats(
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Retrieve aggregate statistics about retailers.
    """
    # Cache key for retailer stats
    cache_key = "retailers:stats"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    # Query to get aggregate statistics about retailers
    query = f"""
    WITH retailer_stats AS (
        SELECT 
            COUNT(DISTINCT s.shop_id) as total_retailers,
            -- Placeholder for verified retailers count
            (SELECT COUNT(*) FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop`) * 0.7 as verified_retailers,
            COUNT(DISTINCT sp.shop_product_id) as total_products
        FROM 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s
        LEFT JOIN 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp ON s.shop_id = sp.shop_id
    )
    SELECT 
        total_retailers,
        CAST(verified_retailers AS INT64) as verified_retailers,
        total_products,
        4.5 as average_rating  -- Placeholder for average rating
    FROM 
        retailer_stats
    """
    
    try:
        query_job = bq_client.query(query)
        results = query_job.result()
        
        # Extract stats from query results
        row = next(iter(results), None)
        if not row:
            # Return default values if no data
            response = {
                "stats": {
                    "total_retailers": 0,
                    "verified_retailers": 0,
                    "total_products": 0,
                    "average_rating": 0.0
                }
            }
        else:
            response = {
                "stats": {
                    "total_retailers": row.total_retailers,
                    "verified_retailers": row.verified_retailers,
                    "total_products": row.total_products,
                    "average_rating": row.average_rating
                }
            }
        
        # Cache the result for a longer duration (stats don't change often)
        cache_service.set(cache_key, response, ttl_seconds=CACHE_TTL_LONG)
        
        return response
    
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to retrieve retailer stats: {str(e)}"
        )


@router.get("/{id}/products")
async def get_products_by_retailer(
    id: int = Path(..., ge=0, description="The ID of the retailer"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Number of products per page"),
    search: Optional[str] = Query(None, description="Search query for product name, brand, or description"),
    category: Optional[str] = Query(None, description="Filter by product category"),
    brand: Optional[str] = Query(None, description="Filter by product brand"),
    min_price: Optional[float] = Query(None, ge=0, description="Filter by minimum price"),
    max_price: Optional[float] = Query(None, ge=0, description="Filter by maximum price"),
    in_stock: Optional[bool] = Query(None, description="Filter by availability status"),
    has_discount: Optional[bool] = Query(None, description="Filter products with discounts"),
    sort: str = Query("newest", description="Sort by field: newest, price_asc, price_desc, name_asc, name_desc"),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Retrieve a paginated list of products from a specific retailer with advanced filtering and sorting.
    """
    # Cache key based on all query parameters
    cache_key = f"retailers:{id}:products:{page}:{limit}:{search}:{category}:{brand}:{min_price}:{max_price}:{in_stock}:{has_discount}:{sort}"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    # Map sort options to actual BigQuery ORDER BY clauses
    sort_options = {
        "newest": "fp.scraped_date DESC",
        "price_asc": "IF(ARRAY_LENGTH(pv.variants) > 0, pv.variants[OFFSET(0)].price, NULL) ASC",
        "price_desc": "IF(ARRAY_LENGTH(pv.variants) > 0, pv.variants[OFFSET(0)].price, NULL) DESC",
        "name_asc": "fp.name ASC",
        "name_desc": "fp.name DESC"
    }
    
    # Use default sort if invalid sort option provided
    order_by_clause = sort_options.get(sort, sort_options["newest"])
    
    # Build WHERE clauses for filtering
    where_clauses = ["s.shop_id = @shop_id"]
    query_params = [bigquery.ScalarQueryParameter("shop_id", "INTEGER", id)]
    
    # Add search filter if provided
    if search:
        where_clauses.append("(LOWER(sp.product_title_native) LIKE LOWER(@search) OR LOWER(IFNULL(sp.brand_native, '')) LIKE LOWER(@search))")
        query_params.append(bigquery.ScalarQueryParameter("search", "STRING", f"%{search}%"))
    
    # Add category filter if provided
    if category:
        where_clauses.append("LOWER(c.category_name) LIKE LOWER(@category)")
        query_params.append(bigquery.ScalarQueryParameter("category", "STRING", f"%{category}%"))
    
    # Add brand filter if provided
    if brand:
        where_clauses.append("LOWER(sp.brand_native) LIKE LOWER(@brand)")
        query_params.append(bigquery.ScalarQueryParameter("brand", "STRING", f"%{brand}%"))
    
    # Add price range filters if provided
    if min_price is not None:
        where_clauses.append("fp.current_price >= @min_price")
        query_params.append(bigquery.ScalarQueryParameter("min_price", "FLOAT", min_price))
    
    if max_price is not None:
        where_clauses.append("fp.current_price <= @max_price")
        query_params.append(bigquery.ScalarQueryParameter("max_price", "FLOAT", max_price))
    
    # Add in-stock filter if provided
    if in_stock is not None:
        where_clauses.append("fp.is_available = @in_stock")
        query_params.append(bigquery.ScalarQueryParameter("in_stock", "BOOL", in_stock))
    
    # Add discount filter if provided
    if has_discount is not None and has_discount:
        where_clauses.append("(fp.original_price > fp.current_price AND fp.original_price IS NOT NULL)")
    
    # Join all WHERE clauses
    where_clause = " AND ".join(where_clauses)
    
    # Calculate pagination parameters
    offset = (page - 1) * limit
    
    # Build the optimized query with pagination and total count
    query = f"""
    WITH filtered_products AS (
        SELECT 
            sp.shop_product_id,
            sp.shop_id,
            sp.product_title_native AS name,
            sp.brand_native AS brand,
            c.category_name AS category,
            c.category_id,
            fp.current_price AS price,
            fp.original_price,
            fp.is_available,
            v.variant_id,
            v.variant_title,
            sp.product_url,
            sp.scraped_date,
            s.shop_name AS retailer_name,
            s.contact_phone AS retailer_phone,
            s.contact_whatsapp AS retailer_whatsapp,
            -- Calculate discount percentage
            CASE 
                WHEN fp.original_price IS NOT NULL AND fp.original_price > fp.current_price 
                THEN CAST(ROUND((fp.original_price - fp.current_price) / fp.original_price * 100) AS INT64)
                ELSE NULL 
            END AS discount
        FROM 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
        JOIN
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON sp.shop_id = s.shop_id
        LEFT JOIN 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimVariant` v ON sp.shop_product_id = v.shop_product_id
        LEFT JOIN 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProductPrice` fp ON v.variant_id = fp.variant_id
        LEFT JOIN 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
        WHERE 
            {where_clause}
    ),
    total_count AS (
        SELECT COUNT(DISTINCT shop_product_id) AS total FROM filtered_products
    ),
    product_images AS (
        SELECT 
            pi.shop_product_id,
            ARRAY_AGG(pi.image_url ORDER BY pi.sort_order) AS images
        FROM 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimProductImage` pi
        JOIN 
            filtered_products fp ON pi.shop_product_id = fp.shop_product_id
        GROUP BY 
            pi.shop_product_id
    ),
    product_variants AS (
        SELECT 
            shop_product_id,
                ARRAY_AGG(STRUCT(
                    variant_id,
                    variant_title AS title,
                    price,
                    original_price,
                    is_available,
                    discount
                ) ORDER BY price) AS variants
        FROM 
            filtered_products
        GROUP BY 
            shop_product_id
    )
    SELECT 
        fp.*,
        pi.images,
        pv.variants,
        tc.total AS total_count
    FROM 
        (SELECT DISTINCT 
            shop_product_id, shop_id, name, brand, category, category_id, 
            product_url, retailer_name, retailer_phone, retailer_whatsapp,
            scraped_date
         FROM filtered_products) fp
    LEFT JOIN 
        product_images pi ON fp.shop_product_id = pi.shop_product_id
    LEFT JOIN 
        product_variants pv ON fp.shop_product_id = pv.shop_product_id,
    total_count tc
    ORDER BY 
        {order_by_clause}
    LIMIT {limit}
    OFFSET {offset}
    """
    
    try:
        # Configure query with parameters
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        
        # Execute query
        query_job = bq_client.query(query, job_config=job_config)
        results = query_job.result()
        
        # Extract products from query results
        products = []
        total_count = 0
        
        for row in results:
            # Set total_count from the first row (it will be the same for all rows)
            if total_count == 0:
                total_count = row.total_count
            
            # Get primary image or placeholder
            images = row.images or []
            primary_image = images[0] if images else None
            
            # Map product data to schema
            product = {
                "id": row.shop_product_id,
                "name": row.name,
                "brand": row.brand,
                "category": row.category or "Uncategorized",
                "retailer": row.retailer_name,
                "retailer_id": row.shop_id,
                "image": primary_image,
                "images": images,
                "description": "Feature-packed product with excellent quality",  # Placeholder
                "created_at": row.scraped_date.isoformat() if row.scraped_date else None,
                "updated_at": row.scraped_date.isoformat() if row.scraped_date else None,
                "specifications": {
                    # Placeholder specifications - would come from actual data in production
                    "key1": "value1",
                    "key2": "value2"
                }
            }
            
            # Add variant data if available
            if row.variants:
                default_variant = None
                for variant in row.variants:
                    if variant["is_available"]:
                        default_variant = variant
                        break

                if not default_variant and row.variants:
                    default_variant = row.variants[0]

                if default_variant:
                    product["price"] = default_variant["price"]
                    product["original_price"] = default_variant["original_price"]
                    product["discount"] = default_variant["discount"]
                    product["in_stock"] = default_variant["is_available"]
            
            products.append(product)
        
        # Calculate pagination metadata
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        
        response = {
            "products": products,
            "meta": {
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "limit": limit
            }
        }
        
        # Cache the result for a short duration (product data changes more frequently)
        cache_service.set(cache_key, response, ttl_seconds=CACHE_TTL_SHORT)
        
        return response
    
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to retrieve products: {str(e)}"
        )


@router.get("/{id}/categories", response_model=CategoriesResponse)
async def get_product_categories_by_retailer(
    id: int = Path(..., ge=0, description="The ID of the retailer"),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Retrieve a list of all product categories available from a specific retailer.
    """
    # Cache key based on retailer ID
    cache_key = f"retailers:{id}:categories"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    # Query to get categories with product counts for the specified retailer
    query = f"""
    SELECT 
        c.category_id AS id,
        c.category_name AS name,
        COUNT(DISTINCT sp.shop_product_id) AS product_count
    FROM 
        `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct` sp
    JOIN 
        `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON sp.predicted_master_category_id = c.category_id
    WHERE 
        sp.shop_id = @shop_id
    GROUP BY 
        c.category_id, c.category_name
    ORDER BY 
        product_count DESC, name ASC
    """
    
    try:
        # Configure query with shop_id parameter
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("shop_id", "INTEGER", id)
            ]
        )
        
        # Execute query
        query_job = bq_client.query(query, job_config=job_config)
        results = query_job.result()
        
        # Extract categories from query results
        categories = []
        
        for row in results:
            category = {
                "id": row.id,
                "name": row.name,
                "product_count": row.product_count
            }
            categories.append(category)
        
        response = {"categories": categories}
        
        # Cache the result for a medium duration (categories change less frequently)
        cache_service.set(cache_key, response, ttl_seconds=CACHE_TTL_MEDIUM)
        
        return response
    
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to retrieve categories: {str(e)}"
        )


@router.get("/{id}/brands", response_model=BrandsResponse)
async def get_product_brands_by_retailer(
    id: int = Path(..., ge=0, description="The ID of the retailer"),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Retrieve a list of all product brands available from a specific retailer.
    """
    # Cache key based on retailer ID
    cache_key = f"retailers:{id}:brands"
    
    # Try to get from cache first
    cached_data = cache_service.get(cache_key)
    if cached_data:
        return cached_data
    
    # Query to get brands with product counts for the specified retailer
    query = f"""
    WITH brand_info AS (
        SELECT 
            ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) AS brand_id,
            brand_native AS brand_name,
            COUNT(DISTINCT shop_product_id) AS product_count
        FROM 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShopProduct`
        WHERE 
            shop_id = @shop_id
            AND brand_native IS NOT NULL
            AND TRIM(brand_native) != ''
        GROUP BY 
            brand_native
    )
    SELECT 
        brand_id AS id,
        brand_name AS name,
        product_count
    FROM 
        brand_info
    ORDER BY 
        product_count DESC, name ASC
    """
    
    try:
        # Configure query with shop_id parameter
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("shop_id", "INTEGER", id)
            ]
        )
        
        # Execute query
        query_job = bq_client.query(query, job_config=job_config)
        results = query_job.result()
        
        # Extract brands from query results
        brands = []
        
        for row in results:
            brand = {
                "id": row.id,
                "name": row.name,
                "product_count": row.product_count
            }
            brands.append(brand)
        
        response = {"brands": brands}
        
        # Cache the result for a medium duration (brands change less frequently)
        cache_service.set(cache_key, response, ttl_seconds=CACHE_TTL_MEDIUM)
        
        return response
    
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to retrieve brands: {str(e)}"
        )