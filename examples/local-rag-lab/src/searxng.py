#!/usr/bin/env python3
"""
searxng.py — Cliente resiliente para SearXNG.

Encapsula las consultas a SearXNG con:
  - reintentos con backoff exponencial
  - timeouts configurables
  - tolerancia a motores caídos (CAPTCHA / rate-limit)
  - degradación elegante (devuelve "" en vez de tumbar al llamador)

Uso:
    from searxng import buscar_en_searxng
    texto = await buscar_en_searxng("¿qué es ChromaDB?")
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://searxng:8080").rstrip("/")
SEARXNG_TIMEOUT = float(os.getenv("SEARXNG_TIMEOUT", "8"))
SEARXNG_RETRIES = int(os.getenv("SEARXNG_RETRIES", "2"))
SEARXNG_BACKOFF = float(os.getenv("SEARXNG_BACKOFF", "1.0"))
SEARXNG_LANG = os.getenv("SEARXNG_LANG", "es")


def _formatear(resultados: list[dict[str, Any]], max_chars: int) -> str:
    """Convierte resultados crudos de SearXNG en texto plano para el prompt."""
    lineas: list[str] = []
    for i, r in enumerate(resultados, 1):
        titulo = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        contenido = (r.get("content") or "").strip()
        if not titulo and not contenido:
            continue
        bloque = f"[{i}] {titulo}\n{url}"
        if contenido:
            bloque += f"\n{contenido}"
        lineas.append(bloque)

    texto = "\n\n".join(lineas)
    if len(texto) > max_chars:
        texto = texto[:max_chars].rsplit("\n", 1)[0] + "\n[…truncado]"
    return texto


def _consultar_sync(
    pregunta: str,
    max_results: int,
    timeout: float,
    categories: str | None,
) -> dict[str, Any]:
    """Consulta síncrona a SearXNG (se ejecuta en un hilo aparte)."""
    params: dict[str, Any] = {
        "q": pregunta,
        "format": "json",
        "language": SEARXNG_LANG,
    }
    if categories:
        params["categories"] = categories

    resp = requests.get(
        f"{SEARXNG_URL}/search",
        params=params,
        timeout=timeout,
        headers={"User-Agent": "Nidavellir-Hermes/1.0"},
    )
    resp.raise_for_status()
    return resp.json()


async def buscar_en_searxng(
    pregunta: str,
    max_results: int = 5,
    *,
    max_chars: int = 2000,
    timeout: float | None = None,
    retries: int | None = None,
    categories: str | None = None,
) -> str:
    """Busca en SearXNG y devuelve texto listo para el prompt.

    Resiliencia:
      - Reintenta ante errores de red / 5xx (con backoff exponencial).
      - Si SearXNG responde pero algunos motores fallan (CAPTCHA, rate-limit),
        igual devuelve lo que sí llegó (no es un error fatal).
      - Si todo falla, devuelve "" — el llamador NO se cae.
    """
    if not pregunta or not pregunta.strip():
        return ""

    timeout = timeout if timeout is not None else SEARXNG_TIMEOUT
    retries = retries if retries is not None else SEARXNG_RETRIES
    ultimo_error: Exception | None = None

    for intento in range(retries + 1):
        try:
            data: dict[str, Any] = await asyncio.to_thread(
                _consultar_sync, pregunta, max_results, timeout, categories
            )

            # Motores caídos: informativo, no fatal
            caidos = data.get("unresponsive_engines") or []
            if caidos:
                detalles = ", ".join(
                    f"{e[0]} ({e[1]})" if isinstance(e, (list, tuple)) and len(e) > 1
                    else str(e)
                    for e in caidos
                )
                logger.warning("SearXNG: motores no disponibles -> %s", detalles)

            resultados = data.get("results") or []
            if not resultados:
                logger.warning("SearXNG: sin resultados para '%s'", pregunta[:60])
                return ""

            return _formatear(resultados[:max_results], max_chars)

        except (requests.RequestException, ValueError) as exc:
            ultimo_error = exc
            if intento < retries:
                espera = SEARXNG_BACKOFF * (2 ** intento)
                logger.warning(
                    "SearXNG intento %d/%d falló (%s); reintento en %.1fs",
                    intento + 1, retries + 1, exc, espera,
                )
                await asyncio.sleep(espera)

    logger.error("SearXNG no respondió tras %d intentos: %s", retries + 1, ultimo_error)
    return ""


# ──────────────────────────────────────────────
# Prueba rápida
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    async def _demo() -> None:
        for q in ["docker containers", ""]:
            print(f"\n=== '{q}' ===")
            txt = await buscar_en_searxng(q, max_results=3)
            print(txt[:600] if txt else "(sin resultados)")

    asyncio.run(_demo())
