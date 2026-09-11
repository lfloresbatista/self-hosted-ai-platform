#!/usr/bin/env python3
"""
modelo_cliente.py — Llama al modelo activo según mapper.json (API key u OAuth).

Lee /opt/data/.hermes/vector/mapper.json (chmod 600).
No imprime api_key/tokens.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("modelo_cliente")

VALKIRIA_JSON = Path(
    os.getenv("VALKIRIA_OUT", "/opt/data/.hermes/vector/mapper.json")
)


def cargar_valkiria(path: Path = VALKIRIA_JSON) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


def llamar_modelo(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
    timeout: float = 60.0,
) -> str:
    """Chat completions OpenAI-compatible (DeepSeek, Grok OAuth Bearer, etc.)."""
    cfg = cargar_valkiria()
    if not cfg.get("mapped") or not cfg.get("api_key"):
        raise RuntimeError(
            f"mapper sin credencial usable: provider={cfg.get('provider')} "
            f"auth_type={cfg.get('auth_type')} mapped={cfg.get('mapped')}"
        )
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("base_url vacío en mapper.json")
    model = cfg.get("model") or ""
    if not model:
        raise RuntimeError("model vacío en mapper.json")

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            "User-Agent": "Nidavellir-mapper/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", errors="replace")
        log.error(
            "HTTP %s provider=%s model=%s: %s",
            e.code,
            cfg.get("provider"),
            model,
            detail,
        )
        raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from e

    try:
        return raw["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Respuesta LLM inesperada: {str(raw)[:200]}") from e


def info_credencial() -> dict[str, Any]:
    """Metadatos seguros (sin secret)."""
    c = cargar_valkiria()
    return {
        "provider": c.get("provider"),
        "model": c.get("model"),
        "auth_type": c.get("auth_type"),
        "mapped": c.get("mapped"),
        "vector_ok": c.get("vector_ok"),
        "oauth_ok": c.get("oauth_ok"),
        "base_url": c.get("base_url"),
        "has_secret": bool(c.get("api_key")),
    }
