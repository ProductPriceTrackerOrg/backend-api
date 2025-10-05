# Debugging script to print SQL query structure
query = """
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
            DimShopProduct sp
        JOIN
            DimShop s ON sp.shop_id = s.shop_id
        LEFT JOIN 
            DimVariant v ON sp.shop_product_id = v.shop_product_id
        LEFT JOIN 
            FactProductPrice fp ON v.variant_id = fp.variant_id
        LEFT JOIN 
            DimCategory c ON sp.predicted_master_category_id = c.category_id
        WHERE 
            s.shop_id = 1
    ),
    total_count AS (
        SELECT COUNT(DISTINCT shop_product_id) AS total FROM filtered_products
    ),
    product_images AS (
        SELECT 
            pi.shop_product_id,
            ARRAY_AGG(pi.image_url ORDER BY pi.sort_order) AS images
        FROM 
            DimProductImage pi
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
        name ASC
    LIMIT 10
    OFFSET 0
"""

# Print line numbers for debugging
lines = query.split('\n')
for i, line in enumerate(lines):
    print(f"{i+1}: {line}")

# Try to identify position [86:9]
if len(lines) >= 86:
    print("\nLine 86:")
    print(lines[85])
    print(" " * 8 + "^") # Point to position 9
