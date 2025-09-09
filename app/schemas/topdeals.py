from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class DealResponse(BaseModel):
    variant_id: int = Field(..., description="Unique variant identifier")
    shop_product_id: int = Field(..., description="Product identifier in the shop")
    product_id: int = Field(..., description="Main product identifier (same as shop_product_id)")
    product_title: str = Field(..., description="Product name/title")
    brand: Optional[str] = Field(None, description="Product brand")
    category_name: str = Field(..., description="Product category")
    variant_title: Optional[str] = Field(None, description="Variant specifications")
    shop_name: str = Field(..., description="Retailer/shop name")
    current_price: float = Field(..., description="Current discounted price")
    original_price: float = Field(..., description="Original price before discount")
    image_url: Optional[str] = Field(None, description="Product image URL")
    product_url: Optional[str] = Field(None, description="Product page URL")
    is_available: bool = Field(..., description="Stock availability status")
    discount_percentage: float = Field(..., description="Discount percentage")
    discount_amount: float = Field(..., description="Discount amount in currency")
    deal_score: float = Field(..., description="Deal quality score (0-100)")
    updated_date: str = Field(..., description="Last updated date (YYYYMMDD format)")

class DealsStats(BaseModel):
    total_deals: int = Field(..., description="Total number of active deals")
    average_discount: float = Field(..., description="Average discount percentage")
    highest_discount: float = Field(..., description="Highest discount percentage")
    total_savings: float = Field(..., description="Total potential savings")
    categories_with_deals: int = Field(..., description="Number of categories with deals")
    retailers_with_deals: int = Field(..., description="Number of retailers with deals")

class DealsQuery(BaseModel):
    category: Optional[str] = Field(None, description="Filter by category")
    retailer: Optional[str] = Field(None, description="Filter by retailer")
    brand: Optional[str] = Field(None, description="Filter by brand")
    min_discount: Optional[float] = Field(None, description="Minimum discount percentage", ge=0, le=100)
    max_discount: Optional[float] = Field(None, description="Maximum discount percentage", ge=0, le=100)
    min_price: Optional[float] = Field(None, description="Minimum current price", ge=0)
    max_price: Optional[float] = Field(None, description="Maximum current price", ge=0)
    sort_by: Optional[str] = Field(
        "discount_desc",
        description="Sort order: discount_desc, discount_asc, price_low, price_high, deal_score, newest"
    )
    in_stock_only: Optional[bool] = Field(True, description="Show only in-stock products")
    limit: Optional[int] = Field(20, description="Number of items per page", ge=1, le=100)
    page: Optional[int] = Field(1, description="Page number", ge=1)

class DealsListResponse(BaseModel):
    items: List[DealResponse] = Field(..., description="List of deals")
    total: int = Field(..., description="Total items returned")
    page: int = Field(..., description="Current page number")
    limit: int = Field(..., description="Items per page")
    has_next: bool = Field(..., description="Whether there are more pages")
    stats: DealsStats = Field(..., description="Deals statistics")

class CategoryDealsStats(BaseModel):
    category_name: str = Field(..., description="Category name")
    deal_count: int = Field(..., description="Number of deals in this category")
    average_discount: float = Field(..., description="Average discount in this category")
    highest_discount: float = Field(..., description="Highest discount in this category")

class RetailerDealsStats(BaseModel):
    shop_name: str = Field(..., description="Retailer name")
    deal_count: int = Field(..., description="Number of deals from this retailer")
    average_discount: float = Field(..., description="Average discount from this retailer")
    highest_discount: float = Field(..., description="Highest discount from this retailer")

class DealsAnalyticsResponse(BaseModel):
    overall_stats: DealsStats = Field(..., description="Overall deals statistics")
    category_breakdown: List[CategoryDealsStats] = Field(..., description="Deals by category")
    retailer_breakdown: List[RetailerDealsStats] = Field(..., description="Deals by retailer")
    trending_categories: List[str] = Field(..., description="Categories with most deals")
    top_retailers: List[str] = Field(..., description="Retailers with most deals")