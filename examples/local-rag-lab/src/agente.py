#!/usr/bin/env python3
"""
agente.py — Orquesta RAG (Chroma+Ollama) + web (SearXNG) + modelo (credential mapper OAuth/API key).

Uso:
  cd /opt/data/.hermes/vector
  .venv/bin/python agente.py --session test1 "¿cómo es el token de seguridad de IT-Form?"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Asegura imports locales
sys.path.insert(0, str(Path(__file__).resolve().parent))

from modelo_cliente import info_credencial, llamar_modelo
from searxng import buscar_en_searxng
from vector_store import recuperar_contexto, recuperar_memoria, recordar

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("agente")


def _bloque(titulo: str, lineas: list[str]) -> str:
    if not lineas:
        return ""
    cuerpo = "\n".join(lineas)
    return f"{titulo}:\n{cuerpo}\n\n"


async def responder(
    session_id: str,
    pregunta: str,
    *,
    usar_web: bool = True,
    top_k: int = 3,
) -> str:
    cred = info_credencial()
    log.info(
        "credencial provider=%s model=%s auth=%s mapped=%s vector_ok=%s",
        cred.get("provider"),
        cred.get("model"),
        cred.get("auth_type"),
        cred.get("mapped"),
        cred.get("vector_ok"),
    )

    contexto: list[str] = []
    memoria: list[str] = []
    if cred.get("vector_ok", True):
        try:
            contexto = recuperar_contexto(pregunta, top_k=top_k)
            memoria = recuperar_memoria(session_id, pregunta, top_k=2)
        except Exception as e:
            log.warning("vector/RAG falló (sigo sin él): %s", e)
    else:
        log.warning("vector_ok=false — se omite Chroma/Ollama")

    web = ""
    if usar_web:
        try:
            web = await buscar_en_searxng(pregunta, max_results=3)
        except Exception as e:
            log.warning("SearXNG falló: %s", e)
            web = ""

    prompt = (
        _bloque("Contexto de conocimiento (RAG)", contexto)
        + _bloque("Memoria de sesión", memoria)
        + (f"Información web actual:\n{web}\n\n" if web else "")
        + f"Pregunta del usuario:\n{pregunta}\n\n"
        "Responde en español, breve y preciso. Si el contexto RAG responde la pregunta, úsalo."
    )

    system = (
        "Eres el agente agent runtime. Usas contexto RAG y web cuando existan. "
        "No inventes datos que no estén en el contexto si la pregunta es factual sobre proyectos del usuario."
    )

    respuesta = await asyncio.to_thread(
        llamar_modelo, prompt, system=system, max_tokens=400
    )

    try:
        recordar(session_id, f"Q: {pregunta}\nA: {respuesta[:500]}")
    except Exception as e:
        log.warning("no se pudo guardar memoria: %s", e)

    return respuesta


def main() -> None:
    ap = argparse.ArgumentParser(description="Agente RAG + credential mapper (OAuth/API)")
    ap.add_argument("pregunta", nargs="+", help="Pregunta del usuario")
    ap.add_argument("--session", default="cli-default", help="ID de sesión memoria")
    ap.add_argument("--no-web", action="store_true")
    args = ap.parse_args()
    pregunta = " ".join(args.pregunta)

    # Carga .env si existe (CHROMA_TOKEN, etc.)
    env_path = Path("/opt/data/.env")
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    texto = asyncio.run(
        responder(args.session, pregunta, usar_web=not args.no_web)
    )
    print(texto)


if __name__ == "__main__":
    main()
