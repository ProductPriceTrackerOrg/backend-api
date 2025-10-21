from fastapi import APIRouter, Depends, Request, Body
from jose import jwt
from typing import Optional, Dict, Any

from app.api.deps import security, get_current_user
from app.config import settings
from app.services.cache_service import cache_service
from app.api.v1.admin.dependencies import get_current_admin_user

router = APIRouter()

@router.post("/debug-token", summary="Debug JWT token")
async def debug_jwt_token(request: Request):
    """
    A diagnostic endpoint to analyze and debug JWT tokens.
    Provide the token in the Authorization header as "Bearer <token>".
    """
    try:
        # Get the authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return {"error": "Invalid Authorization header format. Use 'Bearer <token>'"}
            
        # Extract the token
        token = auth_header.split(" ")[1]
        
        # First, analyze the token without verification
        unverified_payload = jwt.decode(
            token,
            options={"verify_signature": False}
        )
        
        # Now try to verify with our settings
        try:
            verified_payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_signature": True, "verify_aud": False, "verify_exp": True}
            )
            verification_status = "SUCCESS"
        except Exception as e:
            verified_payload = None
            verification_status = f"FAILED: {str(e)}"
        
        return {
            "token_structure": {
                "header": token.split(".")[0],
                "payload": unverified_payload,
                "signature_present": len(token.split(".")) > 2
            },
            "verification": {
                "status": verification_status,
                "verified_payload": verified_payload
            },
            "debug_info": {
                "sub_present": "sub" in unverified_payload,
                "exp_present": "exp" in unverified_payload,
                "aud_present": "aud" in unverified_payload,
                "algorithm": jwt.get_unverified_header(token).get("alg"),
            }
        }
    except Exception as e:
        return {"error": f"Failed to parse token: {str(e)}"}


@router.get("/cache-status", summary="Get cache status and statistics")
async def get_cache_status(current_user = Depends(get_current_admin_user)):
    """
    Get detailed information about the cache system, including statistics.
    Requires admin authentication.
    """
    stats = cache_service.get_stats()
    return {
        "cache_status": stats,
        "config": {
            "cache_debug_enabled": settings.CACHE_DEBUG,
            "redis_url_provided": bool(settings.REDIS_URL)
        }
    }


@router.post("/cache-debug-mode", summary="Toggle cache debug mode")
async def toggle_cache_debug_mode(
    enable_debug: bool = Body(..., embed=True), 
    current_user = Depends(get_current_admin_user)
):
    """
    Enable or disable cache debug mode. This will turn on detailed logging of cache operations.
    Requires admin authentication.
    """
    # Note: This is a temporary runtime change, will not persist after server restart
    cache_service.debug = enable_debug
    
    return {
        "success": True,
        "debug_mode": enable_debug
    }


@router.post("/cache/flush", summary="Flush the entire cache")
async def flush_cache(current_user = Depends(get_current_admin_user)):
    """
    Flush the entire cache, removing all keys.
    Use with caution! This will delete all cached data.
    Requires admin authentication.
    """
    success = cache_service.flush()
    return {
        "success": success,
        "message": "Cache flushed successfully" if success else "Failed to flush cache"
    }


@router.get("/cache/key/{key}", summary="Get a specific cache key")
async def get_cache_key(
    key: str,
    current_user = Depends(get_current_admin_user)
):
    """
    Get the value for a specific cache key.
    Requires admin authentication.
    """
    value = cache_service.get(key)
    if value is not None:
        return {
            "key": key,
            "exists": True,
            "value": value
        }
    else:
        return {
            "key": key,
            "exists": False
        }


@router.delete("/cache/key/{key}", summary="Delete a specific cache key")
async def delete_cache_key(
    key: str,
    current_user = Depends(get_current_admin_user)
):
    """
    Delete a specific cache key.
    Requires admin authentication.
    """
    success = cache_service.delete(key)
    return {
        "success": success,
        "key": key,
        "message": f"Key '{key}' deleted successfully" if success else f"Failed to delete key '{key}' or key not found"
    }
