"""Authentication routes for ViGenAiR."""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Dict

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory token storage (simple approach)
active_tokens: Dict[str, datetime] = {}
TOKEN_EXPIRY_HOURS = 24


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


def cleanup_expired_tokens():
    """Remove expired tokens from storage."""
    now = datetime.now()
    expired = [token for token, expiry in active_tokens.items() if expiry < now]
    for token in expired:
        del active_tokens[token]


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Login endpoint.

    Validates credentials and returns a token if successful.
    """
    cleanup_expired_tokens()

    if not verify_credentials(request.username, request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Generate token
    token = secrets.token_urlsafe(32)
    expiry = datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)
    active_tokens[token] = expiry

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
        if token in active_tokens:
            del active_tokens[token]
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

    cleanup_expired_tokens()

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No authorization token provided")

    token = authorization.split(" ")[1]

    if token not in active_tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {"valid": True, "expires_at": active_tokens[token].isoformat()}


def verify_auth(authorization: str = Header(None)):
    """
    Dependency to verify authentication on protected routes.

    Usage: Add as dependency to any route that needs auth.
    """
    if not os.environ.get("AUTH_CREDENTIAL"):
        # No auth configured, allow all
        return True

    cleanup_expired_tokens()

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No authorization token provided")

    token = authorization.split(" ")[1]

    if token not in active_tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return True
