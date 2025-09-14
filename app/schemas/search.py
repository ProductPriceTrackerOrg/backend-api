"""
Pydantic schemas for Search API
"""
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field


class AutocompleteSuggestions(BaseModel):
    """Response model for autocomplete suggestions"""
    suggestions: List[str] = []


class SearchProduct(BaseModel):
    """A product found in search results"""
    shop_product_id: int = Field(..., alias="shop_product_id")
    name: str
    brand: Optional[str] = None
    product_url: Optional[str] = None
    category_name: Optional[str] = "Uncategorized"
    category_id: Optional[int] = None
    retailer: str
    retailer_id: int
    price: float
    original_price: Optional[float] = None
    in_stock: bool = True
    image: Optional[str] = None
    discount: Optional[int] = 0
    match_group_id: Union[str, int]  # Can be either string or int depending on the database
    is_direct_match: Optional[bool] = False
    relevance_score: Optional[int] = 1


class PaginationInfo(BaseModel):
    """Pagination information for search results"""
    current_page: int
    total_pages: int
    total_items: int
    items_per_page: int


class SearchResultsResponse(BaseModel):
    """Response model for search results"""
    products: List[SearchProduct] = []
    pagination: PaginationInfo
    query: str