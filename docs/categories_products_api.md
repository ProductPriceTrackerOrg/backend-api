# Categories API Documentation

## Category Products Endpoint

**Endpoint:** `/api/v1/categories/{category_slug}/products`

**Method:** `GET`

**Description:** Returns paginated products for a specific category, with filtering and sorting options.

### URL Parameters

- `category_slug` (required): The category slug, e.g., "smartphones", "laptops"

### Query Parameters

- `page` (optional, default: 1): Page number for pagination
- `limit` (optional, default: 20, max: 100): Number of products per page
- `retailer` (optional): Filter by retailer name
- `sort_by` (optional, default: "price_asc"): Sorting method
  - Valid values: "price_asc", "price_desc", "name_asc", "name_desc"
- `in_stock_only` (optional, default: false): Filter to only show products that are in stock
- `min_price` (optional): Minimum price filter
- `max_price` (optional): Maximum price filter
- `brand` (optional): Filter by brand name

### Response Format

```json
{
  "category": {
    "category_id": 123,
    "name": "Smartphones",
    "description": "Smartphones and accessories",
    "icon": "smartphone",
    "color": "blue",
    "product_count": 534
  },
  "products": [
    {
      "id": 1234,
      "name": "iPhone 13 Pro",
      "brand": "Apple",
      "price": 999.99,
      "original_price": 1099.99,
      "discount": 9,
      "retailer": "Apple Store",
      "retailer_id": 42,
      "in_stock": true,
      "image": "https://example.com/iphone13pro.jpg"
    }
    // ... more products
  ],
  "pagination": {
    "current_page": 1,
    "total_pages": 27,
    "total_items": 534,
    "items_per_page": 20
  },
  "filters": {
    "brands": [
      {
        "name": "Apple",
        "count": 125
      }
      // ... more brands
    ],
    "retailers": [
      {
        "retailer_id": 42,
        "name": "Apple Store",
        "count": 75
      }
      // ... more retailers
    ],
    "price_ranges": [
      {
        "range": "$1,000 - $5,000",
        "count": 250
      }
      // ... more price ranges
    ]
  }
}
```

### Error Responses

**Category Not Found (404)**

```json
{
  "detail": "Category with slug 'nonexistent-category' not found"
}
```

**Server Error (500)**

```json
{
  "detail": "Failed to retrieve products for category 'smartphones'"
}
```

## Implementation Notes

- This endpoint utilizes the BigQuery database to fetch category products efficiently
- Results are cached for 15 minutes to improve performance
- The endpoint includes support for filtering by various criteria
- Price filters can be used to narrow down products within specific price ranges
- The response includes helpful filter options based on the available products in the category
- Products are returned with the highest-price variant as the representative for each product
