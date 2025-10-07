# app/schemas/analytics/category_insights.py

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class CategoryInsight(BaseModel):
    category_name: str = Field(..., description="Name of the category")
    avg_price: float = Field(..., description="Average price in the category")
    price_change: float = Field(..., description="Price change percentage compared to previous period")
    price_volatility: float = Field(..., description="Price volatility measure (standard deviation/mean)")
    product_count: int = Field(..., description="Number of products in this category")
    deal_count: int = Field(..., description="Number of deals/discounts in this category")


class CategoryInsightsResponse(BaseModel):
    insights: List[CategoryInsight] = Field(..., description="List of category insights")