from pydantic import BaseModel

class UserOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes":True}
    