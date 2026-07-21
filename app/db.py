from sqlalchemy import String, create_engine
from sqlalchemy.orm import DeclarativeBase,Mapped, mapped_column
from app.config import settings

engine = create_engine(
    settings.database_url,
    echo = True,
)

class Base(DeclarativeBase):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key= True)
