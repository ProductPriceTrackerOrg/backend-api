# app/schemas/buyer_central.py

"""
Pydantic schemas for Buyer Central API endpoints
"""
from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, Field, HttpUrl
from datetime import datetime


# --- Product Search API ---
class SearchProductItem(BaseModel):
    """A product item returned from search results"""
    id: int
    name: str
    brand: Optional[str] = None
    category: Optional[str] = "Uncategorized"
    avgPrice: float
    image: Optional[str] = None


class SearchProductsResponse(BaseModel):
    """Response model for product search API"""
    success: bool = True
    data: List[SearchProductItem]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# --- Price Comparison API ---
class RetailerPrice(BaseModel):
    """Price information for a specific retailer"""
    retailerId: int
    retailerName: str
    price: float
    stockStatus: Literal["in_stock", "out_of_stock"]
    rating: Optional[float] = None
    lastUpdated: str  # ISO format date string


class PriceHistory(BaseModel):
    """Price history trend information"""
    priceChange: float
    trend: Literal["increasing", "decreasing", "stable"]


class ProductPriceComparison(BaseModel):
    """Price comparison information for a specific product"""
    productId: int
    productName: str
    categoryName: Optional[str] = "Uncategorized"
    averagePrice: float
    retailerPrices: List[RetailerPrice]
    priceHistory: PriceHistory


class PriceComparisonResponse(BaseModel):
    """Response model for price comparison API"""
    success: bool = True
    data: List[ProductPriceComparison]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# --- Buying Guides Categories API ---
class BuyingGuideCategory(BaseModel):
    """Category information for buying guides"""
    categoryId: int
    categoryName: str
    description: str
    icon: str
    guideCount: int
    avgProductPrice: float
    popularBrands: List[str]


class BuyingGuidesResponse(BaseModel):
    """Response model for buying guides categories API"""
    success: bool = True
    data: List[BuyingGuideCategory]
    timestamp: datetime = Field(default_factory=datetime.utcnow)