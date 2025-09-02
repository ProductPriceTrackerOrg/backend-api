"""
Test the improved categories implementation
"""

import requests
import json
from pprint import pprint

# Base URL
BASE_URL = "http://localhost:8000/api/v1"

def test_improved_categories():
    """Test the improved categories implementation"""
    print("\n=== Testing Improved Categories API ===")
    
    # Test with default parameters
    url = f"{BASE_URL}/categories"
    print(f"Sending GET request to {url}")
    
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print("✅ Success! Status code:", response.status_code)
        print(f"Total categories: {data['total_categories']}")
        print(f"Total products: {data['total_products']}")
        
        # Display the categories structure
        print("\nCategory structure:")
        for idx, category in enumerate(data['categories'][:3], 1):  # Show first 3 categories
            print(f"\n{idx}. {category['name']}")
            print(f"   ID: {category['category_id']}")
            print(f"   Products: {category['product_count']}")
            print(f"   Trending Score: {category['trending_score']}")
            
            # Show subcategories count and first few if available
            subcats = category.get('subcategories', [])
            print(f"   Subcategories: {len(subcats)}")
            for i, sub in enumerate(subcats[:2], 1):  # Show first 2 subcategories
                if i > 2:
                    break
                print(f"     {i}. {sub['name']} (ID: {sub['category_id']}, Products: {sub['product_count']})")
    else:
        print("❌ Failed! Status code:", response.status_code)
        print("Response:", response.text)
    
    # Test without subcategories
    url = f"{BASE_URL}/categories?include_subcategories=false"
    print(f"\nSending GET request to {url}")
    
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print("✅ Success! Status code:", response.status_code)
        print(f"Total categories: {data['total_categories']}")
        print(f"Total products: {data['total_products']}")
        
        # Check if subcategories are empty lists
        has_empty_subcats = all(len(cat.get('subcategories', [])) == 0 for cat in data['categories'])
        print(f"All categories have empty subcategories lists: {has_empty_subcats}")
    else:
        print("❌ Failed! Status code:", response.status_code)
        print("Response:", response.text)

if __name__ == "__main__":
    test_improved_categories()
