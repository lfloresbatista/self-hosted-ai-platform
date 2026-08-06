# Self-Hosted AI Platform

**Reference architecture for private, production-grade AI platforms.**

This repository documents a real-world implementation of a complete self-hosted AI stack focused on:

- Privacy and data sovereignty
- Security by design (no public ports, Cloudflare Tunnel)
- Multi-model routing (local + remote providers)
- Platform Engineering practices
- Observability and operational readiness

It is intended as a **portfolio showcase** and learning reference for Platform Engineers, SREs and infrastructure specialists working with AI workloads.

---

## Architecture Overview

```
Internet → Cloudflare Edge + Access → Cloudflare Tunnel → nginx-proxy → Services
```

**Core components:**

| Component              | Role                                      |
|------------------------|-------------------------------------------|
| Cloudflare Tunnel      | Zero-trust ingress (no open ports 80/443) |
| nginx-proxy + acme     | Automatic reverse proxy + DNS-01 certs    |
| Open WebUI (Citadel)   | User-facing chat interface                |
| Hermes / Agent runtime | Technical agent with tools + Telegram     |
| Arcane / Docker mgr    | Advanced Compose + GitOps management      |
| Ollama                 | Embeddings / local models (optional)      |

---

## Key Design Decisions

- **No public exposure** of origin servers (Cloudflare Tunnel only)
- DNS-01 challenge for certificates (works behind Tunnel)
- Internal Docker networks + external `prod_net`
- Multi-model strategy (DeepSeek, Qwen, Grok OAuth, Gemini Flash, etc.)
- Strong focus on hardening (server + Docker + proxy)
- Spec-Driven Development experiments for agent workflows

---

## Repository Structure

```
.
├── examples/               # Clean docker-compose examples
├── security/               # Hardening guides
├── docs/                   # Architecture notes
└── README.md
```

---

## What this demonstrates

- End-to-end Platform Engineering for AI
- Production security posture (UFW, Fail2ban, sysctl, Docker hardening, Cloudflare Access)
- Multi-service orchestration with Docker Compose
- Real operational experience (not just toy demos)
- Ability to design systems that are both powerful and private

---

## Related Repositories

- [linux-server-hardening](https://github.com/lfloresbatista/linux-server-hardening) — Practical hardening guides
- Personal tracking: OSpace (private)

---

## Author

**Luis Flores Batista**  
Platform Engineer · SRE · HPC & AI Infrastructure  
Panama · Available for remote contracts (flexible / async)

- GitHub: [lfloresbatista](https://github.com/lfloresbatista)
- LinkedIn: [luisfloresb](https://linkedin.com/in/luisfloresb)

---

> This is a sanitized, public reference derived from production experience. No secrets, no real domains, no credentials are included.
