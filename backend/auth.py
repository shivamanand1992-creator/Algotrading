import os
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWT secret
# ---------------------------------------------------------------------------
_JWT_SECRET_ENV = os.getenv("JWT_SECRET", "")
if _JWT_SECRET_ENV:
    JWT_SECRET = _JWT_SECRET_ENV
else:
    JWT_SECRET = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET env var is not set. A random secret has been generated for this "
        "process. All existing tokens will be invalidated on every restart. "
        "Set JWT_SECRET to a stable value in production."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

# ---------------------------------------------------------------------------
# Password configuration
# ---------------------------------------------------------------------------
_AUTH_PASSWORD_ENV = os.getenv("AUTH_PASSWORD", "")
if _AUTH_PASSWORD_ENV:
    AUTH_PASSWORD = _AUTH_PASSWORD_ENV
else:
    AUTH_PASSWORD = "changeme"
    logger.warning(
        "AUTH_PASSWORD env var is not set. Using the default password 'changeme'. "
        "This is insecure — set AUTH_PASSWORD to a strong password in production."
    )

USERNAME = "admin"

# ---------------------------------------------------------------------------
# Passlib bcrypt context (used for verify only; hashing is optional)
# ---------------------------------------------------------------------------
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# OAuth2 scheme
# ---------------------------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def create_access_token(data: dict) -> str:
    """Return a signed HS256 JWT with an 8-hour expiry."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and validate a JWT.  Raises HTTPException(401) on any failure."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise credentials_exception


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """FastAPI dependency — returns the authenticated username string."""
    payload = verify_token(token)
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


def authenticate_user(password: str) -> bool:
    """Return True if *password* matches AUTH_PASSWORD.

    Supports two modes:
    - If AUTH_PASSWORD looks like a bcrypt hash (starts with ``$2b$`` or
      ``$2a$``), use passlib's constant-time bcrypt verify.
    - Otherwise perform a plain string comparison.  This allows operators to
      set a human-readable password in a Railway / Docker env var without
      needing to pre-hash it.
    """
    stored = AUTH_PASSWORD
    if stored.startswith(("$2b$", "$2a$", "$2y$")):
        try:
            return _pwd_context.verify(password, stored)
        except Exception:
            return False
    return secrets.compare_digest(password, stored)
