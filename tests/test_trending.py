"""
Test cases for the trending endpoint
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture
def mock_bigquery_result():
    """
    Mock the results returned by BigQuery for trending queries
    """
    # Create mock products
    mock_products = [
        {
            "id": 1,
            "name": "iPhone 15 Pro Max",
            "brand": "Apple",
            "category": "Smartphones",
            "variant_id": 101,
            "variant_title": "128GB Space Black",
            "price": 1299.99,
            "original_price": 1399.99,
            "discount": 7,
            "retailer": "MobileWorld",
            "retailer_id": 1,
            "in_stock": True,
            "image": "https://example.com/image.jpg",
            "trend_score": 98,
            "search_volume": "+245%",
            "price_change": -100.00,
            "is_trending": True
        },
        {
            "id": 2,
            "name": "Samsung Galaxy S25",
            "brand": "Samsung",
            "category": "Smartphones",
            "variant_id": 102,
            "variant_title": "256GB Phantom Black",
            "price": 999.99,
            "original_price": 1099.99,
            "discount": 9,
            "retailer": "TechStore",
            "retailer_id": 2,
            "in_stock": True,
            "image": "https://example.com/image2.jpg",
            "trend_score": 85,
            "search_volume": "+190%",
            "price_change": -90.00,
            "is_trending": True
        }
    ]

    # Create mock products for launches
    mock_launches = [
        {
            "id": 3,
            "name": "Google Pixel 9",
            "brand": "Google",
            "category": "Smartphones",
            "price": 899.99,
            "retailer": "GoogleStore",
            "retailer_id": 3,
            "in_stock": True,
            "image": "https://example.com/pixel.jpg",
            "launch_date": "2025-08-15",
            "pre_orders": 12500,
            "rating": 4.8,
            "is_new": True
        }
    ]

    return {
        "trends": mock_products,
        "launches": mock_launches
    }


@patch('app.api.deps.get_bigquery_client')
def test_get_trending_products(mock_get_bigquery_client, mock_bigquery_result):
    """Test the trending products endpoint with default parameters"""
    
    # Setup mock BigQuery client and results
    mock_client = MagicMock()
    mock_get_bigquery_client.return_value = mock_client
    
    # Mock the query results
    mock_results = MagicMock()
    mock_results.result.return_value = mock_bigquery_result['trends']
    
    # Configure mock query call
    mock_client.query.return_value = mock_results
    
    # Test the endpoint
    response = client.get("/api/v1/trending?type=trends")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check response structure
    assert "products" in data
    assert "stats" in data
    
    # Check products data
    assert len(data["products"]) == 2
    product = data["products"][0]
    assert product["id"] == 1
    assert product["name"] == "iPhone 15 Pro Max"
    assert product["brand"] == "Apple"
    assert product["price"] == 1299.99
    assert product["is_trending"] == True
    
    # Check stats
    assert "trending_searches" in data["stats"]
    assert "accuracy_rate" in data["stats"]
    assert "update_frequency" in data["stats"]


@patch('app.api.deps.get_bigquery_client')
def test_get_new_launches(mock_get_bigquery_client, mock_bigquery_result):
    """Test the new product launches endpoint"""
    
    # Setup mock BigQuery client and results
    mock_client = MagicMock()
    mock_get_bigquery_client.return_value = mock_client
    
    # Mock the query results
    mock_results = MagicMock()
    mock_results.result.return_value = mock_bigquery_result['launches']
    
    # Configure mock query call
    mock_client.query.return_value = mock_results
    
    # Test the endpoint
    response = client.get("/api/v1/trending?type=launches")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check response structure
    assert "products" in data
    assert "stats" in data
    
    # Check products data
    assert len(data["products"]) == 1
    product = data["products"][0]
    assert product["id"] == 3
    assert product["name"] == "Google Pixel 9"
    assert product["brand"] == "Google"
    assert product["is_new"] == True
    
    # Check stats
    assert "new_launches" in data["stats"]
    assert "update_frequency" in data["stats"]
    assert "tracking_type" in data["stats"]
