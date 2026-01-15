# Copyright 2024 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""FastAPI entry point for ViGenAiR."""

import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes import upload, status, segments, render, files, jobs
from api.models.responses import HealthResponse
from db.mongodb import init_db, close_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="ViGenAiR API",
    description="Video Generation AI Repurposing API - Transform long-form video ads into shorter variants",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# CORS middleware - configure appropriately for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(upload.router, prefix="/api/v1/videos", tags=["videos"])
app.include_router(status.router, prefix="/api/v1/videos", tags=["status"])
app.include_router(segments.router, prefix="/api/v1/videos", tags=["segments"])
app.include_router(render.router, prefix="/api/v1/videos", tags=["render"])
app.include_router(files.router, prefix="/api/v1/files", tags=["files"])


@app.get("/", tags=["root"])
async def root():
    """Root endpoint - API information."""
    return {
        "name": "ViGenAiR API",
        "version": "1.0.0",
        "docs": "/api/docs",
        "health": "/health"
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy")


@app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
async def api_health_check():
    """API health check endpoint."""
    return HealthResponse(status="healthy")


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("ViGenAiR API starting up...")

    # Verify required environment variables - FAIL if missing
    required_vars = ["S3_BUCKET", "GOOGLE_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]

    if missing_vars:
        error_msg = f"FATAL: Missing required environment variables: {missing_vars}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info("All required environment variables are set")

    # Initialize MongoDB
    try:
        await init_db()
        logger.info("MongoDB connection established")
    except Exception as e:
        error_msg = f"FATAL: Failed to connect to MongoDB: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Initialize Google AI and verify connectivity
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    try:
        import google.generativeai as genai
        genai.configure(api_key=google_api_key)

        # Verify the API key works by listing models
        models = list(genai.list_models())
        logger.info(f"Google AI Studio SDK initialized - {len(models)} models available")
    except Exception as e:
        error_msg = f"FATAL: Failed to initialize Google AI SDK: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Verify S3 connectivity
    try:
        import boto3
        s3_client = boto3.client(
            's3',
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1")
        )
        s3_client.head_bucket(Bucket=os.environ.get("S3_BUCKET"))
        logger.info(f"S3 connectivity verified - bucket: {os.environ.get('S3_BUCKET')}")
    except Exception as e:
        error_msg = f"FATAL: Failed to connect to S3: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info("ViGenAiR API startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("ViGenAiR API shutting down...")
    await close_db()
    logger.info("MongoDB connection closed")
