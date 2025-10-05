#!/usr/bin/env python3

import os

file_path = 'app/api/v1/retailers.py'

with open(file_path, 'r') as file:
    content = file.read()

# First, let's fix the sort_options mapping
# The issue is likely that the ORDER BY clause cannot directly access array elements in the way we're trying
updated_content = content.replace(
    '    # Map sort options to actual BigQuery ORDER BY clauses - simpler approach for debugging\n'
    '    sort_options = {\n'
    '        "newest": "fp.scraped_date DESC",\n'
    '        "price_asc": "1 ASC",  # Temporary placeholder to debug\n'
    '        "price_desc": "1 DESC", # Temporary placeholder to debug\n'
    '        "name_asc": "fp.name ASC",\n'
    '        "name_desc": "fp.name DESC"\n'
    '    }',

    '    # Map sort options to actual BigQuery ORDER BY clauses\n'
    '    sort_options = {\n'
    '        "newest": "fp.scraped_date DESC",\n'
    '        "price_asc": "MIN_PRICE ASC",  # Use calculated MIN_PRICE field\n'
    '        "price_desc": "MIN_PRICE DESC", # Use calculated MIN_PRICE field\n'
    '        "name_asc": "fp.name ASC",\n'
    '        "name_desc": "fp.name DESC"\n'
    '    }'
)

# Now let's also modify the main product query to include a MIN_PRICE calculation
# in the final SELECT that we can use for sorting
updated_content = updated_content.replace(
    'FROM \n'
    '        (SELECT DISTINCT \n'
    '            shop_product_id, shop_id, name, brand, category, category_id, \n'
    '            product_url, retailer_name, retailer_phone, retailer_whatsapp,\n'
    '            scraped_date\n'
    '         FROM filtered_products) fp',

    'FROM \n'
    '        (SELECT DISTINCT \n'
    '            shop_product_id, shop_id, name, brand, category, category_id, \n'
    '            product_url, retailer_name, retailer_phone, retailer_whatsapp,\n'
    '            scraped_date,\n'
    '            MIN(price) OVER (PARTITION BY shop_product_id) AS MIN_PRICE\n'
    '         FROM filtered_products) fp'
)

with open(file_path, 'w') as file:
    file.write(updated_content)

print(f"Updated {file_path} with better price sorting approach")
