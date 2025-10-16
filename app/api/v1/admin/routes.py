from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud import bigquery
from .dependencies import get_current_admin_user
from app.services import admin_service, user_service, audit_service, pipeline_service
from app.api.deps import get_bigquery_client
from pydantic import BaseModel
from typing import Dict, Optional, List
from datetime import date, timedelta

# All routes in this file will have the prefix /admin
# and will be protected by our admin security dependency.
router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(get_current_admin_user)]
)


# Pydantic model for the response of the user list
class User(BaseModel):
    user_id: str
    email: str
    full_name: str
    is_active: bool
    role: str
    created_at: str

class UserListResponse(BaseModel):
    users: List[User]
    total: int


# Pydantic model for the request body of the status update
class UserStatusUpdate(BaseModel):
    is_active: bool   
    
    
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

# End point for fetching anomalies
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
    
    # This is a robust way to check for an error from the service.
    if isinstance(anomalies, list) and anomalies and "error" in anomalies[0]:
        raise HTTPException(status_code=500, detail=anomalies[0]["error"])
        
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
    admin_id = admin_user.get("sub") # The user's UUID from the JWT
    resolution_status = resolution_data.resolution
    
    # Validate that the resolution status is one of the allowed values
    allowed_statuses = ["CONFIRMED_SALE", "DATA_ERROR"]
    if resolution_status not in allowed_statuses:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid resolution status. Must be one of {allowed_statuses}"
        )
        
    result = admin_service.resolve_anomaly(bq_client, anomaly_id, resolution_status, user_email)
    
    # --- Step 2: Log the successful action to the audit trail ---
    audit_service.log_admin_action(
        admin_user_id=admin_id,
        action_type='RESOLVE_ANOMALY',
        target_entity_type='ANOMALY',
        target_entity_id=str(anomaly_id),
        details={'resolution': resolution_status}
    )
    
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


@router.get("/analytics/top-tracked-products")
async def get_top_tracked_products_analytics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    days: int = 30,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
):
    """
    Fetches the top 10 most tracked products for the analytics bar chart.
    """
    if start_date is None or end_date is None:
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
    
    top_products_data = admin_service.get_top_tracked_products(bq_client, start_date, end_date)
    
    if isinstance(top_products_data, list) and top_products_data and "error" in top_products_data[0]:
        raise HTTPException(status_code=500, detail=top_products_data[0]["error"])
        
    return top_products_data


# End point for getting users list
@router.get("/users", response_model=UserListResponse)
async def get_users_list(
    search: Optional[str] = None,
    status: Optional[str] = Query(None, pattern="^(active|inactive)$"),
    page: int = 1,
    per_page: int = 20
):
    """
    Fetches a paginated and searchable list of all users, including their roles.
    """
    is_active_filter = None
    if status == "active":
        is_active_filter = True
    elif status == "inactive":
        is_active_filter = False
        
    result = user_service.get_users(
        search=search,
        is_active=is_active_filter,
        page=page,
        per_page=per_page
    )
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
        
    return result


# End point for updating the status of a user
@router.put("/users/{user_id}/status")
async def update_user_status_endpoint(
    user_id: str,
    status_update: UserStatusUpdate,
    admin_user: Dict = Depends(get_current_admin_user)
):
    """
    Updates a user's active status.
    """
    result = user_service.update_user_status(user_id=user_id, is_active=status_update.is_active)
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    
    # --- Log this action to our audit trail ---
    # We now call the log_admin_action function with the structured arguments it expects.
    admin_id = admin_user.get("sub") # The 'sub' field in a JWT is the user's UUID
    new_status_str = "active" if status_update.is_active else "inactive"
    
    audit_service.log_admin_action(
        admin_user_id=admin_id,
        action_type='UPDATE_USER_STATUS',
        target_entity_type='USER',
        target_entity_id=user_id,
        details={'new_status': new_status_str}
    )
    
    return {"status": "success", "message": f"User {user_id} status updated successfully."}



# Pipeline monitoring end point
@router.get("/pipeline-status")
async def get_pipeline_status():
    """
    Fetches the full details of the most recent data pipeline run.
    """
    # Call our service to get the data for the latest run.
    latest_run = pipeline_service.get_latest_pipeline_run()
    
    # If the service returns None (meaning the log table is empty),
    # we return None, and FastAPI will handle it as an empty response.
    if latest_run is None:
        return None
    
    # Return the complete dictionary from the service. The frontend can now
    # pick the fields it needs (status, run_timestamp, etc.) for the UI cards.
    return latest_run


# End point for fetching the recent admin actions
@router.get("/recent-activity")
async def get_recent_activity():
    """
    Fetches a list of the most recent actions performed by admins from the audit log.
    """
    activity_data = admin_service.get_recent_admin_activity()
    
    # Check if the service returned an error
    if isinstance(activity_data, list) and activity_data and "error" in activity_data[0]:
        raise HTTPException(status_code=500, detail=activity_data[0]["error"])
        
    return activity_data

# End point for Anomaly Price History
@router.get("/anomalies/{anomaly_id}/price-history")
async def get_anomaly_price_history_endpoint(
    anomaly_id: int,
    days: int = 90,
    bq_client: bigquery.Client = Depends(get_bigquery_client)
):
    """
    Fetches the recent price history for the variant associated with a specific anomaly.
    """
    history = admin_service.get_price_history_for_anomaly(bq_client, anomaly_id, days)
    
    if isinstance(history, list) and history and "error" in history[0]:
        raise HTTPException(status_code=500, detail=history[0]["error"])
        
    return history