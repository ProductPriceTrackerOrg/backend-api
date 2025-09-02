from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class Product(BaseModel):
    """Model for a product."""
    id: int
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    price: float
    original_price: Optional[float] = None
    discount: Optional[int] = None
    retailer: str
    retailer_id: int
    in_stock: bool
    image: Optional[str] = None
    trend_score: Optional[int] = None
    search_volume: Optional[str] = None
    price_change: Optional[float] = None
    is_trending: Optional[bool] = None
    variant_id: Optional[int] = None
    variant_title: Optional[str] = None


class Stats(BaseModel):
    """Stats about trending products."""
    trending_searches: Optional[str] = None
    accuracy_rate: Optional[str] = None
    update_frequency: Optional[str] = None
    new_launches: Optional[str] = None
    tracking_type: Optional[str] = None


class TrendingResponse(BaseModel):
    """Response model for trending products endpoint."""
    products: List[Product]
    stats: Stats
