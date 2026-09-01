from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    String,
    create_engine,
    event,
)
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


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


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
    username: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255))

    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    picture: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        primary_key=True,
    )

    bio: Mapped[str] = mapped_column(String(2048), default="")
    grade: Mapped[str] = mapped_column(String(64), default="")
    school: Mapped[str] = mapped_column(String(128), default="")

    languages: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
    )
    preferences: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# 4. Lifecycle helpers.



def get_session():
    """FastAPI dependency: yields a Session, guarantees it closes."""
    with SessionLocal() as session:
        yield session
