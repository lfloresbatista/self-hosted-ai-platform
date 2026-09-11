#!/usr/bin/env python3
"""
CredentialMapper — watcher definitivo (inotify vía libc, sin dependencias extra)

Vigila:
  - /opt/data/.env          (keys y base_url, Dashboard)
  - /opt/data/config.yaml   (model.default / model.provider)
  - /opt/data/auth.json     (OAuth Hermes: xai-oauth, etc.)

Escribe (atómico, chmod 600):
  - /opt/data/.hermes/vector/mapper.json

Campos clave del JSON:
  auth_type: api_key | oauth | none
  mapped: hay credencial usable para chat HTTP
  vector_ok: Chroma+Ollama se pueden usar (default True; no depende de OAuth)
  api_key: secret API key O access_token OAuth (nunca loguear)

Uso:
  cd /opt/data/.hermes/vector && .venv/bin/python mapper.py
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import logging
import os
import select
import struct
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

ENV_PATH = Path(os.getenv("MAPPER_ENV", "/opt/data/.env"))
CFG_PATH = Path(os.getenv("MAPPER_CFG", "/opt/data/config.yaml"))
OUT_PATH = Path(os.getenv("MAPPER_OUT", "/opt/data/.hermes/vector/mapper.json"))
LOG_DIR = Path(os.getenv("MAPPER_LOG_DIR", "/opt/data/.hermes/vector/logs"))
DEBOUNCE = float(os.getenv("MAPPER_DEBOUNCE", "0.5"))
HEARTBEAT_SEC = float(os.getenv("MAPPER_HEARTBEAT", "60"))  # refresca ts sin cambio
# Rotación: poco disco/CPU (stdlib, sin deps)
LOG_MAX_BYTES = int(os.getenv("MAPPER_LOG_MAX_BYTES", str(1 * 1024 * 1024)))  # 1 MiB
LOG_BACKUP_COUNT = int(os.getenv("MAPPER_LOG_BACKUPS", "5"))  # ~6 MiB tope


class _LevelFilter(logging.Filter):
    """Deja pasar solo un rango de niveles (p. ej. solo WARNING)."""

    def __init__(self, min_level: int, max_level: int = logging.CRITICAL):
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return self.min_level <= record.levelno <= self.max_level


def setup_logging() -> logging.Logger:
    """Logging rotacional en vector/logs — bajo consumo (RotatingFileHandler).

    Archivos:
      - mapper.log          INFO+ (todo junto para revisión)
      - mapper-warning.log  solo WARNING
      - mapper-error.log    ERROR+
    + consola INFO+ (opcional vía MAPPER_LOG_CONSOLE=0 para silenciar)
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger("mapper")
    root.handlers.clear()
    root.setLevel(logging.DEBUG)
    root.propagate = False

    def _rotating(name: str) -> RotatingFileHandler:
        h = RotatingFileHandler(
            LOG_DIR / name,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,  # no abre el fichero hasta el primer write
        )
        h.setFormatter(fmt)
        return h

    # Todo junto (info/warning/error) — el que revisamos en sesión
    h_all = _rotating("mapper.log")
    h_all.setLevel(logging.INFO)
    root.addHandler(h_all)

    h_warn = _rotating("mapper-warning.log")
    h_warn.setLevel(logging.WARNING)
    h_warn.addFilter(_LevelFilter(logging.WARNING, logging.WARNING))
    root.addHandler(h_warn)

    h_err = _rotating("mapper-error.log")
    h_err.setLevel(logging.ERROR)
    root.addHandler(h_err)

    if os.getenv("MAPPER_LOG_CONSOLE", "1") not in ("0", "false", "False"):
        h_con = logging.StreamHandler()
        h_con.setLevel(logging.INFO)
        h_con.setFormatter(fmt)
        root.addHandler(h_con)

    root.info(
        "logging listo dir=%s maxBytes=%s backups=%s",
        LOG_DIR,
        LOG_MAX_BYTES,
        LOG_BACKUP_COUNT,
    )
    return root


