# app/schemas/product.py

"""
Pydantic schemas for Product API
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, HttpUrl


# --- Product Details ---
class Variant(BaseModel):
    """A product variant such as a specific size, color, or configuration"""
    variant_id: int
    title: str  # Using more consistent naming
    price: float
    original_price: Optional[float] = None
    is_available: bool
    discount: Optional[int] = None
    price_change_30d: Optional[float] = None


class Product(BaseModel):
    """A canonical product with all its variants"""
    id: int
    name: str
    brand: Optional[str]
    category: Optional[str] = "Uncategorized"
    category_id: Optional[int] = 0
    image: Optional[str] = None  # Primary image
    images: Optional[List[str]] = None  # All product images
    description: Optional[str] = None
    product_url: Optional[str] = None  # URL to the product page
    retailer: Optional[str] = None
    retailer_phone: Optional[str] = None
    retailer_whatsapp: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    variants: List[Variant]
    is_favorited: bool = False


class ProductDetailsResponse(BaseModel):
    """Response for the product details endpoint"""
    product: Product


# --- Price History ---
class PricePoint(BaseModel):
    """A price point for a specific date"""
    date: str
    price: float
    is_minimum: Optional[bool] = None
    is_maximum: Optional[bool] = None
    change: Optional[float] = None
    change_percentage: Optional[float] = None


class PriceHistoryResponse(BaseModel):
    """Response for the price history endpoint"""
    price_history: List[PricePoint]
    statistics: Dict[str, Any]


# --- Price Forecast ---
class ForecastPoint(BaseModel):
    """A price forecast point for a specific date"""
    date: str
    predicted_price: float
    upper_bound: Optional[float] = None
    lower_bound: Optional[float] = None
    confidence: Optional[float] = None


class ForecastResponse(BaseModel):
    """Response for the price forecast endpoint"""
    forecasts: List[ForecastPoint]
    model_info: Dict[str, Any]


# --- Price Anomalies ---
class Anomaly(BaseModel):
    """A price anomaly detection"""
    anomaly_id: int
    date: str
    price: float
    previous_price: float
    change_percentage: float
    anomaly_score: float
    anomaly_type: str
    model_name: str


class AnomalyResponse(BaseModel):
    """Response for the price anomalies endpoint"""
    anomalies: List[Anomaly]


# --- Similar Products ---
class SimilarProduct(BaseModel):
    """A similar product recommendation"""
    id: int
    name: str
    brand: str
    category: str
    price: float
    original_price: Optional[float] = None
    retailer: str
    image: Optional[str] = None
    similarity_score: float


class SimilarProductsResponse(BaseModel):
    """Response for the similar products endpoint"""
    similar_products: List[SimilarProduct]


# --- Product Recommendations ---
class RecommendedProduct(BaseModel):
    """A product recommendation"""
    id: int
    name: str
    brand: str
    category: str
    price: float
    original_price: Optional[float] = None
    retailer: str
    image: Optional[str] = None
    recommendation_score: float
    recommendation_type: str


class RecommendationsResponse(BaseModel):
    """Response for the product recommendations endpoint"""
    recommendations: List[RecommendedProduct]


# --- Product Comparison ---
class ComparedProduct(BaseModel):
    """A product being compared"""
    id: int
    name: str
    brand: str
    category: str
    price: float
    original_price: Optional[float] = None
    discount: Optional[int] = None
    retailer: str
    image: Optional[str] = None
    specs: Dict[str, Any]
    attributes: Dict[str, Any]


class ComparisonResponse(BaseModel):
    """Response for the product comparison endpoint"""
    comparison: List[ComparedProduct]
    common_attributes: List[str]


# --- Favorite Response ---
class FavoriteResponse(BaseModel):
    """Response for the favorite endpoints"""
    is_favorited: bool
    message: str


# --- View Log Response ---
class ViewLogResponse(BaseModel):
    """Response for the view log endpoint"""
    logged: bool
    variant_id: Optional[int] = None
