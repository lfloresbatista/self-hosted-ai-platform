# Self-Hosted AI Platform

**Reference architecture for private, production-grade AI platforms.**

This repository documents a real-world implementation of a complete self-hosted AI stack focused on:

- Privacy and data sovereignty
- Security by design (no public ports, Cloudflare Tunnel)
- Multi-model routing (local + remote providers)
- **Local RAG / embeddings lab** (vector DB + credential mapper)
- Platform Engineering practices
- Observability and operational readiness

It is intended as a **portfolio showcase** and learning reference for Platform Engineers, SREs and infrastructure specialists working with AI workloads.

---

## Architecture Overview

```
Internet → Cloudflare Edge + Access → Cloudflare Tunnel → nginx-proxy → Services
```

**Core components:**

| Component | Role |
|-----------|------|
| Cloudflare Tunnel | Zero-trust ingress (no open ports 80/443) |
| nginx-proxy + acme | Automatic reverse proxy + DNS-01 certs |
| Open WebUI | User-facing chat interface |
| Hermes / Agent runtime | Technical agent with tools + messaging gateway |
| Arcane / Docker mgr | Advanced Compose + GitOps management |
| Ollama | **Embeddings** / optional local models |
| **ChromaDB + local RAG pattern** | Vector store + credential mapper + on-demand retrieval |

```
Agent ──(skill/tool)──► RAG (Chroma) ◄── Ollama embeddings
  │
  └── Credential mapper: env + config + OAuth store → locked-down credential file
```

---

## Key Design Decisions

- **No public exposure** of origin servers (Cloudflare Tunnel only)
- DNS-01 challenge for certificates (works behind Tunnel)
- Internal Docker networks + external `prod_net`
- Multi-model strategy (API providers + OAuth where available)
- Strong focus on hardening (server + Docker + proxy)
- Spec-Driven Development experiments for agent workflows
- **RAG on-demand** (skill/agent), not full-context dump every turn
- Embeddings local; chat models remote/swappable
- Honest residual-risk notes (e.g. vector DB auth vs network isolation)

---

## Repository Structure

```
.
├── docs/
│   └── local-rag-credential-mapper.md   # RAG + mapper lab (sanitized)
├── examples/
│   └── local-rag-lab/                   # Reference Python modules (no secrets)
├── security/                            # Hardening guides (when published)  # keep
├── security/                            # Hardening guides (when published)
└── README.md
```

---

## Labs documented here

| Lab | Doc | Focus |
|-----|-----|--------|
| **Local RAG + credential mapper** | [`docs/local-rag-credential-mapper.md`](docs/local-rag-credential-mapper.md) | Embeddings, Chroma, API key/OAuth mapper, security battery, skill-triggered RAG |

---

## What this demonstrates

- End-to-end Platform Engineering for AI
- Production security posture (UFW, Fail2ban, sysctl, Docker hardening, Cloudflare Access)
- Multi-service orchestration with Docker Compose
- Real operational experience (not just toy demos)
- Ability to design systems that are both powerful and private
- **Retrieval + generation split** with local vectors and multi-provider chat

---

## Related Repositories

- [linux-server-hardening](https://github.com/lfloresbatista/linux-server-hardening) — Practical hardening guides
- Personal tracking / full runbooks: private ops repo (not public)

---

## Author

**Luis Flores Batista**  
Platform Engineer · SRE · HPC & AI Infrastructure  
Panama · Available for remote contracts (flexible / async)
