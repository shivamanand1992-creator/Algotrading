from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.auth import create_access_token, authenticate_user, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

_USERNAME = "admin"


@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate with username + password and return a JWT bearer token."""
    if form_data.username != _USERNAME or not authenticate_user(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(data={"sub": _USERNAME})
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": _USERNAME,
    }


@router.get("/me")
async def me(current_user: str = Depends(get_current_user)):
    """Return the currently authenticated user.  Requires a valid Bearer token."""
    return {"username": current_user, "authenticated": True}
