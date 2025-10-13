# app/schemas/analytics/price_alerts.py

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class PriceAlert(BaseModel):
    id: str = Field(..., description="Unique identifier for the alert")
    product_title: str = Field(..., description="Title of the product")
    image_url: str = Field(..., description="URL to the product image")
    original_price: float = Field(..., description="Original price before the change")
    current_price: float = Field(..., description="Current price after the change")
    percentage_change: float = Field(..., description="Percentage change in price")
    shop_name: str = Field(..., description="Name of the shop/retailer")
    detected_date: str = Field(..., description="Date when the price change was detected")
    product_url: str = Field(..., description="URL to the product page")
    type: str = Field(..., description="Type of alert (price_drop, flash_sale, back_in_stock, unusual_discount)")


class PriceAlertsResponse(BaseModel):
    alerts: List[PriceAlert] = Field(..., description="List of price alerts")