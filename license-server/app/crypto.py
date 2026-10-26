"""Assinatura HMAC das respostas de licença (compartilhada com o app desktop)."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_payload(payload: dict[str, Any]) -> str:
    """JSON estável para assinatura (sem o campo signature)."""
    body = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    message = canonical_payload(payload).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_signature(payload: dict[str, Any], secret: str) -> bool:
    expected = str(payload.get("signature") or "")
    if not expected or not secret:
        return False
    actual = sign_payload(payload, secret)
    return hmac.compare_digest(actual, expected)
