# app/schemas/analytics/market_summary.py

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class CategoryDistribution(BaseModel):
    name: str = Field(..., description="Category name")
    value: int = Field(..., description="Number of products in this category")
    color: str = Field(..., description="Color hex code for visualization")


class MarketSummary(BaseModel):
    total_products: int = Field(..., description="Total number of products in the market")
    total_shops: int = Field(..., description="Total number of shops in the market")
    average_price_change: float = Field(..., description="Average price change percentage")
    price_drop_percentage: float = Field(..., description="Percentage of products with price drops")
    best_buying_score: int = Field(..., description="Score indicating how good the current market is for buying (0-100)")
    category_distribution: List[CategoryDistribution] = Field(..., description="Distribution of products by category")


class MarketSummaryResponse(BaseModel):
    summary: MarketSummary = Field(..., description="Market summary data")