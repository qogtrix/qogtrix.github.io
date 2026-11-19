"""Password hashing + signed session tokens. Stdlib only.

Passwords: PBKDF2-HMAC-SHA256, 200,000 iterations, 16-byte random salt.
Tokens: HMAC-SHA256 signed token  ``base64url(payload).base64url(sig)``
where payload = {"sub": user_id, "sid": session_id, "exp": unix, "iat": unix}.
The server secret comes from AIELAB_SECRET, or from backend/.secret
(generated once, mode 0600) for local dev. Rotating the secret
invalidates every session — that is intentional.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

ITERATIONS = 200_000
TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def get_secret() -> bytes:
    env = os.environ.get("AIELAB_SECRET")
    if env:
        return env.encode()
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, ".secret")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()
    secret = secrets.token_bytes(32)
    with open(path, "wb") as f:
        f.write(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret


def create_token(secret: bytes, user_id: str, session_id: str) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "sid": session_id, "iat": now,
               "exp": now + TOKEN_TTL_SECONDS}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(secret, raw, hashlib.sha256).digest()
    return _b64e(raw) + "." + _b64e(sig)


def verify_token(secret: bytes, token: str):
    """Return payload dict, or None if bad signature / expired / malformed."""
    try:
        raw_b64, sig_b64 = token.split(".")
        raw, sig = _b64d(raw_b64), _b64d(sig_b64)
        expected = hmac.new(secret, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(raw)
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def new_api_key() -> tuple[str, str, str]:
    """Return (display_key, prefix, sha256_hex). Only the hash is stored."""
    raw = secrets.token_hex(24)
    display = "aielab_" + raw
    return display, display[:12], hashlib.sha256(display.encode()).hexdigest()
