from sqlalchemy import String, create_engine
from sqlalchemy.orm import DeclarativeBase,Mapped, mapped_column, sessionmaker
from app.config import settings
from sqlalchemy.orm import Session
engine = create_engine(
    settings.database_url,
    echo = True,
)

class Base(DeclarativeBase):
    pass
class User(Base):
    __tablename__= "users"
    id:Mapped[int] = mapped_column(primary_key=True)

def init_db() -> None:
    Base.metadata.create_all(bind=engine)