log = setup_logging()

# Defaults de base_url si faltan en .env (solo URLs públicas, no secrets)
DEFAULT_BASE = {
    "deepseek": "https://api.deepseek.com/v1",
    "alibaba": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "zai": "https://open.bigmodel.cn/api/paas/v4",
    "xai": "https://api.x.ai/v1",
    "xai-oauth": "https://api.x.ai/v1",
}

# provider Hermes → (env BASE_URL, env API_KEY)  — solo API key clásica
MAPEO = {
    "deepseek": ("DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY"),
    "alibaba": ("DASHSCOPE_BASE_URL", "DASHSCOPE_API_KEY"),
    "dashscope": ("DASHSCOPE_BASE_URL", "DASHSCOPE_API_KEY"),
    "zai": ("GLM_BASE_URL", "GLM_API_KEY"),
    "glm": ("GLM_BASE_URL", "GLM_API_KEY"),
    "xai": ("XAI_BASE_URL", "XAI_API_KEY"),  # si hay key pay-as-you-go
}

# OAuth de Hermes (login device_code, etc.) vive aquí — NO en .env
AUTH_PATH = Path(os.getenv("MAPPER_AUTH", "/opt/data/auth.json"))

# El stack vectorial (Chroma + Ollama) NUNCA depende del proveedor de chat
VECTOR_OK_DEFAULT = True

# inotify
IN_MODIFY = 0x00000002
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
MASK = IN_MODIFY | IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE

_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
_libc.inotify_init.restype = ctypes.c_int
_libc.inotify_add_watch.restype = ctypes.c_int
_libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]

# Estado previo para no spamear WARNING en cada heartbeat
_prev_sig: str | None = None


def _inotify_init() -> int:
    fd = _libc.inotify_init()
    if fd < 0:
        raise OSError(ctypes.get_errno(), "inotify_init falló")
    return fd


def _inotify_add_watch(fd: int, path: str, mask: int) -> int:
    wd = _libc.inotify_add_watch(fd, path.encode(), mask)
    if wd < 0:
        raise OSError(ctypes.get_errno(), f"inotify_add_watch falló en {path}")
    return wd


def _leer_env(path: Path = ENV_PATH) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError as e:
        log.warning("No se pudo leer %s: %s", path, e)
    return out


def _leer_config(path: Path = CFG_PATH) -> dict[str, str]:
    """Lee model.default y model.provider del bloque model: (indentado)."""
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        log.warning("No se pudo leer %s: %s", path, e)
        return out

    in_model = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] not in (" ", "\t") and line.rstrip().endswith(":"):
            in_model = line.strip() == "model:"
            continue
        if not in_model:
            continue
        s = line.strip()
        if s.startswith("default:"):
            out["model"] = s.split(":", 1)[1].strip().strip('"').strip("'")
        elif s.startswith("provider:"):
            out["provider"] = s.split(":", 1)[1].strip().strip('"').strip("'")
    return out


