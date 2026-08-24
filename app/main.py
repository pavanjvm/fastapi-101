from fastapi import FastAPI, Depends, HTTPException
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from app.schemas import UserOut,UserCreate

from app.db import User,get_session, init_db
from app.config import settings
from app.security import hash_password

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title = settings.app_name, lifespan=lifespan)

@app.get("/health")
def health() -> dict[str,str]:
    return {"status":"ok"}

@app.get("/users/{user_id}", response_model = UserOut)
def read_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User,user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user 

@app.post("/register",response_model=UserOut, status_code=201)
def register(payload:UserCreate, session:Session = Depends(get_session)):
    user=User(
        username = payload.username,
        password_hash = hash_password(payload.password),
    )

    session.add(user)
    session.commit()
    return user
