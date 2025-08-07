# PricePulse Backend - File & Folder Structure

## Overview

This document outlines the recommended folder structure for the PricePulse FastAPI backend repository. This structure is designed to complement the frontend implementation and work alongside separate repositories for data pipeline and ML/data science tasks.

## Repository Structure

```
price-pulse-backend/
├── .github/                          # GitHub workflows and templates
│   └── workflows/
│       ├── ci.yml                    # Continuous Integration
│       ├── cd.yml                    # Continuous Deployment
│       └── security.yml              # Security scanning
│
├── app/                              # Main FastAPI application
│   ├── __init__.py
│   ├── main.py                       # FastAPI app entry point
│   ├── config.py                     # Configuration settings
│   │
│   ├── api/                          # API route handlers
│   │   ├── __init__.py
│   │   ├── deps.py                   # Dependencies (auth, db, etc.)
│   │   │
│   │   └── v1/                       # API version 1 routes
│   │       ├── __init__.py
│   │       ├── auth.py               # Authentication endpoints
│   │       ├── users.py              # User management endpoints
│   │       ├── products.py           # Product-related endpoints
│   │       ├── search.py             # Search & filtering endpoints
│   │       ├── categories.py         # Categories & trending endpoints
│   │       ├── analytics.py          # Analytics & forecasting endpoints
│   │       ├── notifications.py     # Notification endpoints
│   │       ├── admin.py              # Admin dashboard endpoints
│   │       ├── static.py             # Static pages endpoints
│   │       └── websocket.py          # WebSocket connections
│   │
│   ├── core/                         # Core functionality
│   │   ├── __init__.py
│   │   ├── security.py               # JWT, password hashing
│   │   ├── middleware.py             # Custom middleware
│   │   ├── exceptions.py             # Custom exception handlers
│   │   ├── logging.py                # Logging configuration
│   │   └── rate_limiting.py          # API rate limiting
│   │
│   ├── db/                           # Database related code
│   │   ├── __init__.py
│   │   ├── session.py                # Database session management
│   │   ├── base.py                   # SQLAlchemy base classes
│   │   │
│   │   ├── models/                   # SQLAlchemy models
│   │   │   ├── __init__.py
│   │   │   ├── user.py               # User-related models
│   │   │   ├── warehouse.py          # Data warehouse models
│   │   │   ├── operational.py        # Operational database models
│   │   │   └── relationships.py      # Model relationships
│   │   │
│   │   └── repositories/             # Data access layer
│   │       ├── __init__.py
│   │       ├── base.py               # Base repository class
│   │       ├── user.py               # User repository
│   │       ├── product.py            # Product repository
│   │       ├── analytics.py          # Analytics repository
│   │       └── admin.py              # Admin repository
│   │
│   ├── schemas/                      # Pydantic schemas
│   │   ├── __init__.py
│   │   ├── user.py                   # User schemas
│   │   ├── product.py                # Product schemas
│   │   ├── search.py                 # Search schemas
│   │   ├── analytics.py              # Analytics schemas
│   │   ├── notification.py           # Notification schemas
│   │   ├── admin.py                  # Admin schemas
│   │   └── common.py                 # Common/shared schemas
│   │
│   ├── services/                     # Business logic services
│   │   ├── __init__.py
│   │   ├── auth_service.py           # Authentication business logic
│   │   ├── user_service.py           # User management logic
│   │   ├── product_service.py        # Product-related logic
│   │   ├── search_service.py         # Search & filtering logic
│   │   ├── analytics_service.py      # Analytics & forecasting logic
│   │   ├── notification_service.py   # Notification logic
│   │   ├── admin_service.py          # Admin functionality logic
│   │   ├── cache_service.py          # Caching logic
│   │   └── email_service.py          # Email sending logic
│   │
│   ├── utils/                        # Utility functions
│   │   ├── __init__.py
│   │   ├── helpers.py                # General helper functions
│   │   ├── validators.py             # Custom validators
│   │   ├── formatters.py             # Data formatting utilities
│   │   ├── constants.py              # Application constants
│   │   └── enums.py                  # Enumeration classes
│   │
│   └── workers/                      # Background task workers
│       ├── __init__.py
│       ├── celery_app.py             # Celery configuration
│       ├── notification_worker.py    # Notification background tasks
│       ├── analytics_worker.py       # Analytics processing tasks
│       └── data_sync_worker.py       # Data synchronization tasks
│
├── alembic/                          # Database migrations
│   ├── env.py                        # Alembic environment
│   ├── script.py.mako                # Migration template
│   └── versions/                     # Migration files
│       └── 001_initial_migration.py
│
├── tests/                            # Test suite
│   ├── __init__.py
│   ├── conftest.py                   # Pytest configuration
│   ├── test_main.py                  # Main app tests
│   │
│   ├── api/                          # API endpoint tests
│   │   ├── __init__.py
│   │   ├── test_auth.py              # Authentication tests
│   │   ├── test_users.py             # User endpoint tests
│   │   ├── test_products.py          # Product endpoint tests
│   │   ├── test_search.py            # Search endpoint tests
│   │   ├── test_analytics.py         # Analytics endpoint tests
│   │   └── test_admin.py             # Admin endpoint tests
│   │
│   ├── services/                     # Service layer tests
│   │   ├── __init__.py
│   │   ├── test_auth_service.py
│   │   ├── test_product_service.py
│   │   └── test_notification_service.py
│   │
│   ├── utils/                        # Utility function tests
│   │   ├── __init__.py
│   │   └── test_helpers.py
│   │
│   └── fixtures/                     # Test data fixtures
│       ├── __init__.py
│       ├── users.py                  # User test fixtures
│       └── products.py               # Product test fixtures
│
├── scripts/                          # Utility scripts
│   ├── init_db.py                    # Database initialization
│   ├── seed_data.py                  # Database seeding
│   ├── migrate.py                    # Migration helpers
│   └── health_check.py               # Health check script
│
├── docs/                             # API documentation
│   ├── api_docs.md                   # API documentation
│   ├── deployment.md                 # Deployment guide
│   ├── development.md                # Development setup
│   └── architecture.md               # System architecture
│
├── docker/                           # Docker configuration
│   ├── Dockerfile                    # Main application Dockerfile
│   ├── Dockerfile.worker             # Background worker Dockerfile
│   ├── docker-compose.yml            # Local development setup
│   ├── docker-compose.prod.yml       # Production setup
│   └── nginx.conf                    # Nginx configuration
│
├── .env.example                      # Environment variables example
├── .gitignore                        # Git ignore rules
├── .dockerignore                     # Docker ignore rules
├── requirements.txt                  # Python dependencies
├── requirements-dev.txt              # Development dependencies
├── pyproject.toml                    # Python project configuration
├── alembic.ini                       # Alembic configuration
├── pytest.ini                        # Pytest configuration
├── README.md                         # Project documentation
└── CHANGELOG.md                      # Version changelog
```

