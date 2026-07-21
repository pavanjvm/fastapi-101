from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/users", tags = ["users"])

class UserProfile(BaseModel):
    uid:str
    name:str
    email:str | None = None

@router.get("/me", response_model=UserProfile)
def get_currnet_user_profile() -> UserProfile:
    return UserProfile(
        uid = "1",
        name = "pavan",
    )
    
    

