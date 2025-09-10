# New Arrivals API Documentation

This document provides comprehensive documentation for the New Arrivals API endpoints in the PricePulse backend system.

## Overview

The New Arrivals API allows users to browse and filter recently added products with advanced filtering capabilities including time range, stock status, category, retailer, and price range filtering.

## Base URL

```
http://localhost:8000/api/v1
```

## Endpoints

### 1. Get New Arrivals

Retrieves a paginated list of new arrivals with comprehensive filtering options.

```http
GET /api/v1/new-arrivals
```

#### Query Parameters

| Parameter     | Type    | Default    | Description                      | Validation                                                          |
| ------------- | ------- | ---------- | -------------------------------- | ------------------------------------------------------------------- |
| `timeRange`   | string  | `"30d"`    | Filter by time period            | `24h`, `7d`, `30d`, `3m`                                            |
| `category`    | string  | `null`     | Filter by product category       | Case-insensitive partial match                                      |
| `retailer`    | string  | `null`     | Filter by retailer/shop name     | Case-insensitive partial match                                      |
| `minPrice`    | float   | `null`     | Minimum price filter (inclusive) | ≥ 0                                                                 |
| `maxPrice`    | float   | `null`     | Maximum price filter (inclusive) | ≥ 0                                                                 |
| `sortBy`      | string  | `"newest"` | Sort order                       | `newest`, `oldest`, `price_low`, `price_high`, `name_az`, `name_za` |
| `inStockOnly` | boolean | `null`     | Stock status filter              | See Stock Filtering Logic below                                     |
| `limit`       | integer | `20`       | Items per page                   | 1-100                                                               |
| `page`        | integer | `1`        | Page number                      | ≥ 1                                                                 |

#### Time Range Filtering

The `timeRange` parameter filters products based on their `arrival_date` field:

- **`24h`**: Products added in the last 24 hours
- **`7d`**: Products added in the last 7 days
- **`30d`**: Products added in the last 30 days
- **`3m`**: Products added in the last 3 months (90 days)

The `arrival_date` field uses YYYYMMDD format (e.g., "20250826" for August 26, 2025).

#### Stock Filtering Logic

The `inStockOnly` parameter controls which products are returned based on their availability:

| Value   | Behavior                               | SQL Filter Applied        |
| ------- | -------------------------------------- | ------------------------- |
| `true`  | Returns **ONLY** in-stock products     | `fp.is_available = TRUE`  |
| `false` | Returns **ONLY** out-of-stock products | `fp.is_available = FALSE` |
| `null`  | Returns **ALL** products               | No stock filter applied   |

#### Response Format

```json
{
  "items": [
    {
      "variant_id": 14,
      "shop_product_id": 10047,
      "product_title": "ASUS Zenbook Duo (2025)",
      "brand": "ASUS",
      "category_name": "Laptops",
      "variant_title": "Intel Core Ultra 7 / 16GB RAM / 1TB SSD",
      "shop_name": "Hanotek",
      "current_price": 640000.0,
      "original_price": 670000.0,
      "image_url": "https://www.laptop.lk/wp-content/uploads/2021/03/hanotek.lk/product/1002",
      "product_url": "https://www.laptop.lk/product/asus-zenbook-duo-ux8406ma",
      "is_available": true,
      "arrival_date": "20250826",
      "days_since_arrival": 0
    }
  ],
  "total": 4,
  "page": 1,
  "limit": 20,
  "has_next": false
}
```

#### Response Fields

| Field                | Type    | Description                                 |
| -------------------- | ------- | ------------------------------------------- |
| `variant_id`         | integer | Unique variant identifier                   |
| `shop_product_id`    | integer | Product identifier in the shop              |
| `product_title`      | string  | Product name/title                          |
| `brand`              | string  | Product brand (defaults to "Unknown Brand") |
| `category_name`      | string  | Product category                            |
| `variant_title`      | string  | Variant specifications                      |
| `shop_name`          | string  | Retailer/shop name                          |
| `current_price`      | float   | Current price                               |
| `original_price`     | float   | Original price (may be null)                |
| `image_url`          | string  | Product image URL                           |
| `product_url`        | string  | Product page URL                            |
| `is_available`       | boolean | Stock availability status                   |
| `arrival_date`       | string  | Date added (YYYYMMDD format)                |
| `days_since_arrival` | integer | Days since product was added                |

#### Example Requests

**Get newest products from last 7 days:**

```bash
curl "http://localhost:8000/api/v1/new-arrivals?timeRange=7d&sortBy=newest&limit=10"
```

**Get only in-stock laptops under 500,000:**

```bash
curl "http://localhost:8000/api/v1/new-arrivals?category=Laptops&inStockOnly=true&maxPrice=500000"
```

**Get only out-of-stock products:**

```bash
curl "http://localhost:8000/api/v1/new-arrivals?inStockOnly=false"
```

**Get products from specific retailer with pagination:**

