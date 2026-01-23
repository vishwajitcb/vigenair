"""Authentication routes for ViGenAiR."""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Dict

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import redis

logger = logging.getLogger(__name__)

router = APIRouter()

# Redis connection for shared token storage across workers
redis_client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "redis"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    db=0,
    decode_responses=True
)

TOKEN_EXPIRY_HOURS = 24
TOKEN_EXPIRY_SECONDS = TOKEN_EXPIRY_HOURS * 3600


class LoginRequest(BaseModel):
    """Login request model."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response model."""
    token: str
    expires_in: int = TOKEN_EXPIRY_HOURS * 3600


def hash_password(password: str) -> str:
    """Hash password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_credentials(username: str, password: str) -> bool:
    """Verify username and password against env credentials."""
    auth_cred = os.environ.get("AUTH_CREDENTIAL", "")

    logger.info(f"AUTH_CREDENTIAL present: {bool(auth_cred)}")

    if not auth_cred:
        # If no auth configured, allow all (open mode)
        logger.warning("No AUTH_CREDENTIAL configured - allowing all logins!")
        return True

    # Parse credential (format: username:hashed_password)
    try:
        expected_username, expected_password_hash = auth_cred.split(":", 1)
        provided_password_hash = hash_password(password)

        logger.info(f"Login attempt - Username match: {username == expected_username}, Password hash match: {provided_password_hash == expected_password_hash}")
        logger.debug(f"Expected hash: {expected_password_hash}")
        logger.debug(f"Provided hash: {provided_password_hash}")

        return username == expected_username and provided_password_hash == expected_password_hash
    except Exception as e:
        logger.error(f"Error parsing AUTH_CREDENTIAL: {e}")
        return False


def store_token(token: str, expiry_seconds: int = TOKEN_EXPIRY_SECONDS):
    """Store token in Redis with expiration."""
    redis_client.setex(f"auth_token:{token}", expiry_seconds, "1")


def verify_token_exists(token: str) -> bool:
    """Check if token exists in Redis."""
    return redis_client.exists(f"auth_token:{token}") > 0


def delete_token(token: str):
    """Delete token from Redis."""
    redis_client.delete(f"auth_token:{token}")


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Login endpoint.

    Validates credentials and returns a token if successful.
    """
    if not verify_credentials(request.username, request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Generate token and store in Redis
    token = secrets.token_urlsafe(32)
    store_token(token, TOKEN_EXPIRY_SECONDS)

    logger.info(f"User '{request.username}' logged in successfully")

    return LoginResponse(token=token)


@router.post("/logout")
async def logout(authorization: str = Header(None)):
    """
    Logout endpoint.

    Invalidates the provided token.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        if verify_token_exists(token):
            delete_token(token)
            logger.info("User logged out successfully")
            return {"message": "Logged out successfully"}

    return {"message": "No active session"}


@router.get("/verify")
async def verify_token(authorization: str = Header(None)):
    """
    Token verification endpoint.

    Checks if a token is valid.
    """
    if not os.environ.get("AUTH_CREDENTIAL"):
        # No auth configured, always valid
        return {"valid": True}

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No authorization token provided")

    token = authorization.split(" ")[1]

    if not verify_token_exists(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Get TTL from Redis
    ttl = redis_client.ttl(f"auth_token:{token}")
    expires_at = datetime.now() + timedelta(seconds=ttl) if ttl > 0 else datetime.now()

    return {"valid": True, "expires_at": expires_at.isoformat()}


def verify_auth(authorization: str = Header(None)):
    """
    Dependency to verify authentication on protected routes.

    Usage: Add as dependency to any route that needs auth.
    """
    if not os.environ.get("AUTH_CREDENTIAL"):
        # No auth configured, allow all
        return True

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No authorization token provided")

    token = authorization.split(" ")[1]

    if not verify_token_exists(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return True
