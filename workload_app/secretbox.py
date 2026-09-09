"""A small sealed box, so an administrator can read a password back.

Passwords are stored twice and for two different reasons.  ``password_hash``
is what signs you in: PBKDF2, one-way, and the only thing ``verify`` consults.
Beside it sits a *sealed* copy, which exists solely so the Admin tab can show
an administrator the password they handed out.

Sealed, not plain: the key is a file next to the database, mode 0600, and no
part of it is in the database.  A copy of ``accounts.db`` -- a backup that went
astray, a download of the data folder -- is therefore not a list of everyone's
passwords.  Somebody with the key file *and* the database can read them, which
is the point of the feature and is stated plainly in the app.

The construction is HMAC-SHA256 in counter mode with encrypt-then-MAC, which
the standard library can do.  There is no third-party cryptography here and no
need for any: the threat is a stray copy of one file, not an adversary with
the key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Optional

KEY_BYTES = 32
NONCE_BYTES = 16
TAG_BYTES = 32
KEY_NAME = "secret.key"


def key_file(data_dir: Path) -> Path:
    """Make the key on first use, readable by nobody else, and keep it."""
    path = Path(data_dir) / KEY_NAME
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written 0600 from the start: never briefly world-readable.
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(handle, secrets.token_bytes(KEY_BYTES))
        finally:
            os.close(handle)
    return path


def load_key(data_dir: Path) -> bytes:
    return key_file(data_dir).read_bytes()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"),
                        hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _subkeys(key: bytes, nonce: bytes):
    enc = hmac.new(key, b"encrypt" + nonce, hashlib.sha256).digest()
    mac = hmac.new(key, b"authenticate" + nonce, hashlib.sha256).digest()
    return enc, mac


def seal(key: bytes, plaintext: str) -> str:
    """Text in, one base64 string out."""
    raw = str(plaintext).encode("utf-8")
    nonce = secrets.token_bytes(NONCE_BYTES)
    enc, mac = _subkeys(key, nonce)
    cipher = bytes(a ^ b for a, b in zip(raw, _keystream(enc, nonce, len(raw))))
    tag = hmac.new(mac, nonce + cipher, hashlib.sha256).digest()
    return base64.b64encode(nonce + cipher + tag).decode("ascii")


def unseal(key: bytes, blob: Optional[str]) -> Optional[str]:
    """The text back, or None if this key never sealed it."""
    if not blob:
        return None
    try:
        raw = base64.b64decode(str(blob), validate=True)
    except (ValueError, TypeError):
        return None
    if len(raw) < NONCE_BYTES + TAG_BYTES:
        return None
    nonce = raw[:NONCE_BYTES]
    cipher = raw[NONCE_BYTES:-TAG_BYTES]
    tag = raw[-TAG_BYTES:]
    enc, mac = _subkeys(key, nonce)
    if not hmac.compare_digest(tag, hmac.new(mac, nonce + cipher,
                                             hashlib.sha256).digest()):
        return None                     # a different key, or a changed blob
    try:
        return bytes(a ^ b for a, b in
                     zip(cipher, _keystream(enc, nonce, len(cipher)))
                     ).decode("utf-8")
    except UnicodeDecodeError:          # pragma: no cover - tag rules this out
        return None
