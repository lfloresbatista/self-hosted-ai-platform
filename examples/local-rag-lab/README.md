# Local RAG lab — reference Python modules

Sanitized **reference implementation** of:

- local embeddings (Ollama) + ChromaDB vector store  
- credential mapper (API key / OAuth file → locked-down JSON)  
- optional RAG agent + metasearch helper  
- s6 install helper for supervised agent containers  

**No secrets.** Paths default to `/opt/data/...` as a self-hosted layout example — adjust to your deploy.

| Module | Role |
|--------|------|
| `src/credential_mapper.py` | File watcher → `mapper.json` |
| `src/vector_store.py` | Embed + Chroma collections |
| `src/searxng.py` | Resilient metasearch client |
| `src/modelo_cliente.py` | OpenAI-compatible chat via mapper |
| `src/agente.py` | RAG (+ optional web) + LLM |
| `scripts/security_test.py` | Permission / leak / embed battery |
| `supervise/install_s6.py` | Optional s6 longrun registration |

See also: [`docs/local-rag-credential-mapper.md`](../../docs/local-rag-credential-mapper.md).
