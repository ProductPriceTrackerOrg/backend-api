from fastapi import APIRouter, Depends, HTTPException
from google.cloud import bigquery
from .dependencies import get_current_admin_user
from app.services import admin_service, user_service
from app.api.deps import get_bigquery_client
from pydantic import BaseModel
from typing import Dict, Optional
from datetime import date, timedelta

# All routes in this file will have the prefix /admin
# and will be protected by our admin security dependency.
router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(get_current_admin_user)]
)

# Dashboard stats fetching end point
@router.get("/dashboard-stats")
async def get_dashboard_stats(bq_client: bigquery.Client = Depends(get_bigquery_client)):
    """
    Fetches key statistics for the main dashboard cards.
    This endpoint now calls the admin_service to get live data from BigQuery.
    """
    # Instead of mock data, we now call our service function to get live stats
    live_stats = admin_service.get_dashboard_stats_from_db(bq_client)
    return live_stats


# Anomaly fetching end point
@router.get("/anomalies")
async def get_anomalies(
    page: int = 1, 
    per_page: int = 20, 
    bq_client: bigquery.Client = Depends(get_bigquery_client)
):
    """
    Fetches a paginated list of price anomalies that are pending review.
    """
    anomalies = admin_service.get_pending_anomalies(bq_client, page, per_page)
    if "error" in anomalies:
        raise HTTPException(status_code=500, detail=anomalies["error"])
    return anomalies


# Define a Pydantic model for the request body of the resolve endpoint.
# This ensures the frontend sends the data in the correct format.
class AnomalyResolution(BaseModel):
    resolution: str

# Anomaly Resolving end point ---
@router.post("/anomalies/{anomaly_id}/resolve")
async def resolve_anomaly_endpoint(
    anomaly_id: int,
    resolution_data: AnomalyResolution,
    admin_user: Dict = Depends(get_current_admin_user),
    bq_client: bigquery.Client = Depends(get_bigquery_client)
):
    """
    Allows an admin to resolve an anomaly by updating its status.
    Expects a JSON body, for example: { "resolution": "DATA_ERROR" }
    """
    user_email = admin_user.get("email", "unknown_admin")
    resolution_status = resolution_data.resolution
    
    # Validate that the resolution status is one of the allowed values
    allowed_statuses = ["CONFIRMED_SALE", "DATA_ERROR"]
    if resolution_status not in allowed_statuses:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid resolution status. Must be one of {allowed_statuses}"
        )
        
    result = admin_service.resolve_anomaly(bq_client, anomaly_id, resolution_status, user_email)
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
        
    return result

# User Sign-Ups analytics end point
@router.get("/analytics/user-signups")
async def get_user_signups_analytics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    days: int = 30
):
    """
    Fetches user sign-up data for the analytics chart.
    Can be filtered by a specific date range or a number of past days.
    """
    # If no specific dates are provided, calculate the range based on the 'days' parameter.
    if start_date is None or end_date is None:
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        
    # Call the service function to get the data
    signup_data = user_service.get_user_signups_over_time(start_date, end_date)
    
    if "error" in signup_data:
        raise HTTPException(status_code=500, detail=signup_data["error"])
        
    return signup_data



# Category Distribution end point
@router.get("/analytics/category-distribution")
async def get_category_distribution_analytics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    days: int = 30,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
):
    """
    Fetches the distribution of products across categories for a pie chart.
    """
    if start_date is None or end_date is None:
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
    
    category_data = admin_service.get_category_distribution(bq_client, start_date, end_date)
    
    if isinstance(category_data, list) and category_data and "error" in category_data[0]:
        raise HTTPException(status_code=500, detail=category_data[0]["error"])
        
    return category_data

