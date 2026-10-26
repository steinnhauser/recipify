"""Encrypt the viewer into a locked page that only opens with a key (for public hosting).

The page is AES-256-GCM encrypted with a key derived from the passphrase (PBKDF2-SHA256), and
decrypted in the browser with WebCrypto. The passphrase travels in the URL fragment
(`#key=...`), which browsers never send to the server.
"""

import base64
import html
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

TEMPLATE = Path(__file__).parent / "templates" / "locked.html"
ITERATIONS = 600_000


def _derive(passphrase: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_page(page: str, passphrase: str, title: str = "recipify") -> str:
    if not passphrase:
        raise ValueError("empty passphrase")
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_derive(passphrase, salt, ITERATIONS)).encrypt(iv, page.encode("utf-8"), None)
    fields = {"salt": salt, "iv": iv, "ct": ct}
    payload = json.dumps(
        {"v": 1, "iter": ITERATIONS} | {k: base64.b64encode(v).decode() for k, v in fields.items()}
    )
    return (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__TITLE__", html.escape(title))
        .replace("__PAYLOAD__", payload)
    )


def decrypt_page(locked: str, passphrase: str) -> str:
    """Inverse of encrypt_page; raises cryptography's InvalidTag on a wrong key."""
    start = locked.index('<script id="payload" type="application/json">')
    p = json.loads(locked[locked.index(">", start) + 1 : locked.index("</script>", start)])
    key = _derive(passphrase, base64.b64decode(p["salt"]), p["iter"])
    return AESGCM(key).decrypt(base64.b64decode(p["iv"]), base64.b64decode(p["ct"]), None).decode()
