from pydantic import BaseModel,Field

class UserOut(BaseModel):
    id: int
    username: str
    name: str | None
    model_config = {"from_attributes":True}


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str





    