# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import users

app = FastAPI(
    title="PricePulse API",
    description="Backend API for the PricePulse platform.",
    version="1.0.0"
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
    allow_methods=["*"], # Allows all methods (GET, POST, etc.)
    allow_headers=["*"], # Allows all headers
)


# --- API Routers ---
# Include the user and authentication routes
app.include_router(users.router, prefix="/api/v1", tags=["Users"])


@app.get("/", tags=["Health Check"])
def read_root():
    """A public health check endpoint to confirm the API is running."""
    return {"status": "ok"}