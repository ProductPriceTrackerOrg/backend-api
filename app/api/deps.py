# app/api/deps.py

import time
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordBearer

from google.cloud import bigquery
from google.oauth2 import service_account

from app.config import settings

# This helper scheme will extract the token from the "Authorization: Bearer <token>" header
security = HTTPBearer()
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # CHANGE 4: The token is now inside the credentials object
        token = credentials.credentials
        
        # The rest of the logic remains the same
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

# --- Dependency for Admin-Only Routes (NO CHANGES NEEDED HERE) ---
async def get_current_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    roles = current_user.get("app_metadata", {}).get("roles", [])

    if "Admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this resource."
        )

    MAX_ADMIN_SESSION_DURATION = 3600
    issued_at_timestamp = current_user.get("iat")

    if (time.time() - issued_at_timestamp) > MAX_ADMIN_SESSION_DURATION:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session expired due to inactivity. Please log in again."
        )

    return current_user

def get_bigquery_client():
    """
    Returns a BigQuery client using the service account credentials.
    """
    try:
        # Path to the credentials file
        credentials_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "gcp-credentials.json")
        
        # Create credentials from the service account file
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        
        # Create and return BigQuery client
        client = bigquery.Client(
            project=settings.GCP_PROJECT_ID,
            credentials=credentials
        )
        return client
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create BigQuery client: {e}"
        )