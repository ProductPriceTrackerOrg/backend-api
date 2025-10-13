import json

# This is what the SQL query looks like after fp.* and the joins
result_structure = {
    "shop_product_id": 12345,
    "shop_id": 1,
    "name": "Product Name",
    "brand": "Brand Name",
    "category": "Category",
    "category_id": 42,
    "product_url": "http://example.com/product",
    "retailer_name": "Retailer",
    "retailer_phone": "123456789",
    "retailer_whatsapp": "987654321",
    "scraped_date": "2025-10-01",
    "images": ["image1.jpg", "image2.jpg"],
    "variants": [
        {
            "variant_id": 101,
            "title": "Variant 1",
            "price": 19.99,
            "original_price": 29.99,
            "is_available": True,
            "discount": 33
        },
        {
            "variant_id": 102,
            "title": "Variant 2",
            "price": 24.99,
            "original_price": 34.99,
            "is_available": False,
            "discount": 28
        }
    ],
    "total_count": 150
}

print("SQL query result structure:")
print(json.dumps(result_structure, indent=2))

print("\nProper column references for ORDER BY:")
print("- newest: fp.scraped_date DESC")
print("- price_asc: Cannot use simple column reference, need a different approach")
print("- name_asc: fp.name ASC")
print("- name_desc: fp.name DESC")

print("\nThe issue with price sorting:")
print("- The price is inside the variants array, so we can't reference it directly")
print("- We need to find a valid BigQuery approach for this")
