# Price Drops API Documentation

This document outlines the API endpoints available for the Price Drops feature in the PricePulse backend.

## Endpoints

### Get Price Drops

Retrieves products that have experienced price drops based on specified filters.

```
GET /api/v1/price-drops
```

#### Query Parameters

| Parameter    | Type   | Default               | Description                                                                           |
| ------------ | ------ | --------------------- | ------------------------------------------------------------------------------------- |
| time_range   | string | "7d"                  | Time range for price drops. Options: "24h", "7d", "30d", "90d"                        |
| category     | string | null                  | Filter by category ID or name                                                         |
| retailer     | string | null                  | Filter by retailer ID or name                                                         |
| min_discount | number | 5.0                   | Minimum discount percentage (0-100)                                                   |
| sort_by      | string | "discount_percentage" | Sort order. Options: "discount_percentage", "discount_amount", "most_recent", "price" |
| page         | number | 1                     | Page number for pagination                                                            |
| limit        | number | 20                    | Number of results per page (max 100)                                                  |

#### Response

```json
{
  "price_drops": [
    {
      "id": 123,
      "name": "Product Name",
      "brand": "Brand Name",
      "category": "Category Name",
      "current_price": 89.99,
      "previous_price": 99.99,
      "price_change": -10.0,
      "percentage_change": -10.0,
      "retailer": "Retailer Name",
      "retailer_id": 456,
      "image": "https://example.com/image.jpg",
      "change_date": "2025-10-10",
      "in_stock": true
    }
  ],
  "total_count": 100,
  "next_page": 2
}
```

### Get Price Drops Statistics

Retrieves statistics about price drops.

```
GET /api/v1/price-drops/stats
```

#### Query Parameters

| Parameter  | Type   | Default | Description                                                   |
| ---------- | ------ | ------- | ------------------------------------------------------------- |
| time_range | string | "7d"    | Time range for statistics. Options: "24h", "7d", "30d", "90d" |
| category   | string | null    | Filter by category ID or name                                 |
| retailer   | string | null    | Filter by retailer ID or name                                 |

#### Response

```json
{
  "stats": {
    "total_drops": 1250,
    "average_discount_percentage": 15.75,
    "retailers_with_drops": 42,
    "categories_with_drops": 28,
    "largest_drop_percentage": 70.0,
    "total_savings": 125000.0,
    "drops_last_24h": 150,
    "drops_last_7d": 1250
  }
}
```

## Implementation Details

- The API uses the BigQuery database to query pricing history
- Results are cached for performance (15 minutes for price drops, 1 hour for statistics)
- The async query service implements timeouts to prevent long-running queries
- Appropriate error handling provides clear messages when something goes wrong

## Example Usage

### curl

```bash
# Get price drops with a minimum discount of 20%
curl -X GET "http://localhost:9000/api/v1/price-drops?min_discount=20&sort_by=discount_percentage"

# Get statistics for the last 24 hours
curl -X GET "http://localhost:9000/api/v1/price-drops/stats?time_range=24h"
```

### JavaScript (Fetch API)

```javascript
// Get price drops for a specific category
fetch("http://localhost:9000/api/v1/price-drops?category=Smartphones&limit=10")
  .then((response) => response.json())
  .then((data) => console.log(data))
  .catch((error) => console.error("Error:", error));

// Get price drops statistics
fetch("http://localhost:9000/api/v1/price-drops/stats")
  .then((response) => response.json())
  .then((data) => console.log(data.stats))
  .catch((error) => console.error("Error:", error));
```