```bash
curl "http://localhost:8000/api/v1/new-arrivals?retailer=Hanotek&page=2&limit=5"
```

### 2. Get New Arrivals Statistics

Returns aggregated statistics for new arrivals with the same filtering options.

```http
GET /api/v1/new-arrivals/stats
```

#### Query Parameters

Uses the same parameters as the main endpoint.

#### Response Format

```json
{
  "total_new_arrivals": 150,
  "average_price": 425000.5,
  "in_stock_count": 120,
  "category_count": 8
}
```

#### Response Fields

| Field                | Type    | Description                               |
| -------------------- | ------- | ----------------------------------------- |
| `total_new_arrivals` | integer | Total number of products matching filters |
| `average_price`      | float   | Average price of filtered products        |
| `in_stock_count`     | integer | Number of in-stock products               |
| `category_count`     | integer | Number of unique categories               |

### 3. Debug Database Stock Distribution

Development endpoint to analyze stock distribution in the database.

```http
GET /api/v1/new-arrivals/check-database-stock
```

#### Response Format

```json
{
  "database_stock_distribution": [
    {
      "is_available": true,
      "count": 1250,
      "status_description": "Available (In Stock)"
    },
    {
      "is_available": false,
      "count": 350,
      "status_description": "Not Available (Out of Stock)"
    }
  ],
  "out_of_stock_samples": [...],
  "in_stock_samples": [...],
  "analysis": {
    "has_out_of_stock_items": true,
    "total_distribution_categories": 2,
    "recommendation": "Database has both in-stock and out-of-stock items..."
  }
}
```

### 4. Debug General Information

Development endpoint for database table information and sample data.

```http
GET /api/v1/new-arrivals/debug
```

## Error Handling

### Common Error Responses

#### 400 Bad Request

```json
{
  "detail": "Validation error: limit must be between 1 and 100"
}
```

#### 500 Internal Server Error

```json
{
  "detail": "BigQuery error: [specific error message]"
}
```

### Empty Results

When no products match the specified criteria, the API returns an empty list with 200 OK status:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "limit": 20,
  "has_next": false
}
```

This is normal behavior for:

- Time ranges with no recent data (e.g., `24h` or `7d`)
- Out-of-stock filtering when database has no out-of-stock items
- Very specific filter combinations

## Database Schema

The API queries the following BigQuery tables:

- **`FactProductPrice`**: Main price and availability data
- **`DimVariant`**: Product variant information
- **`DimShopProduct`**: Product details and metadata
- **`DimCategory`**: Category information
- **`DimShop`**: Retailer information
- **`DimProductImage`**: Product images

## Performance Considerations

1. **Pagination**: Use appropriate `limit` values (recommended: 10-50)
2. **Time Filtering**: Shorter time ranges (`24h`, `7d`) perform better than longer ones
3. **Caching**: Results may be cached; expect slight delays for real-time updates
4. **Index Usage**: Category and retailer filters use optimized indexes

## Rate Limiting

- No specific rate limits currently implemented
- Recommend reasonable request frequency for production use

## Testing

### Test Script

A comprehensive test suite is available:

```bash
python tests/test_new_arrivals.py
```

### Manual Testing Examples

**Test basic functionality:**

```bash
curl -X GET "http://localhost:8000/api/v1/new-arrivals?limit=5" | jq '.'
```

**Test stock filtering:**

```bash
# Only in-stock items
curl -X GET "http://localhost:8000/api/v1/new-arrivals?inStockOnly=true&limit=10"

# Only out-of-stock items
curl -X GET "http://localhost:8000/api/v1/new-arrivals?inStockOnly=false&limit=10"

# All items
curl -X GET "http://localhost:8000/api/v1/new-arrivals?limit=10"
```

**Test time filtering:**

```bash
# Last 24 hours
curl -X GET "http://localhost:8000/api/v1/new-arrivals?timeRange=24h"

# Last 7 days
curl -X GET "http://localhost:8000/api/v1/new-arrivals?timeRange=7d"
```

**Test combined filters:**

```bash
curl -X GET "http://localhost:8000/api/v1/new-arrivals?timeRange=30d&category=Laptops&inStockOnly=true&sortBy=price_low&limit=20"
```

## Integration Notes

### Frontend Integration

1. **Loading States**: Handle empty results gracefully
2. **Error Handling**: Display user-friendly messages for errors
3. **Pagination**: Implement proper pagination controls
4. **Real-time Updates**: Consider periodic refresh for stock status

### Data Pipeline

1. **Data Updates**: Product data is updated via ETL pipeline
2. **Date Format**: Arrival dates use YYYYMMDD format consistently
3. **Stock Status**: `is_available` field reflects real-time inventory status

## Changelog

### Version 1.0 (Current)

- Initial implementation with full filtering capabilities
- Time range filtering with YYYYMMDD date support
- Corrected stock filtering logic (true/false/null)
- Comprehensive error handling for empty results
- Debug endpoints for development support

---

_This documentation is automatically updated with code changes. Last updated: September 2025_
