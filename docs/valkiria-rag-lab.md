# Valkiria RAG Lab (Reference Architecture)

**Portfolio lab:** local embeddings + vector DB + credential mapper + optional agent RAG for a technical AI agent runtime.

This documents a **production-inspired** pattern used on a private self-hosted AI platform (Hermes-class agent + Open WebUI + Ollama embeddings). No secrets, hostnames of personal domains, or live credentials are included.

---

## Problem

- Chat models do not automatically “remember” private project knowledge at scale.
- API keys and OAuth tokens live in different stores; agents need a **stable mapper**.
- Embeddings should stay **local** when possible (privacy + cost).

## Solution sketch

```
Agent chat (any provider)
        │
        ├─► Skill / tool (on demand) ─► vector_store ─► ChromaDB
        │                                      ▲
        │                                      │ embeddings
        │                                      Ollama (nomic-embed-text, 768-d)
        │
        └─► Credential mapper “Valkiria”
                 watches: .env + agent config + OAuth store
                 writes:  valkiria.json (0600)  → base_url + secret handle
```

| Piece | Role |
|-------|------|
| **Ollama** | Embeddings only (e.g. `nomic-embed-text`) |
| **ChromaDB** | HTTP vector store; collections for knowledge + session memory |
| **Valkiria** | `inotify` watcher; maps active model provider → API key **or** OAuth access token |
| **Agent module** | Optional: RAG (+ optional SearXNG) + chat completions via mapped credential |
| **Agent skill** | Triggers RAG when the user asks about indexed project knowledge |

## Design decisions

1. **RAG is on-demand**, not injected every turn (token cost + control).
2. **Chat model is swappable**; embedding model is structural (dimension lock, e.g. 768).
3. **OAuth** (e.g. xAI device-code) can feed the same OpenAI-compatible client as API keys when the platform stores tokens in a known auth file.
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
| Blind agent session: skill auto-selected RAG for project Q | Pass |
| Vector DB server-side token enforcement | **Warn** — mitigate with private network |

## Security test harness (pattern)

Reproducible script categories:

- File permission gates  
- Log redaction checks  
- Authenticated vs anonymous vector client behaviour  
- Embed dimension sanity  
- Metadata rules (no empty metadata dicts for Chroma)  
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

*Sanitized lab notes — suitable for public portfolio. Implementation details of private hostnames and live keys are intentionally omitted.*
