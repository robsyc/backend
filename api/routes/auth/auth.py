import os
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from .schemas import RegistrationForm, Token
from ...models.social import User
from neomodel import adb
from .services import (
    get_password_hash, 
    verify_password, 
    create_access_token, 
    create_refresh_token, 
    get_current_user,
    create_verification_token,
    send_verification_email,
    send_warning_email,
    verify_email_token
)
from jose import JWTError, jwt


load_dotenv()
router = APIRouter(tags=["auth"])
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(form: RegistrationForm):
    """
    User registration endpoint. Checks if username/email is already taken and creates a new user.
    Args:
        form (RegistrationForm): User registration form.
    Returns:
        dict: A success message.
    """
    # Check if username is already taken
    if await User.nodes.get_or_none(username=form.username):
        raise HTTPException(status_code=400, detail="Username already taken")
    
    # Check if email is already taken (without letting the client know)
    if await User.nodes.get_or_none(email=form.email):
        await send_warning_email(form.email, form.username)
    else:
        # Create user
        hashed_password = get_password_hash(form.password)
        user = await User(
            username=form.username, 
            email=form.email, 
            hashed_password=hashed_password
        ).save()
        token = create_verification_token(user.email)
        await send_verification_email(
            user.email, 
            user.username, 
            token
        )
    return {
        "message": "User registration successful, please check your email",
        "email": form.email
        }


@router.get("/verify/{token}")
async def verify_email(token: str):
    """
    Email verification endpoint. Checks if the token is valid and marks the user as verified.
    Args:
        token (str): Verification token send to user's email upon registration.
    Returns:
        dict: A success message.
    """
    email = await verify_email_token(token)
    user = await User.nodes.get_or_none(email=email)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_verified = True
    await user.save()
    return {"message": "Email verified, you can now login"}


@router.post("/token", response_model=Token)
async def login_for_access_token(form: OAuth2PasswordRequestForm = Depends()):
    """
    User login endpoint. Checks if the user exists and the password is correct.
    Args:
        form (OAuth2PasswordRequestForm): User login form.
    Returns:
        dict: An access token and refresh token.
    """
    is_email = "@" in form.username
    if is_email:
        user = await User.nodes.get_or_none(email=form.username)
    else:
        user = await User.nodes.get_or_none(username=form.username)

    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=401, 
            detail="Incorrect identifier or password",
            headers={"WWW-Authenticate": "Bearer"}
            )
    if not user.is_verified:
        raise HTTPException(
            status_code=401,
            detail="Email not verified",
            headers={"WWW-Authenticate": "Bearer"}
        )
    data = {
        "sub": user.uid,
        "username": user.username
    }
    return {
        "access_token": create_access_token(data=data), 
        "refresh_token": create_refresh_token(data=data),
        "token_type": "bearer"}


@router.post("/refresh", response_model=Token)
async def refresh_access_token(refresh_token: str):
    """
    Refresh access token endpoint. Checks if the refresh token is valid and returns a new access token.
    Args:
        refresh_token (str): Refresh token.
    Returns:
        dict: An access token and refresh token.
    """
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: str = payload.get("sub")
        username: str = payload.get("username")
        token_type: str = payload.get("type")
        if username is None or token_type != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    data = {
        "sub": sub,
        "username": username
    }
    return {
        "access_token": create_access_token(data=data),
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.get("/me")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "email": current_user.email
    }