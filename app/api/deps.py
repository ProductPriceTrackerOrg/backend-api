# app/api/deps.py

import time
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError

from app.config import settings

# This helper scheme will extract the token from the "Authorization: Bearer <token>" header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Decodes and verifies the Supabase JWT.
    Returns the token's payload if valid.
    This is used for routes that any logged-in user can access.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"]
        )
        if payload.get("sub") is None:
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception

async def get_current_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """
    A dependency for admin-only routes.
    It first verifies the user is logged in, then checks for the 'Admin' role
    and enforces a stricter session timeout for enhanced security.
    """
    # Your Edge Function adds roles to the 'app_metadata' claim
    roles = current_user.get("app_metadata", {}).get("roles", [])

    if "Admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for this resource."
        )

    # Enforce a 1-hour session timeout for admins for security
    MAX_ADMIN_SESSION_DURATION = 3600  # 1 hour in seconds
    issued_at_timestamp = current_user.get("iat")

    if (time.time() - issued_at_timestamp) > MAX_ADMIN_SESSION_DURATION:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session expired due to inactivity. Please log in again."
        )

    return current_user