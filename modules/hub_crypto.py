"""
hub_crypto.py -- the hub's encryption (Step 1b; design s.3, decision 2).

    page    AES-256-GCM, key = PBKDF2-HMAC-SHA256(passphrase, salt,
            ITERATIONS), the hub's 16-byte salt (kept in league state,
            output/hub_salt.json, so remembered phones stay unlocked) and a
            new random 12-byte IV per build.
            The browser derives the same key with WebCrypto.
    issues  each archived issue is encrypted ONCE, at archive time, with its
            own random 256-bit AES-GCM key (modules/hub_archive). That key is
            published only inside the per-build encrypted page bundle, so an
            issue reads only after the passphrase does -- and its ciphertext
            never changes, so the public host does not take a fresh copy of
            every ~2 MB issue every night.

THE PASSPHRASE comes from the environment (HUB_PASSPHRASE) and only from
there. It is never written, logged or put in a file, and no message here
contains it. Missing -> PassphraseMissing; shorter than MIN_LENGTH ->
PassphraseTooShort. The encrypted archive sits on a public host indefinitely,
so a short passphrase could be attacked offline.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from typing import Mapping

ITERATIONS = 600_000            # PBKDF2-HMAC-SHA256 (OWASP 2023 floor for SHA-256)
SALT_BYTES = 16
IV_BYTES = 12
KEY_BYTES = 32
MIN_LENGTH = 20                 # characters: four random words clears it
ENV_VAR = "HUB_PASSPHRASE"
BUNDLE_VERSION = 1


class PassphraseError(RuntimeError):
    pass


class PassphraseMissing(PassphraseError):
    pass


class PassphraseTooShort(PassphraseError):
    pass


def passphrase_from_env(env: Mapping[str, str] = None) -> str:
    env = os.environ if env is None else env
    p = env.get(ENV_VAR)
    if p is None or p == "":
        raise PassphraseMissing(f"{ENV_VAR} is not set: the hub is never published unencrypted. "
                                f"Set it in the environment (never in a file).")
    if len(p) < MIN_LENGTH:
        raise PassphraseTooShort(f"{ENV_VAR} is {len(p)} characters; the minimum is {MIN_LENGTH} "
                                 "(about four random words). The encrypted archive stays on a "
                                 "public host, so a short one can be guessed offline.")
    return p


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def derive_key(passphrase: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def seal(key: bytes, plaintext: bytes) -> bytes:
    """iv || ciphertext+tag."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = secrets.token_bytes(IV_BYTES)
    return iv + AESGCM(key).encrypt(iv, plaintext, None)


def open_sealed(key: bytes, blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(blob[:IV_BYTES], blob[IV_BYTES:], None)


def new_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def new_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def make_bundle(passphrase: str, plaintext: bytes, iterations: int = ITERATIONS,
                salt: bytes = None) -> dict:
    """The page bundle the decrypt shell carries: version, KDF, iterations,
    salt, iv, ciphertext. A new IV every call. The salt is the hub's own,
    kept across builds (hub_publish.hub_salt) so a phone's remembered key
    keeps working night after night (Nick, 11-05: the hub asked again the
    morning after "remember this phone"); a new random one when none is
    given (tests)."""
    salt = new_salt() if salt is None else salt
    if len(salt) != SALT_BYTES:
        raise ValueError(f"the salt must be {SALT_BYTES} bytes")
    key = derive_key(passphrase, salt, iterations)
    sealed = seal(key, plaintext)
    return {"v": BUNDLE_VERSION, "kdf": "PBKDF2-SHA256", "iter": iterations, "salt": b64(salt),
            "iv": b64(sealed[:IV_BYTES]), "ct": b64(sealed[IV_BYTES:])}


def open_bundle(passphrase: str, bundle: dict) -> bytes:
    """What the page does, in Python: the round-trip test's decryptor."""
    if bundle.get("v") != BUNDLE_VERSION or bundle.get("kdf") != "PBKDF2-SHA256":
        raise ValueError("not a hub bundle")
    key = derive_key(passphrase, unb64(bundle["salt"]), int(bundle["iter"]))
    return open_sealed(key, unb64(bundle["iv"]) + unb64(bundle["ct"]))


def bundle_json(bundle: dict) -> str:
    return json.dumps(bundle, separators=(",", ":"))
