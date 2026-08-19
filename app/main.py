from fastapi import FastAPI, Depends, HTTPException
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session

from app.db import User,get_session, init_db
from app.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title = settings.app_name, lifespan=lifespan)

@app.get("/health")
def health() -> dict[str,str]:
    return {"status":"ok"}

@app.get("/users/{user_id}")
def read_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User,user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {"id": user.id, "name": user.name}

