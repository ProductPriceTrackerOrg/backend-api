# app/schemas/retailer.py

"""
Pydantic schemas for Retailer API
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, HttpUrl


class RetailerContact(BaseModel):
    """Contact information for a retailer"""
    email: Optional[str] = None
    phone: Optional[str] = None 
    address: Optional[str] = None


class Retailer(BaseModel):
    """A retailer with detailed information"""
    id: int
    name: str
    logo: Optional[str] = None
    website: Optional[str] = None
    rating: Optional[float] = None
    product_count: int
    description: Optional[str] = None
    verified: bool = False
    is_featured: bool = False
    headquarters: Optional[str] = None
    founded_year: Optional[int] = None
    contact: Optional[RetailerContact] = None


class RetailerListResponse(BaseModel):
    """Response for the retailers list endpoint"""
    retailers: List[Retailer]
    meta: Dict[str, Any]


class RetailerDetailResponse(BaseModel):
    """Response for the retailer detail endpoint"""
    retailer: Retailer


class RetailerStats(BaseModel):
    """Aggregate statistics about retailers"""
    total_retailers: int
    verified_retailers: int
    total_products: int
    average_rating: float


class RetailerStatsResponse(BaseModel):
    """Response for the retailer stats endpoint"""
    stats: RetailerStats


class Category(BaseModel):
    """Product category data with count for a retailer"""
    id: int
    name: str
    product_count: int


class CategoriesResponse(BaseModel):
    """Response for the retailer categories endpoint"""
    categories: List[Category]


class Brand(BaseModel):
    """Product brand data with count for a retailer"""
    id: int
    name: str
    product_count: int


class BrandsResponse(BaseModel):
    """Response for the retailer brands endpoint"""
    brands: List[Brand]