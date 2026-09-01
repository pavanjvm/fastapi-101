from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.schemas import UserOut,UserCreate

from app.db import User,get_session
from app.config import settings
from app.security import hash_password



app = FastAPI(title = settings.app_name)
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
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="username taken")
    
    return user
