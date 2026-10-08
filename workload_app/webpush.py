"""Sending a notification to a phone, with nothing but the standard library.

A phone that has turned notifications on hands the app a *subscription*: an
address at its maker's push service (Apple, Google, Mozilla) and two keys of
its own.  Sending is one HTTPS POST to that address, with

* the message encrypted for that phone alone (RFC 8291, "aes128gcm"), so the
  push service carries it without being able to read it; and
* a short signed note saying which server sent it (RFC 8292, "VAPID"), so the
  push service knows the sender is the one the phone subscribed to.

Both need elliptic-curve keys on P-256 and AES-128-GCM.  The host's only
dependency is openpyxl and nothing may be installed there, so the arithmetic is
done here in plain Python.  It is slow by the standards of a crypto library --
milliseconds a message -- which is nothing for a handful of notifications a
day.  The tests check every piece against a real crypto library.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# --------------------------------------------------------------------------
# P-256
# --------------------------------------------------------------------------

_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)

Point = Optional[Tuple[int, int]]


def _add(p: Point, q: Point) -> Point:
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0]:
        if (p[1] + q[1]) % _P == 0:
            return None
        slope = (3 * p[0] * p[0] + _A) * pow(2 * p[1], -1, _P) % _P
    else:
        slope = (q[1] - p[1]) * pow(q[0] - p[0], -1, _P) % _P
    x = (slope * slope - p[0] - q[0]) % _P
    return x, (slope * (p[0] - x) - p[1]) % _P


def _multiply(k: int, point: Point) -> Point:
    result: Point = None
    addend = point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def _on_curve(point: Tuple[int, int]) -> bool:
    x, y = point
    return 0 <= x < _P and 0 <= y < _P and (y * y - (x * x * x + _A * x + _B)) % _P == 0


def public_bytes(private: int) -> bytes:
    """The public key of ``private``, uncompressed: 0x04 || x || y."""
    x, y = _multiply(private, _G)
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def _point(raw: bytes) -> Tuple[int, int]:
    if len(raw) != 65 or raw[0] != 4:
        raise ValueError("not an uncompressed P-256 public key")
    point = (int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big"))
    if not _on_curve(point):
        raise ValueError("the key is not on the curve")
    return point


def new_private() -> int:
    return secrets.randbelow(_N - 1) + 1


def ecdh(private: int, their_public: bytes) -> bytes:
    shared = _multiply(private, _point(their_public))
    if shared is None:                                  # pragma: no cover
        raise ValueError("no shared secret")
    return shared[0].to_bytes(32, "big")


def _rfc6979_k(private: int, digest: bytes) -> int:
    """The signature's one-time number, derived rather than drawn (RFC 6979),
    so a weak random source can never give the key away."""
    x = private.to_bytes(32, "big")
    h = (int.from_bytes(digest, "big") % _N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < _N:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()  # pragma: no cover
        v = hmac.new(k, v, hashlib.sha256).digest()           # pragma: no cover


def sign(private: int, message: bytes) -> bytes:
    """ECDSA P-256 with SHA-256, as JOSE wants it: r || s, 32 bytes each."""
    digest = hashlib.sha256(message).digest()
    z = int.from_bytes(digest, "big")
    while True:
        k = _rfc6979_k(private, digest)
        r = _multiply(k, _G)[0] % _N
        s = pow(k, -1, _N) * (z + r * private) % _N
        if r and s:
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")
        digest = hashlib.sha256(digest).digest()          # pragma: no cover


# --------------------------------------------------------------------------
# AES-128-GCM
# --------------------------------------------------------------------------

def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x11B) if a & 0x100 else a


def _sbox():
    box = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)    # p * 3
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ (q << 1 | q >> 7) ^ (q << 2 | q >> 6) ^ (q << 3 | q >> 5) ^ (q << 4 | q >> 4)
        box[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    box[0] = 0x63
    return box


_SBOX = _sbox()


def _expand(key: bytes):
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        word = list(words[i - 1])
        if i % 4 == 0:
            word = [_SBOX[b] for b in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([a ^ b for a, b in zip(words[i - 4], word)])
    return [sum(words[r * 4:r * 4 + 4], []) for r in range(11)]


def _encrypt_block(rounds, block: bytes) -> bytes:
    s = [b ^ k for b, k in zip(block, rounds[0])]
    for r in range(1, 11):
        s = [_SBOX[b] for b in s]
        # shift rows: the state is column-major, s[c * 4 + row]
        s = [s[((c + row) % 4) * 4 + row] for c in range(4) for row in range(4)]
        if r != 10:
            mixed = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                mixed += [a[i] ^ t ^ _xtime(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = mixed
        s = [b ^ k for b, k in zip(s, rounds[r])]
    return bytes(s)


def _gf_mult(x: int, y: int) -> int:
    r = 0xE1 << 120
    z = 0
    for i in range(127, -1, -1):
        if (y >> i) & 1:
            z ^= x
        x = (x >> 1) ^ r if x & 1 else x >> 1
    return z


def aes128gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
    """Ciphertext followed by the 16-byte tag; no associated data."""
    rounds = _expand(key)
    h = int.from_bytes(_encrypt_block(rounds, bytes(16)), "big")
    j0 = nonce + b"\x00\x00\x00\x01"
    out = bytearray()
    for i in range(0, len(plaintext), 16):
        counter = nonce + struct.pack(">I", 2 + i // 16)
        stream = _encrypt_block(rounds, counter)
        out += bytes(a ^ b for a, b in zip(plaintext[i:i + 16], stream))
    ghash = 0
    padded = bytes(out) + bytes(-len(out) % 16)
    for i in range(0, len(padded), 16):
        ghash = _gf_mult(ghash ^ int.from_bytes(padded[i:i + 16], "big"), h)
    ghash = _gf_mult(ghash ^ (len(out) * 8), h)
    tag = int.from_bytes(_encrypt_block(rounds, j0), "big") ^ ghash
    return bytes(out) + tag.to_bytes(16, "big")


# --------------------------------------------------------------------------
# Web Push
# --------------------------------------------------------------------------

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    text = str(text or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


#: The size of the one record a message is sent in.
RECORD_SIZE = 4096


def encrypt(payload: bytes, p256dh: str, auth: str, *,
            server_private: Optional[int] = None,
            salt: Optional[bytes] = None) -> bytes:
    """``payload`` sealed for one subscription (RFC 8291), ready to POST."""
    ua_public = unb64url(p256dh)
    auth_secret = unb64url(auth)
    if len(auth_secret) < 16:
        raise ValueError("the subscription's auth secret is too short")
    if len(payload) > RECORD_SIZE - 17 - 86:
        raise ValueError("the message is too long to send")
    server_private = server_private or new_private()
    as_public = public_bytes(server_private)
    salt = salt or os.urandom(16)
    secret = ecdh(server_private, ua_public)
    ikm = _hkdf(auth_secret, secret,
                b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    header = salt + struct.pack(">I", RECORD_SIZE) + bytes([len(as_public)]) + as_public
    return header + aes128gcm_encrypt(cek, nonce, payload + b"\x02")


class Keys:
    """The server's own signing key, made once and kept in the data folder."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._private: Optional[int] = None

    @property
    def private(self) -> int:
        if self._private is None:
            if self.path.is_file():
                self._private = int(self.path.read_text().strip(), 16)
            else:
                value = new_private()
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(f"{value:064x}\n")
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
                self._private = value
        return self._private

    @property
    def public(self) -> str:
        """What a browser is given to subscribe with."""
        return b64url(public_bytes(self.private))

    def authorization(self, endpoint: str, contact: str) -> str:
        parts = urllib.parse.urlsplit(endpoint)
        claims = {"aud": f"{parts.scheme}://{parts.netloc}",
                  "exp": int(time.time()) + 12 * 3600,
                  "sub": contact}
        signing = (b64url(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
                   + "." + b64url(json.dumps(claims, separators=(",", ":")).encode()))
        token = signing + "." + b64url(sign(self.private, signing.encode("ascii")))
        return f"vapid t={token}, k={self.public}"


class Gone(Exception):
    """The phone has turned notifications off, or the app was removed."""


def send(keys: Keys, device: Dict[str, Any], message: Dict[str, Any], *,
         contact: str, ttl: int = 2 * 24 * 3600, timeout: float = 15.0,
         opener=None) -> int:
    """Deliver ``message`` to one device; the push service's status code.

    Raises :class:`Gone` when the subscription no longer exists, and
    ``urllib.error`` errors for anything else that went wrong.
    """
    endpoint = device["endpoint"]
    if not endpoint.startswith("https://"):
        raise ValueError("a push address must be https")
    body = encrypt(json.dumps(message).encode("utf-8"),
                   device["p256dh"], device["auth"])
    request = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Authorization": keys.authorization(endpoint, contact),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": "normal",
    })
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        if error.code in (404, 410):
            raise Gone(endpoint) from error
        raise
