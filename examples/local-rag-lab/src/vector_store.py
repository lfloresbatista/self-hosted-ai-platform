# hermes/vector_store.py
import os
import hashlib
import requests
import chromadb

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
CHROMA_HOST   = os.getenv("CHROMA_HOST", "chromadb")   # nombre DNS en prod_net
CHROMA_PORT   = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_TOKEN  = os.environ["CHROMA_TOKEN"]              # mismo token del .env de tools

OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBED_MODEL   = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM     = 768                                    # nomic-embed-text = 768
# nomic ~2k tokens; Ollama 500 en este host a partir de ~4500 chars
EMBED_MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "4000"))

# ──────────────────────────────────────────────
# Cliente ChromaDB (envía Bearer; el server puede no forzar auth — ver docs)
# ──────────────────────────────────────────────
chroma = chromadb.HttpClient(
    host=CHROMA_HOST,
    port=CHROMA_PORT,
    headers={"Authorization": f"Bearer {CHROMA_TOKEN}"},
)


def embed(texto: str) -> list[float]:
    """Genera embedding de UN texto con Ollama (trunca a EMBED_MAX_CHARS)."""
    if texto is None:
        texto = ""
    if len(texto) > EMBED_MAX_CHARS:
        texto = texto[:EMBED_MAX_CHARS]
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": texto},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def embed_varios(textos: list[str]) -> list[list[float]]:
    """Genera embeddings de varios textos (uno a uno; Ollama no batea)."""
    return [embed(t) for t in textos]


def _id_de(texto: str, prefijo: str = "") -> str:
    """ID determinista basado en el contenido (evita duplicados en upsert)."""
    h = hashlib.sha1(texto.encode()).hexdigest()[:16]
    return f"{prefijo}-{h}" if prefijo else h


# ──────────────────────────────────────────────
# Colecciones (separadas por propósito)
# ──────────────────────────────────────────────
KNOWLEDGE = chroma.get_or_create_collection(
    name="hermes_knowledge",
    metadata={"hnsw:space": "cosine"},   # nomic-embed-text rinde mejor con cosine
)
MEMORY = chroma.get_or_create_collection(
    name="hermes_memory",
    metadata={"hnsw:space": "cosine"},
)


# ──────────────────────────────────────────────
# Ingesta de conocimiento (RAG)
# ──────────────────────────────────────────────
def agregar_conocimiento(textos: list[str], metadatas: list[dict] | None = None):
    """Indexa documentos/chunks en la base de conocimiento.

    Nota: Chroma rechaza metadatas vacíos ({}), por eso solo se envían
    cuando hay valores reales.
    """
    if not textos:
        return
    ids = [_id_de(t, "doc") for t in textos]
    kwargs = {
        "ids": ids,
        "embeddings": embed_varios(textos),
        "documents": textos,
    }
    if metadatas:
        kwargs["metadatas"] = metadatas
    KNOWLEDGE.upsert(**kwargs)


def recuperar_contexto(pregunta: str, top_k: int = 3) -> list[str]:
    """Recupera los fragmentos más relevantes para una pregunta."""
    res = KNOWLEDGE.query(
        query_embeddings=[embed(pregunta)],
        n_results=top_k,
    )
    return res["documents"][0] if res["documents"] else []


# ──────────────────────────────────────────────
# Memoria de conversación (por sesión)
# ──────────────────────────────────────────────
def recordar(session_id: str, texto: str):
    """Guarda un fragmento de conversación asociado a una sesión."""
    MEMORY.upsert(
        ids=[_id_de(texto, session_id)],
        embeddings=[embed(texto)],
        documents=[texto],
        metadatas=[{"session_id": session_id}],
    )


def recuperar_memoria(session_id: str, pregunta: str, top_k: int = 3) -> list[str]:
    """Recupera recuerdos relevantes de una sesión concreta."""
    res = MEMORY.query(
        query_embeddings=[embed(pregunta)],
        n_results=top_k,
        where={"session_id": session_id},
    )
    return res["documents"][0] if res["documents"] else []
