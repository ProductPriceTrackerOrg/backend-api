"""
Pydantic schemas for Favorites API
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class FavoriteProduct(BaseModel):
    """A product that has been favorited by a user"""
    id: int
    name: str
    brand: Optional[str] = None
    category: Optional[str] = "Uncategorized"
    price: float
    original_price: Optional[float] = None
    image: Optional[str] = None
    retailer: str
    retailer_phone: Optional[str] = None
    retailer_whatsapp: Optional[str] = None
    discount: Optional[int] = 0
    is_available: bool = True
    variant_id: int


class FavoritesResponse(BaseModel):
    """Response for the get user favorites endpoint"""
    favorites: List[FavoriteProduct]
