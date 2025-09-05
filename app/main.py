# app/main.py

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import users, home,newarrivals
from app.config import settings
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPICallError

# --- 2. BigQuery Client Initialization ---
# Explicitly load the credentials file
import os
from google.oauth2 import service_account

# Path to the credentials file (adjust if necessary)
credentials_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gcp-credentials.json"
)

try:
    # Create credentials from the service account file
    credentials = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    # Create BigQuery client with explicit credentials
    bq_client = bigquery.Client(
        project=settings.GCP_PROJECT_ID, credentials=credentials
    )
    print(
        "Successfully connected to Google BigQuery using service account credentials."
    )
except Exception as e:
    print(f"Failed to connect to BigQuery: {e}")
    bq_client = None

app = FastAPI(
    title="PricePulse API",
    description="Backend API for the PricePulse platform.",
    version="1.0.0",
)

# --- CORS (Cross-Origin Resource Sharing) ---
# This middleware is essential for allowing  frontend application,
# which runs on a different origin (domain/port), to make requests to this backend.
# In production, you should restrict origins to  frontend's actual domain for security.
origins = [
    "http://localhost:3000",  #  Next.js development server
    # "https://production-frontend-domain.com", # Add  production domain
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)


# --- API Routers ---
# Include the user and authentication routes
app.include_router(users.router, prefix="/api/v1", tags=["Users"])
# Include the home routes
app.include_router(home.router, prefix="/api/v1/home", tags=["Home"])
# Include the product routes
from app.api.v1 import products

app.include_router(products.router, prefix="/api/v1/products", tags=["Products"])
# Include the categories routes
from app.api.v1 import categories

app.include_router(categories.router, prefix="/api/v1/categories", tags=["Categories"])
# Include debug routes for troubleshooting
from app.api.v1 import debug

app.include_router(debug.router, prefix="/api/v1/debug", tags=["Debug"])
# Include the trending routes
from app.api.v1 import trending

app.include_router(trending.router, prefix="/api/v1/trending", tags=["Trending"])
# Include the new arrivals routes
from app.api.v1 import newarrivals

app.include_router(newarrivals.router, prefix="/api/v1", tags=["new-arrivals"])


@app.get("/health")
async def health_check():
    """
    Health check endpoint that verifies all components are operational.
    """
    health = {
        "status": "healthy",
        "api_version": "1.0.0",
        "components": {
            "bigquery": {"status": "unknown", "error": None},
            "settings": {
                "status": "ok",
                "config": {
                    "supabase_url": bool(settings.SUPABASE_URL),
                    "supabase_key": bool(settings.SUPABASE_KEY),
                    "supabase_jwt_secret": bool(settings.SUPABASE_JWT_SECRET),
                    "gcp_project": bool(settings.GCP_PROJECT_ID),
                    "redis_url": bool(settings.REDIS_URL),
                },
            },
        },
    }

    # Check BigQuery connection
    try:
        if not bq_client:
            health["components"]["bigquery"]["status"] = "error"
            health["components"]["bigquery"][
                "error"
            ] = "BigQuery client not initialized"
            health["status"] = "degraded"
        else:
            # A simple query to select data from one of your tables
            query = f"""
                SELECT COUNT(*) as count 
                FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop`
                LIMIT 1;
            """

            query_job = bq_client.query(query)
            result = next(query_job.result())

            health["components"]["bigquery"]["status"] = "ok"
            health["components"]["bigquery"]["shop_count"] = result.count
    except Exception as e:
        health["components"]["bigquery"]["status"] = "error"
        health["components"]["bigquery"]["error"] = str(e)
        health["status"] = "degraded"

    return health


@app.get("/check-bigquery")
async def check_bigquery_connection():
    """
    This endpoint runs a simple query on your DimShop table
    to verify the BigQuery connection and data access.
    """
    if not bq_client:
        raise HTTPException(
            status_code=500,
            detail="BigQuery client is not initialized. Check server logs.",
        )

    # A simple query to select data from one of your tables
    query = f"""
        SELECT shop_name, website_url
        FROM `{settings.GCP_PROJECT_ID}.{settings.BIGQUERY_DATASET_ID}.DimShop`
        ORDER BY shop_name
        LIMIT 10;
    """

    try:
        print(f"Running query: {query}")
        # Execute the query
        query_job = bq_client.query(query)
        # Convert the results into a list of dictionaries
        results = [dict(row) for row in query_job.result()]

        return {
            "status": "success",
            "message": "Successfully connected to BigQuery and fetched data.",
            "data": results,
        }

    except GoogleAPICallError as e:
        # Handle potential API errors (e.g., permissions, table not found)
        raise HTTPException(
            status_code=500, detail=f"An error occurred while querying BigQuery: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {e}"
        )


@app.get("/", tags=["Health Check"])
def read_root():
    """A public health check endpoint to confirm the API is running."""
    return {"status": "ok"}
