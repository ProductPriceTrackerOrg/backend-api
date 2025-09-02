# Category Browsing APIs

This document provides an overview of the category browsing APIs implemented in the PricePulse backend.

## Implemented Endpoints

### 1. Get All Categories

```http
GET /api/v1/categories
```

This endpoint retrieves all product categories with optional subcategories and product counts.

**Query Parameters:**

- `include_subcategories` (optional): Include child categories (default: true)
- `include_counts` (optional): Include product counts (default: true)

**Response:**

```json
{
  "categories": [
    {
      "category_id": 1,
      "name": "Smartphones",
      "description": "Smartphones and accessories",
      "product_count": 450000,
      "parent_category_id": null,
      "subcategories": [
        {
          "category_id": 11,
          "name": "Android Phones",
          "product_count": 320000,
          "parent_category_id": 1
        },
        {
          "category_id": 12,
          "name": "iPhones",
          "product_count": 130000,
          "parent_category_id": 1
        }
      ],
      "trending_score": 95,
      "icon": "smartphone",
      "color": "blue"
    }
  ],
  "total_categories": 8,
  "total_products": 2500000
}
```

### 2. Get Category Products

```http
GET /api/v1/categories/{category_id}/products
```

This endpoint retrieves products for a specific category with filtering and pagination.

**Path Parameters:**

- `category_id`: Category ID

**Query Parameters:**

- `page` (optional): Page number (default: 1)
- `limit` (optional): Items per page (default: 20)
- `sort` (optional): "price_asc", "price_desc", "popularity", "newest" (default: "popularity")
- `min_price` (optional): Minimum price filter
- `max_price` (optional): Maximum price filter
- `retailer` (optional): Retailer filter
- `in_stock` (optional): Stock status filter

**Response:**

```json
{
  "category": {
    "category_id": 1,
    "name": "Smartphones",
    "description": "Mobile phones and accessories",
    "parent_category": null
  },
  "products": [
    {
      "id": 1,
      "name": "iPhone 15 Pro Max",
      "brand": "Apple",
      "price": 1299.99,
      "original_price": 1399.99,
      "discount": 7,
      "retailer": "MobileWorld",
      "retailer_id": 1,
      "in_stock": true,
      "image": "https://example.com/image.jpg",
      "popularity_score": 95
    }
  ],
  "pagination": {
    "current_page": 1,
    "total_pages": 150,
    "total_items": 3000,
    "items_per_page": 20
  },
  "filters": {
    "brands": [
      { "name": "Apple", "count": 500 },
      { "name": "Samsung", "count": 800 }
    ],
    "retailers": [{ "retailer_id": 1, "name": "MobileWorld", "count": 1200 }],
    "price_ranges": [
      { "range": "0-500", "count": 800 },
      { "range": "500-1000", "count": 1200 }
    ]
  }
}
```

## Testing

A test script has been provided in `tests/test_categories_api.py`. You can run this script to test the implemented APIs:

```bash
python tests/test_categories_api.py
```

Make sure the backend server is running before executing the test script.

## Implementation Details

The category browsing APIs use BigQuery as the data source, with caching implemented to improve performance. The implementation follows the architecture described in `backend.md` and uses the BigQuery schema defined in `schema.txt`.

- **Caching**: Responses are cached to reduce database load and improve response times.
- **Filtering**: The category products endpoint supports various filters such as price range, retailer, and stock status.
- **Pagination**: Results are paginated to handle large datasets efficiently.
- **Sorting**: Products can be sorted by price (ascending or descending), popularity, or recency.

## Schema and Structure

- `app/schemas/category.py`: Contains Pydantic models for API responses
- `app/api/v1/categories.py`: Contains the API routes for category browsing
