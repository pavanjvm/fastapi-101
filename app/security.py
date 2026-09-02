from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.config import settings

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return password_hasher.verify(plain_password, password_hash)


def create_access_token(
    subject: int | str,
    expires_delta: timedelta | None = None,
) -> str:
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expire_minutes)

    expires_at = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(subject),
        "exp": expires_at,
    }

    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

