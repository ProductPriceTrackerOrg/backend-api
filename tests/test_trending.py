"""
Test the trending products and new launches API endpoints
"""

import requests
import json
from pprint import pprint

# Base URL
BASE_URL = "http://localhost:9000/api/v1"

def test_trending_products():
    """Test the trending products endpoint"""
    print("\n=== Testing Trending Products API ===")
    
    # Test with default parameters
    url = f"{BASE_URL}/trending?type=trends"
    print(f"Sending GET request to {url}")
    
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print("Success! Status code:", response.status_code)
        print(f"Total trending products: {len(data['products'])}")
        
        # Display the trending products structure
        print("\nTrending products structure:")
        for idx, product in enumerate(data['products'][:3], 1):  # Show first 3 products
            print(f"\n{idx}. {product['name']}")
            print(f"   Brand: {product['brand']}")
            print(f"   Category: {product['category']}")
            print(f"   Price: ${product['price']}")
            print(f"   Discount: {product.get('discount', '0')}%")
            print(f"   Trend Score: {product.get('trend_score', 'N/A')}")
            
        # Display stats
        print("\nStats:")
        print(f"   Trending Searches: {data['stats'].get('trending_searches', 'N/A')}")
        print(f"   Accuracy Rate: {data['stats'].get('accuracy_rate', 'N/A')}")
        print(f"   Update Frequency: {data['stats'].get('update_frequency', 'N/A')}")
    else:
        print("Failed! Status code:", response.status_code)
        print("Response:", response.text)
    
    # Test with specific category
    url = f"{BASE_URL}/trending?type=trends&category=Laptops"
    print(f"\nSending GET request to {url}")
    
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print("Success! Status code:", response.status_code)
        print(f"Total trending products in Laptops category: {len(data['products'])}")
        
        # Check if all products are in the Laptops category
        all_laptops = all(product['category'] == 'Laptops' for product in data['products'])
        print(f"All products are in Laptops category: {all_laptops}")
    else:
        print("Failed! Status code:", response.status_code)
        print("Response:", response.text)
        
    # Test with different period
    url = f"{BASE_URL}/trending?type=trends&period=month"
    print(f"\nSending GET request to {url}")
    
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print("Success! Status code:", response.status_code)
        print(f"Total trending products in month period: {len(data['products'])}")
    else:
        print("Failed! Status code:", response.status_code)
        print("Response:", response.text)

def test_new_launches():
    """Test the new product launches endpoint"""
    print("\n=== Testing New Product Launches API ===")
    
    # Test with default parameters
    url = f"{BASE_URL}/trending?type=launches"
    print(f"Sending GET request to {url}")
    
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print("Success! Status code:", response.status_code)
        print(f"Total new launches: {len(data['products'])}")
        
        # Display the new launches structure
        print("\nNew launches structure:")
        for idx, product in enumerate(data['products'][:3], 1):  # Show first 3 products
            print(f"\n{idx}. {product['name']}")
            print(f"   Brand: {product['brand']}")
            print(f"   Category: {product['category']}")
            print(f"   Price: ${product['price']}")
            print(f"   Launch Date: {product.get('launch_date', 'N/A')}")
            print(f"   Pre-orders: {product.get('pre_orders', 'N/A')}")
            print(f"   Rating: {product.get('rating', 'N/A')}")
            
        # Display stats
        print("\nStats:")
        print(f"   New Launches: {data['stats'].get('new_launches', 'N/A')}")
        print(f"   Update Frequency: {data['stats'].get('update_frequency', 'N/A')}")
        print(f"   Tracking Type: {data['stats'].get('tracking_type', 'N/A')}")
    else:
        print("Failed! Status code:", response.status_code)
        print("Response:", response.text)
    
    # Test with specific category
    url = f"{BASE_URL}/trending?type=launches&category=Smartphones"
    print(f"\nSending GET request to {url}")
    
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print("Success! Status code:", response.status_code)
        print(f"Total new launches in Smartphones category: {len(data['products'])}")
    else:
        print("Failed! Status code:", response.status_code)
        print("Response:", response.text)

if __name__ == "__main__":
    test_trending_products()
    test_new_launches()
