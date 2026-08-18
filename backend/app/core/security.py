"""Пароли и токены сессий.

Пароли хранятся как scrypt-хеш со случайной солью — алгоритм есть в
стандартной библиотеке, дополнительных зависимостей не нужно. Сравнение
хешей идёт по времени-постоянному compare_digest, чтобы по скорости
ответа нельзя было подбирать.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# Параметры scrypt: компромисс между стойкостью и временем входа (~100 мс).
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LENGTH = 32
SALT_BYTES = 16

PREFIX = "scrypt"


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Пароль должен быть не короче 8 символов.")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_LENGTH
    )
    return f"{PREFIX}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, n, r, p, salt_hex, digest_hex = stored.split("$")
        if prefix != PREFIX:
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest_hex)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_fingerprint(token: str) -> str:
    """В базе храним не сам токен, а его хеш — как и пароль."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
