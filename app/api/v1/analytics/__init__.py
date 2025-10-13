# app/api/v1/analytics/__init__.py

from fastapi import APIRouter
from app.api.v1.analytics.price_history import router as price_history_router
from app.api.v1.analytics.category_insights import router as category_insights_router
from app.api.v1.analytics.shop_comparison import router as shop_comparison_router
from app.api.v1.analytics.price_alerts import router as price_alerts_router
from app.api.v1.analytics.market_summary import router as market_summary_router

router = APIRouter()

# Include all analytics sub-routers
router.include_router(price_history_router)
router.include_router(category_insights_router)
router.include_router(shop_comparison_router)
router.include_router(price_alerts_router)
router.include_router(market_summary_router)