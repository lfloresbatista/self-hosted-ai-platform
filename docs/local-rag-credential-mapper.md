# Local RAG + credential mapper (lab)

**Portfolio lab:** local embeddings + vector database + credential mapper + optional on-demand RAG for a technical AI agent runtime.

Documents a **production-inspired** pattern used on a private self-hosted AI platform (agent runtime + chat UI + Ollama embeddings). No secrets, personal domains, or live credentials.

---

## Problem

- Chat models do not automatically retain private project knowledge at scale.
- API keys and OAuth tokens often live in different stores; tool-facing clients need a **stable mapper**.
- Embeddings should stay **local** when possible (privacy + cost).

## Solution sketch

```
Agent chat (any provider)
        │
        ├─► Skill / tool (on demand) ─► vector store client ─► ChromaDB
        │                                         ▲
        │                                         │ embeddings
        │                                         Ollama (e.g. nomic-embed-text, 768-d)
        │
        └─► Credential mapper (watcher)
                 watches: .env + agent config + OAuth token store
                 writes:  locked-down JSON (0600) → base_url + secret handle
```

| Piece | Role |
|-------|------|
| **Ollama** | Embeddings only (example: `nomic-embed-text`) |
| **ChromaDB** | HTTP vector store; collections for knowledge + session memory |
| **Credential mapper** | File watcher; maps active model provider → API key **or** OAuth access token |
| **Agent module** | Optional: RAG (+ optional metasearch) + chat completions via mapped credential |
| **Agent skill** | Triggers RAG when the user asks about indexed project knowledge |

## Design decisions

1. **RAG is on-demand**, not injected every turn (token cost + control).
2. **Chat model is swappable**; embedding model is structural (dimension lock, e.g. 768).
3. **OAuth** (device-code / login flows) can feed the same OpenAI-compatible HTTP client as API keys when the platform stores tokens in a known auth file.
4. **Security baseline:** secrets files mode `0600`; never log bearer tokens; truncate embed inputs; prefer internal Docker DNS only.
5. Residual risk if the vector DB does not enforce auth tokens: **network isolation** is mandatory until server-side auth is hardened.

## What was validated (lab)

| Check | Result (lab) |
|-------|----------------|
| Permissions on mapper JSON / env / auth store | Pass (0600) |
| No full secrets / JWTs in application logs | Pass |
| Embed + upsert + semantic retrieve | Pass |
| Long/malicious query handled (input truncation) | Pass |
| OAuth chat completions via mapped token | Pass |
| Blind agent session: skill auto-selected RAG for a project question | Pass |
| Vector DB server-side token enforcement | **Warn** — mitigate with private network |

## Security test harness (pattern)

Reproducible script categories:

- File permission gates  
- Log redaction checks  
- Authenticated vs anonymous vector client behaviour  
- Embed dimension sanity  
- Metadata rules (e.g. no empty metadata dicts for Chroma)  
- Short LLM round-trip without printing secrets  

## Portfolio takeaways

- Separates **retrieval infrastructure** from **generation models**.
- Shows OAuth + API-key unification for tool-facing HTTP clients.
- Demonstrates skill-triggered RAG without hard-coding “always retrieve”.
- Documents residual risks honestly (vector DB auth).

## Related public work

- This monorepo: self-hosted AI platform architecture (Tunnel, nginx-proxy, multi-model).
- Hardening guides in sibling public repos.

---

*Sanitized lab notes — suitable for public portfolio. Private ops may use internal codenames; they are intentionally omitted here.*

## Reference code

See [`examples/local-rag-lab/`](../examples/local-rag-lab/).