## Directory Explanations

### `/app` - Main Application

- **`main.py`**: FastAPI application entry point with CORS, middleware setup
- **`config.py`**: Environment variables, database URLs, external service configs
- **`api/`**: All REST API endpoints organized by feature/version
- **`core/`**: Cross-cutting concerns (security, middleware, exceptions)
- **`db/`**: Database models, repositories, and session management
- **`schemas/`**: Pydantic models for request/response validation
- **`services/`**: Business logic layer (separated from API endpoints)
- **`utils/`**: Utility functions, helpers, constants
- **`workers/`**: Background task processing (Celery/Redis)

### `/api/v1` - API Endpoints

Based on your frontend routes, organized by feature:

- **`auth.py`**: Login, registration, JWT handling, OAuth
- **`users.py`**: User profiles, favorites, settings, dashboard
- **`products.py`**: Product details, price history, forecasting
- **`search.py`**: Product search, filters, autocomplete
- **`categories.py`**: Categories, trending, deals, new arrivals
- **`analytics.py`**: Advanced analytics, market insights, admin metrics
- **`notifications.py`**: Email alerts, push notifications, preferences
- **`admin.py`**: Pipeline monitoring, user management, system admin
- **`static.py`**: Help, contact, privacy, terms, FAQ pages
- **`websocket.py`**: Real-time notifications, live updates