def _leer_auth(path: Path = AUTH_PATH) -> dict:
    """Lee auth.json de Hermes (OAuth + credential_pool). No loguea secrets."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        log.warning("No se pudo leer auth.json: %s", e)
        return {}


def _es_oauth_provider(prov: str) -> bool:
    p = (prov or "").lower()
    return "oauth" in p or p.endswith("-oauth")


def _resolver_oauth(prov: str, auth: dict) -> dict:
    """Extrae access_token + base_url del credential_pool / providers de Hermes."""
    out = {
        "access_token": "",
        "base_url": DEFAULT_BASE.get(prov, DEFAULT_BASE.get("xai-oauth", "")),
        "auth_mode": "",
        "found": False,
    }
    if not auth:
        return out

    # 1) credential_pool[provider] preferido
    pool = (auth.get("credential_pool") or {}).get(prov) or []
    if isinstance(pool, list):
        for cred in pool:
            if not isinstance(cred, dict):
                continue
            tok = cred.get("access_token") or ""
            if tok:
                out["access_token"] = tok
                out["base_url"] = cred.get("base_url") or out["base_url"]
                out["auth_mode"] = cred.get("auth_type") or "oauth"
                out["found"] = True
                return out

    # 2) providers[provider].tokens
    block = (auth.get("providers") or {}).get(prov) or {}
    tokens = block.get("tokens") or {}
    tok = tokens.get("access_token") or ""
    if tok:
        out["access_token"] = tok
        out["auth_mode"] = block.get("auth_mode") or "oauth"
        out["found"] = True
        # base_url a veces solo en pool; defaults ya puestos
    return out


def construir() -> dict:
    """Arma el mapeador: API key (.env) u OAuth (auth.json). Vector siempre OK."""
    cfg = _leer_config()
    env = _leer_env()
    auth = _leer_auth()
    prov = (cfg.get("provider") or "").strip()
    model = (cfg.get("model") or "").strip()

    auth_type = "none"
    base = ""
    key = ""
    key_env = ""
    mapped = False
    oauth_ok = False
    notes: list[str] = []

    # --- rama OAuth (xai-oauth, openai-codex, etc.) ---
    if _es_oauth_provider(prov):
        auth_type = "oauth"
        oa = _resolver_oauth(prov, auth)
        base = oa["base_url"] or DEFAULT_BASE.get(prov, "")
        key = oa["access_token"]  # Bearer usable como api_key OpenAI-compatible
        oauth_ok = bool(key)
        mapped = oauth_ok
        if oauth_ok:
            notes.append("oauth_token_from_auth_json")
        else:
            notes.append("oauth_sin_token_en_auth_json")
    else:
        # --- rama API key ---
        be, ke = MAPEO.get(prov, (None, None))
        key_env = ke or ""
        if be and ke:
            auth_type = "api_key"
            base = env.get(be, "") or DEFAULT_BASE.get(prov, "")
            key = env.get(ke, "")
            mapped = bool(key)
            if not key:
                notes.append("api_key_faltante_en_env")
        else:
            # ¿Hay entrada en credential_pool con api_key?
            pool = (auth.get("credential_pool") or {}).get(prov) or []
            for cred in pool if isinstance(pool, list) else []:
                if isinstance(cred, dict) and cred.get("auth_type") == "api_key":
                    auth_type = "api_key"
                    base = cred.get("base_url") or DEFAULT_BASE.get(prov, "")
                    # secret no está en plain en pool a veces — fallback env por label
                    src = (cred.get("source") or "")
                    if src.startswith("env:"):
                        key_env = src.split(":", 1)[1]
                        key = env.get(key_env, "")
                    mapped = bool(key and base)
                    break
            if not mapped and not be:
                notes.append("provider_sin_mapeo")

    # Vector stack: independiente del chat model
    vector_ok = VECTOR_OK_DEFAULT
    # Opción 1 solo si OAuth roto Y política estricta — NO: user chose option 2
    # Si en el futuro: MAPPER_VECTOR_REQUIRE_CHAT_AUTH=1
    if os.getenv("MAPPER_VECTOR_REQUIRE_CHAT_AUTH", "0") in ("1", "true", "True"):
        vector_ok = mapped

    return {
        "provider": prov,
        "model": model,
        "auth_type": auth_type,  # api_key | oauth | none
        "base_url": base,
        "api_key": key,  # API key o access_token OAuth (chmod 600 en archivo)
        "key_env": key_env,
        "mapped": mapped,
        "oauth_ok": oauth_ok if auth_type == "oauth" else None,
        "vector_ok": vector_ok,  # Chroma+Ollama se pueden usar
        "notes": notes,
        "ts": time.time(),
        "source": {
            "env": str(ENV_PATH),
            "cfg": str(CFG_PATH),
            "auth": str(AUTH_PATH),
        },
    }


def _sig(datos: dict) -> str:
    return "|".join(
        [
            str(datos.get("provider")),
            str(datos.get("model")),
            str(datos.get("auth_type")),
            str(datos.get("mapped")),
            str(bool(datos.get("api_key"))),
            str(datos.get("vector_ok")),
        ]
    )


def escribir_atomico(datos: dict, path: Path = OUT_PATH, *, force_warn: bool = False) -> None:
    global _prev_sig
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    sig = _sig(datos)
    changed = sig != _prev_sig

    log.info(
        "escribiendo %s  provider=%s model=%s auth=%s mapped=%s vector_ok=%s base_url=%s",
        path.name,
        datos.get("provider"),
        datos.get("model"),
        datos.get("auth_type"),
        datos.get("mapped"),
        datos.get("vector_ok"),
        datos.get("base_url") or "(vacío)",
    )

    # WARNING solo si cambió el estado (o force) — evita spam en heartbeat
    if changed or force_warn:
        if not datos.get("mapped"):
            log.warning(
                "chat no mapeado provider=%r auth_type=%s notes=%s "
                "(vector_ok=%s — Chroma/Ollama siguen disponibles)",
                datos.get("provider"),
                datos.get("auth_type"),
                datos.get("notes"),
                datos.get("vector_ok"),
            )
        elif datos.get("auth_type") == "oauth":
            log.info(
                "OAuth OK provider=%s — token presente; vector_ok=%s",
                datos.get("provider"),
                datos.get("vector_ok"),
            )
        if not datos.get("vector_ok"):
            log.warning("vector_ok=false — política desactiva Chroma/Ollama para este estado")

    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        _prev_sig = sig
    except OSError as e:
        log.error("fallo al escribir %s: %s", path, e)
        raise


def _evento_relevante(nombre: str) -> bool:
    if not nombre:
        return False
    return nombre in (
        ENV_PATH.name,
        CFG_PATH.name,
        AUTH_PATH.name,
    ) or nombre.endswith((".env", "config.yaml", "auth.json"))


def main() -> None:
    log.info("CredentialMapper arrancando (watcher inotify + OAuth auth.json)")
    try:
        fd = _inotify_init()
    except OSError as e:
        log.error("no se pudo iniciar inotify: %s", e)
        raise

    watched = set()
    for p in (ENV_PATH, CFG_PATH, AUTH_PATH):
        d = str(p.parent)
        if d not in watched:
            try:
                _inotify_add_watch(fd, d, MASK)
                watched.add(d)
                log.info("watch dir: %s", d)
            except OSError as e:
                log.error("no se pudo vigilar %s: %s", d, e)
                raise

    log.info(
        "CredentialMapper activa → %s | logs → %s | auth → %s",
        OUT_PATH,
        LOG_DIR,
        AUTH_PATH,
    )
    escribir_atomico(construir(), force_warn=True)

    pendiente = False
    ultimo_ev = 0.0
    ultimo_hb = time.time()
    escrituras = 1

    while True:
        try:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                data = os.read(fd, 65536)
                off = 0
                while off + 16 <= len(data):
                    _wd, _mask, _cookie, ln = struct.unpack("iIII", data[off : off + 16])
                    off += 16
                    nombre = data[off : off + ln].split(b"\0", 1)[0].decode(errors="ignore")
                    off += ln
                    if _evento_relevante(nombre):
                        pendiente = True
                        ultimo_ev = time.time()
                        log.info("evento inotify: %s", nombre or "(dir)")

            now = time.time()
            if pendiente and (now - ultimo_ev) >= DEBOUNCE:
                escribir_atomico(construir())
                pendiente = False
                ultimo_hb = now
                escrituras += 1

            if (now - ultimo_hb) >= HEARTBEAT_SEC:
                d = construir()
                # heartbeat: escribe ts; WARNING solo si cambió el estado
                escribir_atomico(d)
                ultimo_hb = now
                log.info(
                    "heartbeat ok (escrituras=%d mapped=%s auth=%s)",
                    escrituras,
                    d.get("mapped"),
                    d.get("auth_type"),
                )
        except Exception as e:
            log.error("error en bucle principal: %s", e, exc_info=True)
            time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error("CredentialMapper terminó con error fatal: %s", e, exc_info=True)
        raise
