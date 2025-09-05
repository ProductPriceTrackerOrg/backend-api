from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class NewArrivalResponse(BaseModel):
    variant_id: int  # Changed from str to int
    shop_product_id: int  # Changed from str to int
    product_title: str
    brand: Optional[str]
    category_name: str
    variant_title: Optional[str]
    shop_name: str
    current_price: float
    original_price: Optional[float]
    image_url: Optional[str]
    product_url: Optional[str]
    is_available: bool
    arrival_date: str
    days_since_arrival: int

class NewArrivalsStats(BaseModel):
    total_new_arrivals: int
    average_price: float
    in_stock_count: int
    category_count: int

class NewArrivalsQuery(BaseModel):
    timeRange: Optional[str] = "30d"
    category: Optional[str] = None
    retailer: Optional[str] = None
    minPrice: Optional[float] = None
    maxPrice: Optional[float] = None
    sortBy: Optional[str] = "newest"
    inStockOnly: Optional[bool] = False
    limit: Optional[int] = 20
    page: Optional[int] = 1

class NewArrivalsListResponse(BaseModel):
    items: List[NewArrivalResponse]
    total: int
    page: int
    limit: int
    has_next: bool