### `/services` - Business Logic

Each service handles specific domain logic:

- **`auth_service.py`**: JWT generation, OAuth integration, role management
- **`product_service.py`**: Product matching, price calculations, comparisons
- **`search_service.py`**: Search algorithms, filtering, ranking
- **`analytics_service.py`**: Forecasting models, anomaly detection, insights
- **`notification_service.py`**: Email templates, push notifications, scheduling
- **`cache_service.py`**: Redis caching strategies, cache invalidation

### `/db` - Database Layer

- **`models/`**: SQLAlchemy ORM models matching your database schema
- **`repositories/`**: Data access patterns, query optimization
- **`session.py`**: Database connection management, transaction handling

### `/tests` - Testing

Comprehensive test coverage for all layers:

- **API tests**: Endpoint behavior, authentication, validation
- **Service tests**: Business logic, edge cases, integrations
- **Database tests**: Repository methods, query optimization
- **Integration tests**: End-to-end workflows

## 🔧 Key Configuration Files

### `requirements.txt`

```txt
fastapi[all]==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
alembic==1.12.1
pydantic==2.5.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.6
redis==5.0.1
celery==5.3.4
httpx==0.25.2
pytest==7.4.3
pytest-asyncio==0.21.1
python-dotenv==1.0.0
```

### `docker-compose.yml`

```yaml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db/priceplus
      - REDIS_URL=redis://redis:6379
    depends_on:
      - db
      - redis

  worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    depends_on:
      - redis
      - db

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: priceplus
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass

  redis:
    image: redis:7-alpine
```

## Integration Points

### With Frontend

- **API Endpoints**: Direct mapping to frontend pages/components
- **WebSocket**: Real-time notifications to React components
- **Authentication**: JWT tokens, OAuth integration
- **File Uploads**: Product images, user avatars

### With Data Pipeline Repository

- **Database Access**: Read from data warehouse populated by pipeline
- **Pipeline Status**: Monitor ETL job status via API
- **Data Quality**: Validate data consistency

### With Data Science Repository

- **Model Integration**: Load ML models for predictions
- **Feature Store**: Access preprocessed features
- **Model Monitoring**: Track prediction accuracy

## Development Workflow

1. **Local Setup**:

   ```bash
   # Clone repository
   git clone <backend-repo>
   cd price-pulse-backend

   # Setup virtual environment
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or venv\Scripts\activate  # Windows

   # Install dependencies
   pip install -r requirements.txt
   pip install -r requirements-dev.txt

   # Setup environment
   cp .env.example .env

   # Run migrations
   alembic upgrade head

   # Start development server
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Testing**:

   ```bash
   # Run tests
   pytest

   # Run with coverage
   pytest --cov=app

   # Run specific test category
   pytest tests/api/
   ```

3. **Database Migrations**:

   ```bash
   # Create new migration
   alembic revision --autogenerate -m "Add new table"

   # Apply migrations
   alembic upgrade head

   # Rollback migration
   alembic downgrade -1
   ```

## Security Considerations

- **JWT Authentication**: Secure token handling with refresh tokens
- **Rate Limiting**: API endpoint protection
- **Input Validation**: Pydantic schemas for all inputs
- **SQL Injection Prevention**: SQLAlchemy ORM usage
- **CORS Configuration**: Frontend domain whitelisting
- **Environment Variables**: Secure configuration management

## Performance Optimization

- **Database Indexing**: Optimized queries for search/analytics
- **Redis Caching**: Frequent data caching strategies
- **Connection Pooling**: Database connection optimization
- **Background Tasks**: Asynchronous processing with Celery
- **Response Compression**: Gzip compression for large responses

