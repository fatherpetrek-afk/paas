from __future__ import annotations

import hashlib
import hmac
import secrets


def only_digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def normalize_username(value: str) -> str:
    return only_digits(value)


def normalize_password(value: str) -> str:
    return only_digits(value)


def valid_username(value: str) -> bool:
    return len(normalize_username(value)) == 8


def valid_password(value: str) -> bool:
    return len(normalize_password(value)) == 16


def group_digits(value: str, size: int = 4) -> str:
    digits = only_digits(value)
    if not digits:
        return ""
    return " ".join(digits[i : i + size] for i in range(0, len(digits), size))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = (stored or "").split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def normalize_worker_label(value: str) -> str:
    return " ".join((value or "").split())


def is_platform_label(value: str) -> bool:
    return normalize_worker_label(value).casefold() == "dev"
