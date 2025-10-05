from fastapi import APIRouter, Depends, HTTPException, Path
from typing import Dict, List, Optional, Any
from google.cloud import bigquery
import supabase
from app.config import settings
from app.api.deps import get_current_user, get_bigquery_client, get_current_user_optional
from app.schemas.product import ProductDetailsResponse

router = APIRouter()

@router.get("/{product_id}", response_model=ProductDetailsResponse)
async def get_product_detail(
    product_id: int = Path(..., description="The ID of the specific product to retrieve"),
    current_user: Optional[Dict] = Depends(get_current_user_optional),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
) -> Dict:
    """
    Retrieve detailed information about a specific product by its ID.
    This endpoint returns comprehensive product details including pricing, specifications, and availability.
    """
    try:
        # Query to get product details
        query = f"""
        SELECT 
            p.product_id,
            p.product_name,
            p.description,
            p.regular_price,
            p.current_price,
            p.currency,
            p.image_url,
            p.product_url,
            p.brand,
            s.shop_name,
            s.website_url as shop_url,
            s.logo_url as shop_logo_url,
            c.category_name,
            CASE 
                WHEN p.current_price < p.regular_price THEN 
                    ROUND((p.regular_price - p.current_price) / p.regular_price * 100, 0)
                ELSE 0
            END as discount_percentage
        FROM 
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.FactProduct` p
        JOIN
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop` s ON p.shop_id = s.shop_id
        JOIN
            `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimCategory` c ON p.category_id = c.category_id
        WHERE 
            p.product_id = {product_id}
        """
        
        query_job = bq_client.query(query)
        result = list(query_job.result())
        
        if not result:
            raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found")
        
        product = dict(result[0])
        
        # Format the response according to the schema
        response = {
            "product_id": product["product_id"],
            "product_name": product["product_name"],
            "description": product["description"] if product["description"] else "",
            "brand": product["brand"] if product["brand"] else "",
            "category": product["category_name"],
            "pricing": {
                "current_price": product["current_price"],
                "regular_price": product["regular_price"],
                "currency": product["currency"],
                "discount_percentage": product["discount_percentage"]
            },
            "images": [product["image_url"]] if product["image_url"] else [],
            "urls": {
                "product_url": product["product_url"],
                "shop_url": product["shop_url"]
            },
            "shop": {
                "name": product["shop_name"],
                "logo_url": product["shop_logo_url"] if product["shop_logo_url"] else ""
            }
        }
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred retrieving product details: {str(e)}")