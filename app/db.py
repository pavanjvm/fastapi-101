from sqlalchemy import String, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
)

from app.config import settings

# 1. Engine: connection pool + SQL dialect. Lazy — does not connect yet.
engine = create_engine(
    settings.database_url,
    echo=True,
)

# 2. Factory that produces one Session (= one transaction) per request.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


# 3. Registry. Every subclass registers its table into Base.metadata.
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


# 4. Lifecycle helpers.
def init_db() -> None:
    """Create any tables that don't exist yet. Idempotent."""
    Base.metadata.create_all(bind=engine)


def get_session():
    """FastAPI dependency: yields a Session, guarantees it closes."""
    with SessionLocal() as session:
        yield session
