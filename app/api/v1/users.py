
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_current_admin_user

router = APIRouter()

@router.get("/profile", summary="Get current user's profile")
async def read_user_profile(current_user: dict = Depends(get_current_user)):
    """
    A protected endpoint to get the profile of the currently logged-in user.
    The user data is sourced directly from the verified JWT.
    """
    try:
        # Extract key user details from the token
        user_id = current_user.get("sub")
        email = current_user.get("email")
        roles = current_user.get("app_metadata", {}).get("roles", [])
        
        # Additional token data that might be useful
        additional_data = {
            "aud": current_user.get("aud"),
            "exp": current_user.get("exp"),
            "iat": current_user.get("iat"),
        }
        
        return {
            "status": "success",
            "user_id": user_id,
            "email": email,
            "roles": roles,
            "token_info": additional_data
        }
    except Exception as e:
        # This would only happen if there's an issue after authentication succeeded
        return {
            "status": "error",
            "message": f"Error processing user data: {str(e)}",
            "token_keys_found": list(current_user.keys()) if current_user else None
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