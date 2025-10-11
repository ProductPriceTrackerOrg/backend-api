"""
Price drops schema definitions.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class PriceDropProduct(BaseModel):
    """Individual price drop product schema."""
    id: int
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    current_price: float
    previous_price: float
    price_change: float
    percentage_change: float
    retailer: str
    retailer_id: int
    image: Optional[str] = None
    change_date: str
    in_stock: bool = True


class PriceDropResponse(BaseModel):
    """Price drops response schema."""
    price_drops: List[PriceDropProduct]
    total_count: int = Field(..., description="Total number of price drops matching the criteria")
    next_page: Optional[int] = Field(None, description="Next page number if available")
    

class PriceDropStats(BaseModel):
    """Price drops statistics schema."""
    total_drops: int = Field(..., description="Total number of price drops")
    average_discount_percentage: float = Field(..., description="Average discount percentage across all drops")
    retailers_with_drops: int = Field(..., description="Number of retailers with price drops")
    categories_with_drops: int = Field(..., description="Number of categories with price drops")
    largest_drop_percentage: float = Field(..., description="Largest percentage drop")
    total_savings: float = Field(..., description="Total potential savings across all drops")
    drops_last_24h: int = Field(..., description="Number of drops in the last 24 hours")
    drops_last_7d: int = Field(..., description="Number of drops in the last 7 days")


class PriceDropStatsResponse(BaseModel):
    """Price drops statistics response schema."""
    stats: PriceDropStats