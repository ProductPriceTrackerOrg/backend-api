"""
Pydantic schemas for Category API
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, HttpUrl


class SubCategory(BaseModel):
    category_id: int
    name: str
    product_count: int
    parent_category_id: int


class Category(BaseModel):
    category_id: int
    name: str
    description: Optional[str] = None
    product_count: int
    parent_category_id: Optional[int] = None
    subcategories: Optional[List[SubCategory]] = None
    trending_score: Optional[float] = None
    icon: Optional[str] = None
    color: Optional[str] = None


class CategoriesResponse(BaseModel):
    categories: List[Category]
    total_categories: int
    total_products: int


class Brand(BaseModel):
    name: str
    count: int


class Retailer(BaseModel):
    retailer_id: int
    name: str
    count: int


class PriceRange(BaseModel):
    range: str
    count: int


class FilterOptions(BaseModel):
    brands: List[Brand]
    retailers: Optional[List[Retailer]] = []
    price_ranges: Optional[List[PriceRange]] = []


class ProductInCategory(BaseModel):
    id: int
    name: str
    brand: Optional[str] = None
    price: float
    retailer: str
    original_price: Optional[float] = None
    discount: Optional[int] = None
    retailer_id: Optional[int] = None
    in_stock: Optional[bool] = True
    image: Optional[str] = None
    rating: Optional[float] = None
    popularity_score: Optional[int] = None


class PaginationInfo(BaseModel):
    current_page: int
    total_pages: int
    total_items: int
    items_per_page: int


class CategoryProductsResponse(BaseModel):
    category: Category
    products: List[ProductInCategory]
    pagination: PaginationInfo
    filters: FilterOptions
