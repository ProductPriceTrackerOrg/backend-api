# app/schemas/analytics/price_history.py

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class BestTimeToBuy(BaseModel):
    recommendation: str = Field(..., description="Recommendation text about buying timing")
    confidence: int = Field(..., description="Confidence score for the recommendation (0-100)")


class PriceHistoryPoint(BaseModel):
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    avg_price: float = Field(..., description="Average price on this date")
    lowest_price: float = Field(..., description="Lowest price on this date")
    price_drops: int = Field(..., description="Number of price drops on this date")
    is_good_time_to_buy: bool = Field(..., description="Flag indicating if it's a good time to buy")


class PriceHistoryResponse(BaseModel):
    price_history: List[PriceHistoryPoint] = Field(..., description="List of price history data points")
    best_time_to_buy: BestTimeToBuy = Field(..., description="Recommendation about the best time to buy")