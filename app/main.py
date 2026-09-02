from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import User, get_session
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserOut
from app.security import create_access_token, hash_password, verify_password

app = FastAPI(title=settings.app_name)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/users/{user_id}", response_model=UserOut)
def read_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@app.post("/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, session: Session = Depends(get_session)):
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
    )

    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="username taken")
    return user


@app.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.username == payload.username))

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
    }
