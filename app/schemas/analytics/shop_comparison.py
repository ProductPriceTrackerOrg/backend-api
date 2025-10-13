# app/schemas/analytics/shop_comparison.py

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class ShopInsight(BaseModel):
    shop_name: str = Field(..., description="Name of the shop/retailer")
    product_count: int = Field(..., description="Number of products available in this shop")
    avg_price_rating: int = Field(..., description="Average price competitiveness rating (0-100)")
    reliability_score: int = Field(..., description="Reliability score based on consistent inventory (0-100)")
    availability_percentage: float = Field(..., description="Percentage of products available")
    best_categories: List[str] = Field(..., description="Categories where this shop performs best")


class ShopComparisonResponse(BaseModel):
    insights: List[ShopInsight] = Field(..., description="List of shop comparison insights")