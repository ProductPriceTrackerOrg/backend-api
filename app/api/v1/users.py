
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_current_admin_user

router = APIRouter()

@router.get("/profile", summary="Get current user's profile")
async def read_user_profile(current_user: dict = Depends(get_current_user)):
    """
    A protected endpoint to get the profile of the currently logged-in user.
    The user data is sourced directly from the verified JWT.
    """
    return {
        "user_id": current_user.get("sub"),
        "email": current_user.get("email"),
        "roles": current_user.get("app_metadata", {}).get("roles", []),
    }

@router.get("/admin/data", summary="Get sensitive admin data")
async def read_admin_data(admin_user: dict = Depends(get_current_admin_user)):
    """
    A protected endpoint accessible only by users with the 'Admin' role.
    The dependency handles both authentication and authorization.
    """
    return {
        "message": f"Welcome, Admin {admin_user.get('email')}!",
        "sensitive_data": "This is highly confidential admin dashboard information."
    }