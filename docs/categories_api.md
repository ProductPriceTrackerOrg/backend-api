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

## Testing

A test script has been provided in `tests/test_categories_api.py`. You can run this script to test the implemented APIs:

```bash
python tests/categories_api.py
```
