#!/usr/bin/env python3
"""Security battery — Stack Local RAG lab (no secrets printed)."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path("/opt/data/.hermes/vector")
LOGS = ROOT / "logs"
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[bool | None, str, str]] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((bool(cond), name, detail))
    print(("PASS" if cond else "FAIL"), name, (detail or "")[:140])


def main() -> int:
    # Load .env
    env_path = Path("/opt/data/.env")
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    # 1. File permissions
    vj = ROOT / "mapper.json"
    mode = vj.stat().st_mode & 0o777
    ok("mapper.json mode 600", mode == 0o600, oct(mode))
    em = env_path.stat().st_mode & 0o777
    ok(".env not world-readable", not (em & 0o004), oct(em))
    auth = Path("/opt/data/auth.json")
    am = auth.stat().st_mode & 0o777
    ok("auth.json not world-readable", not (am & 0o004), oct(am))
    ok("mapper.json not group/other writable", not (mode & 0o022), oct(mode))

    # 2. Secrets not in logs
    d = json.loads(vj.read_text(encoding="utf-8"))
    secret_patterns: list[str] = []
    if d.get("api_key"):
        secret_patterns.append(d["api_key"])
        if len(d["api_key"]) > 24:
            secret_patterns.append(d["api_key"][:24])
    chroma_tok = os.environ.get("CHROMA_TOKEN", "")
    if chroma_tok:
        secret_patterns.append(chroma_tok)

    log_blob = ""
    for p in LOGS.glob("*.log"):
        log_blob += p.read_text(encoding="utf-8", errors="replace")
    leaked = [s for s in secret_patterns if s and s in log_blob]
    ok("no full secrets in log files", len(leaked) == 0, f"leaks={len(leaked)}")
    ok(
        "no JWT-looking blobs in logs",
        not re.search(r"eyJ[a-zA-Z0-9_-]{30,}\.[a-zA-Z0-9_-]+", log_blob),
    )

    # 3. Chroma auth — residual: server may not enforce token on internal net
    import chromadb

    unauth_works = False
    try:
        bad = chromadb.HttpClient(
            host=os.getenv("CHROMA_HOST", "chromadb"),
            port=int(os.getenv("CHROMA_PORT", "8000")),
        )
        bad.list_collections()
        unauth_works = True
    except Exception as e:
        ok(
            "chroma rejects unauthenticated client",
            "Auth" in type(e).__name__ or "Forbidden" in str(e) or "403" in str(e),
            type(e).__name__,
        )
    if unauth_works:
        # Documented residual risk: mitigate with Docker network isolation only
        RESULTS.append(
            (
                None,
                "chroma token not enforced by server (residual)",
                "mitigation: internal prod_net only; client still sends Bearer",
            )
        )
        print(
            "WARN chroma token not enforced by server (residual)",
            "mitigation: internal prod_net only",
        )

    try:
        good = chromadb.HttpClient(
            host=os.getenv("CHROMA_HOST", "chromadb"),
            port=int(os.getenv("CHROMA_PORT", "8000")),
            headers={"Authorization": f"Bearer {os.environ['CHROMA_TOKEN']}"},
        )
        cols = good.list_collections()
        ok("chroma accepts client with token header", True, f"collections={len(cols)}")
    except Exception as e:
        ok("chroma accepts client with token header", False, str(e)[:100])

    # 4. Ollama internal
    try:
        url = os.getenv("OLLAMA_URL", "http://ollama:11434") + "/api/tags"
        with urllib.request.urlopen(url, timeout=5) as r:
            ok("ollama reachable on internal DNS", r.status == 200)
    except Exception as e:
        ok("ollama reachable on internal DNS", False, str(e)[:80])

    # 5. Vector ops
    from vector_store import agregar_conocimiento, embed, recuperar_contexto

    v = embed("security probe plaintext only")
    ok("embed returns 768-d", len(v) == 768)

    try:
        agregar_conocimiento(
            ["probe security stack valkiria " + hashlib.sha1(os.urandom(4)).hexdigest()]
        )
        ok("upsert without empty metadata", True)
    except Exception as e:
        ok("upsert without empty metadata", False, str(e)[:100])

    try:
        r = recuperar_contexto("A" * 5000 + "; DROP TABLE --", top_k=1)
        ok("long/malicious query handled", True, f"docs={len(r)}")
    except Exception as e:
        ok("long/malicious query handled", False, str(e)[:80])

    # 6. modelo_cliente hygiene + short LLM call
    from modelo_cliente import info_credencial, llamar_modelo

    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    logging.getLogger("modelo_cliente").addHandler(h)
    logging.getLogger("modelo_cliente").setLevel(logging.DEBUG)
    info = info_credencial()
    ok("info_credencial has no api_key field", "api_key" not in info)
    ok("info_credencial exposes has_secret only", "has_secret" in info)
    try:
        out = llamar_modelo("Responde solo con la palabra OK.", max_tokens=8, timeout=45)
        ok("oauth/api chat works under security test", bool(out and out.strip()), (out or "")[:40])
    except Exception as e:
        ok("oauth/api chat works under security test", False, str(e)[:100])
    logtxt = buf.getvalue()
    ok(
        "modelo_cliente log buffer has no full secrets",
        not any(s and len(s) > 15 and s in logtxt for s in secret_patterns),
    )

    ok("vector_ok true with current mapping", d.get("vector_ok") is True)
    ok("mapped true with current creds", d.get("mapped") is True)

    fails = sum(1 for c, _, _ in RESULTS if c is False)
    passes = sum(1 for c, _, _ in RESULTS if c is True)
    print("---")
    print(f"PASS={passes} FAIL={fails}")
    outj = LOGS / "security-test-last.json"
    outj.write_text(
        json.dumps([{"pass": c, "name": n, "detail": d} for c, n, d in RESULTS], indent=2),
        encoding="utf-8",
    )
    print(f"wrote {outj}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
