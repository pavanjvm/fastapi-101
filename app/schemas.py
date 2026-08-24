from pydantic import BaseModel,Field

class UserOut(BaseModel):
    id: int
    name: str
    model_config = {"from_attributes":True}


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8,  max_length=128)





    