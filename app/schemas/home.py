"""
Pydantic schemas for Home API
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, HttpUrl


# --- Home Statistics ---
class HomeStats(BaseModel):
    total_products: str
    product_categories: str
    total_users: str
    total_suppliers: str
    price_updates_today: str
    active_deals: str


# --- Category ---
class Category(BaseModel):
    category_id: int
    name: str
    product_count: str
    trending_score: float
    icon: str
    href: str
    color: str


class CategoriesResponse(BaseModel):
    categories: List[Category]


# --- Product ---
class TrendingProduct(BaseModel):
    id: int
    name: str
    brand: str
    category: str
    variant_id: Optional[int] = None
    variant_title: Optional[str] = None
    price: float
    original_price: Optional[float] = None
    retailer: str
    retailer_id: int
    in_stock: bool
    image: Optional[str] = None
    discount: Optional[int] = None
    trend_score: Optional[float] = None
    search_volume: Optional[str] = None
    price_change: Optional[float] = None
    is_trending: Optional[bool] = None


class TrendingStats(BaseModel):
    trending_searches: str
    accuracy_rate: str
    update_frequency: str


class TrendingResponse(BaseModel):
    products: List[TrendingProduct]
    stats: TrendingStats


# --- New Launch Product ---
class NewLaunchProduct(BaseModel):
    id: int
    name: str
    brand: str
    category: str
    price: float
    retailer: str
    retailer_id: int
    in_stock: bool
    image: Optional[str] = None
    launch_date: Optional[str] = None
    pre_orders: Optional[int] = None
    rating: Optional[float] = None
    is_new: Optional[bool] = None


class NewLaunchStats(BaseModel):
    new_launches: str
    update_frequency: str
    tracking_type: str


class NewLaunchResponse(BaseModel):
    products: List[NewLaunchProduct]
    stats: NewLaunchStats


# --- Latest Product ---
class LatestProduct(BaseModel):
    id: int
    name: str
    brand: str
    category: str
    price: float
    original_price: Optional[float] = None
    retailer: str
    retailer_id: int
    in_stock: bool
    image: Optional[str] = None
    discount: Optional[int] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    added_date: Optional[str] = None


class LatestProductsResponse(BaseModel):
    products: List[LatestProduct]


# --- Price Change ---
class PriceChange(BaseModel):
    id: int
    name: str
    brand: str
    category: str
    current_price: float
    previous_price: float
    price_change: float
    percentage_change: float
    retailer: str
    retailer_id: int
    image: Optional[str] = None
    change_date: Optional[str] = None
    in_stock: bool


class PriceChangeResponse(BaseModel):
    price_changes: List[PriceChange]


# --- Retailer ---
class Retailer(BaseModel):
    shop_id: int
    name: str
    logo: str
    website_url: Optional[str] = None
    product_count: int
    avg_rating: float
    specialty: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_whatsapp: Optional[str] = None


class RetailersResponse(BaseModel):
    retailers: List[Retailer]


# --- Search Suggestions ---
class SearchSuggestions(BaseModel):
    popular_searches: List[str]
    trending_searches: List[str]


# --- Recommendation ---
class RecommendedProduct(BaseModel):
    id: int
    name: str
    brand: str
    category: str
    price: float
    original_price: Optional[float] = None
    retailer: str
    image: Optional[str] = None
    recommendation_score: float
    recommendation_reason: str


class RecommendationsResponse(BaseModel):
    recommended_products: List[RecommendedProduct]
