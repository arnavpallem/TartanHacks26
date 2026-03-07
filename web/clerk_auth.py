"""
Clerk Authentication middleware for FastAPI.
Verifies Clerk session tokens (JWTs) from the __session cookie.
Extracts user identity (Andrew ID) from verified claims.
"""
import logging
from typing import Optional
from functools import lru_cache

import jwt
from jwt import PyJWKClient

from config.settings import ClerkConfig

logger = logging.getLogger(__name__)

# Cache the JWKS client to avoid re-fetching keys on every request
_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    """Get or create the JWKS client for Clerk token verification."""
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"https://{ClerkConfig.FRONTEND_API}/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
        logger.info(f"Initialized JWKS client: {jwks_url}")
    return _jwks_client


def verify_session_token(token: str) -> Optional[dict]:
    """
    Verify a Clerk session token (JWT) and return the decoded claims.
    
    Args:
        token: The JWT from the __session cookie
        
    Returns:
        Decoded claims dict if valid, None if invalid
    """
    if not ClerkConfig.PUBLISHABLE_KEY:
        logger.warning("Clerk not configured — skipping auth")
        return None
    
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={
                "verify_exp": True,
                "verify_aud": False,  # Clerk doesn't set audience by default
            },
        )
        return claims
    
    except jwt.ExpiredSignatureError:
        logger.debug("Session token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Invalid session token: {e}")
        return None
    except Exception as e:
        logger.error(f"Error verifying session token: {e}")
        return None


def get_andrew_id_from_claims(claims: dict) -> Optional[str]:
    """
    Extract Andrew ID from Clerk JWT claims.
    
    Clerk stores the primary email in the session claims.
    Andrew emails are formatted as: andrewid@andrew.cmu.edu
    
    Args:
        claims: Decoded JWT claims
        
    Returns:
        Andrew ID string, or None
    """
    # Clerk stores email info in different places depending on config
    # Check custom claims, then standard fields
    
    # Custom session claims (if configured in Clerk dashboard)
    email = claims.get("email")
    
    # Standard Clerk claims
    if not email:
        # The primary email may be in metadata
        metadata = claims.get("public_metadata", {})
        email = metadata.get("email")
    
    if not email:
        # Fall back to subject (user ID) - not ideal but works as identifier
        sub = claims.get("sub", "")
        logger.debug(f"No email in claims, using sub: {sub}")
        return sub
    
    # Extract Andrew ID from email: andrewid@andrew.cmu.edu → andrewid
    if "@andrew.cmu.edu" in email:
        return email.split("@")[0].lower()
    elif "@cmu.edu" in email:
        return email.split("@")[0].lower()
    
    # Use the full email prefix as fallback
    return email.split("@")[0].lower()


class ClerkUser:
    """Represents an authenticated Clerk user."""
    
    def __init__(self, claims: dict):
        self.claims = claims
        self.user_id = claims.get("sub", "")
        self.andrew_id = get_andrew_id_from_claims(claims)
        self.email = claims.get("email", "")
        self.session_id = claims.get("sid", "")
    
    def __repr__(self):
        return f"<ClerkUser {self.andrew_id or self.user_id}>"


def get_current_user_from_cookie(cookies: dict) -> Optional[ClerkUser]:
    """
    Extract and verify the current user from request cookies.
    
    Args:
        cookies: Request cookies dict
        
    Returns:
        ClerkUser if authenticated, None otherwise
    """
    token = cookies.get("__session")
    if not token:
        return None
    
    claims = verify_session_token(token)
    if not claims:
        return None
    
    return ClerkUser(claims)
