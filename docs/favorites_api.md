# User Favorites API Documentation

## Overview

The User Favorites API allows authenticated users to retrieve their list of favorited products. This document outlines how to integrate with the favorites endpoint in the frontend application.

## Authentication Requirements

All favorites endpoints require authentication. The API uses JWT token authentication via the Authorization header:

```
Authorization: Bearer <token>
```

Where `<token>` is the JWT token obtained during user login.

## Endpoints

### 1. Get User Favorites

**Endpoint:** `GET /api/v1/favorites/`

**Description:** Retrieves all products that the current authenticated user has added to their favorites.

**Authentication:** Required

**Request:** No request body or parameters needed. The user is identified by their authentication token.

**Response:**

```json
{
  "favorites": [
    {
      "id": 240898780,
      "name": "HK10 Pro Max plus Gen7 Series 10 Smart Watch 2025",
      "brand": "HK",
      "category": "Wearables",
      "price": 12999.99,
      "original_price": 15999.99,
      "image": "https://example.com/image.webp",
      "retailer": "appleme",
      "retailer_phone": "+94112000000",
      "retailer_whatsapp": "+94712000000",
      "discount": 19,
      "is_available": true,
      "variant_id": 12345678
    }
    // Additional favorite products...
  ]
}
```

**Example Usage in React:**

```typescript
import { useEffect, useState } from "react";
import axios from "axios";

interface FavoriteProduct {
  id: number;
  name: string;
  brand?: string;
  category?: string;
  price: number;
  original_price?: number;
  image?: string;
  retailer: string;
  retailer_phone?: string;
  retailer_whatsapp?: string;
  discount?: number;
  is_available: boolean;
  variant_id: number;
}

const UserFavorites = () => {
  const [favorites, setFavorites] = useState<FavoriteProduct[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchFavorites = async () => {
      try {
        setIsLoading(true);
        // Get the authentication token from your auth context or storage
        const token = localStorage.getItem("authToken");

        const response = await axios.get("/api/v1/favorites/", {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        setFavorites(response.data.favorites);
        setError(null);
      } catch (err) {
        console.error("Failed to fetch favorites:", err);
        setError(
          "Failed to load your favorite products. Please try again later."
        );
      } finally {
        setIsLoading(false);
      }
    };

    fetchFavorites();
  }, []);

  if (isLoading) {
    return <div>Loading your favorites...</div>;
  }

  if (error) {
    return <div className="error-message">{error}</div>;
  }

  if (favorites.length === 0) {
    return <div>You haven't added any products to your favorites yet.</div>;
  }

  return (
    <div className="favorites-container">
      <h1>Your Favorites</h1>
      <div className="favorites-grid">
        {favorites.map((product) => (
          <div key={product.variant_id} className="favorite-product-card">
            <img src={product.image || "/placeholder.png"} alt={product.name} />
            <h3>{product.name}</h3>
            <p className="retailer">{product.retailer}</p>
            <div className="price-container">
              <span className="current-price">${product.price.toFixed(2)}</span>
              {product.original_price &&
                product.original_price > product.price && (
                  <span className="original-price">
                    ${product.original_price.toFixed(2)}
                  </span>
                )}
              {product.discount && product.discount > 0 && (
                <span className="discount-badge">-{product.discount}%</span>
              )}
            </div>
            <a href={`/product/${product.id}`} className="view-product-btn">
              View Product
            </a>
          </div>
        ))}
      </div>
    </div>
  );
};

export default UserFavorites;
```

## Error Handling

| Status Code | Description           | Possible Cause                                                |
| ----------- | --------------------- | ------------------------------------------------------------- |
| 401         | Unauthorized          | The user is not authenticated or the token is invalid/expired |
| 500         | Internal Server Error | Server-side error during processing                           |

## Caching

User favorites are cached for 5 minutes to improve performance. If a user adds or removes favorites, they might need to refresh or wait up to 5 minutes to see the changes reflected.

## Best Practices

1. **Handle Authentication Errors**: Always implement proper error handling for cases when a user's authentication token expires.

2. **Loading States**: Implement loading states in your UI to improve user experience while favorites are being fetched.

3. **Empty States**: Design appropriate empty states for when a user has no favorites.

4. **Responsive Design**: Ensure your favorites UI is responsive to accommodate various screen sizes.

5. **Deep Linking**: When a user clicks on a favorited product, link directly to that product's detail page.
