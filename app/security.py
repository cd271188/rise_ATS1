"""Password hashing (argon2id), access tokens (JWT) and refresh-token helpers."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("not-a-real-password")  # burns the same time when the user does not exist
COMMON = {"password", "password1", "123456789", "1234567890", "qwertyuiop", "iloveyou12", "administrator"}


def password_problem(pw: str) -> str | None:
    if len(pw) < 10:
        return "must be at least 10 characters"
    if len(pw) > 200:
        return "too long"
    if pw.lower() in COMMON or pw.isdigit() or len(set(pw)) < 4:
        return "too easy to guess"
    return None


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw: str, hashed: str | None) -> bool:
    try:
        return _hasher.verify(hashed or _DUMMY_HASH, pw) and hashed is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_secret() -> str:
    return secrets.token_hex(32)


def create_access_token(user_id: int, secret: str, minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=minutes), "jti": secrets.token_hex(8)}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> int:
    """Return the user id or raise jwt.PyJWTError."""
    data = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    return int(data["sub"])


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()