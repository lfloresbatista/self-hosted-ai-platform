#!/usr/bin/env python3
"""
Register / ensure CredentialMapper as an s6 longrun under Nidavellir (Hermes container).

Survives: process crash (s6 restarts it).
Re-register on boot: call ensure via cont-init mount or ensure.sh (see docs).

Usage:
  /opt/data/.hermes/vector/.venv/bin/python install_s6.py
  /opt/data/.hermes/vector/.venv/bin/python install_s6.py --ensure
  /opt/data/.hermes/vector/.venv/bin/python install_s6.py --uninstall
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

S6_BIN = Path("/command")
SCANDIR = Path("/run/service")
SVC_NAME = "mapper"
SVC_DIR = SCANDIR / SVC_NAME
VECTOR_DIR = Path("/opt/data/.hermes/vector")
VENV_PY = VECTOR_DIR / ".venv" / "bin" / "python"
MAPPER_PY = VECTOR_DIR / "credential_mapper.py"
LOG_DIR = Path("/opt/data/.hermes/vector/logs/s6-mapper")
STATE_FILE = VECTOR_DIR / "supervise" / "enabled"


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=check)


def _seed_supervise_skeleton(svc_dir: Path) -> None:
    """Match Hermes service_manager._seed_supervise_skeleton (hermes-owned)."""
    event = svc_dir / "event"
    event.mkdir(exist_ok=True)
    os.chmod(event, 0o3730)
    sup = svc_dir / "supervise"
    sup.mkdir(exist_ok=True)
    os.chmod(sup, 0o755)
    se = sup / "event"
    se.mkdir(exist_ok=True)
    os.chmod(se, 0o3730)
    control = sup / "control"
    if not control.exists():
        os.mkfifo(control, 0o660)


def _render_run() -> str:
    return f"""#!/command/with-contenv sh
# shellcheck shell=sh
set -e
export HOME=/opt/data
cd /opt/data/.hermes/vector
# Load secrets for any child tools; CredentialMapper itself reads files from disk
set -a
[ -f /opt/data/.env ] && . /opt/data/.env
set +a
export MAPPER_LOG_CONSOLE=0
if [ ! -x "{VENV_PY}" ]; then
  echo "[mapper] missing venv python at {VENV_PY}" >&2
  exit 78
fi
if [ ! -f "{MAPPER_PY}" ]; then
  echo "[mapper] missing {MAPPER_PY}" >&2
  exit 78
fi
[ "$(id -u)" = 0 ] || exec "{VENV_PY}" "{MAPPER_PY}"
exec s6-setuidgid hermes "{VENV_PY}" "{MAPPER_PY}"
"""


def _render_finish() -> str:
    return """#!/command/with-contenv sh
# shellcheck shell=sh
# $1 = exit code from run
if [ "$1" = "78" ]; then
  exit 125
fi
exit 0
"""


def _render_log_run() -> str:
    return f"""#!/command/with-contenv sh
# shellcheck shell=sh
log_dir="{LOG_DIR}"
mkdir -p "$log_dir"
chown hermes:hermes "$log_dir" 2>/dev/null || true
rm -f "$log_dir/lock"
[ "$(id -u)" = 0 ] || exec s6-log 1 n20 s1000000 T "$log_dir"
exec s6-setuidgid hermes s6-log 1 n20 s1000000 T "$log_dir"
"""


def is_up() -> bool:
    if not SVC_DIR.exists():
        return False
    try:
        r = _run([str(S6_BIN / "s6-svstat"), str(SVC_DIR)], check=False)
        return r.returncode == 0 and "up " in (r.stdout or "")
    except Exception:
        return False


def stop_loose_processes() -> None:
    """Kill non-s6 credential_mapper.py started manually (best-effort)."""
    subprocess.run(
        ["pkill", "-f", r"[.]venv/bin/python mapper\.py"],
        check=False,
        capture_output=True,
    )


def uninstall() -> None:
    if SVC_DIR.exists():
        subprocess.run(
            [str(S6_BIN / "s6-svc"), "-d", str(SVC_DIR)],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            [str(S6_BIN / "s6-svwait"), "-d", str(SVC_DIR)],
            check=False,
            capture_output=True,
            timeout=20,
        )
        shutil.rmtree(SVC_DIR, ignore_errors=True)
        subprocess.run(
            [str(S6_BIN / "s6-svscanctl"), "-a", str(SCANDIR)],
            check=False,
            capture_output=True,
        )
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    print("mapper s6: uninstalled")


def install(*, start: bool = True) -> None:
    if not SCANDIR.is_dir():
        raise SystemExit("not an s6 Hermes container (/run/service missing)")
    if not VENV_PY.is_file() or not MAPPER_PY.is_file():
        raise SystemExit(f"missing {VENV_PY} or {MAPPER_PY}")

    stop_loose_processes()

    if SVC_DIR.exists() and is_up():
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text("1\n")
        print("mapper s6: already up")
        return

    if SVC_DIR.exists():
        # recreate clean
        subprocess.run([str(S6_BIN / "s6-svc"), "-d", str(SVC_DIR)], check=False)
        shutil.rmtree(SVC_DIR, ignore_errors=True)

    tmp = SCANDIR / f".{SVC_NAME}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    try:
        (tmp / "type").write_text("longrun\n")
        run = tmp / "run"
        run.write_text(_render_run())
        run.chmod(0o755)
        fin = tmp / "finish"
        fin.write_text(_render_finish())
        fin.chmod(0o755)
        log_sub = tmp / "log"
        log_sub.mkdir()
        log_run = log_sub / "run"
        log_run.write_text(_render_log_run())
        log_run.chmod(0o755)
        _seed_supervise_skeleton(tmp)
        if not start:
            (tmp / "down").touch()
        tmp.rename(SVC_DIR)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    r = _run([str(S6_BIN / "s6-svscanctl"), "-a", str(SCANDIR)], check=False)
    if r.returncode != 0:
        shutil.rmtree(SVC_DIR, ignore_errors=True)
        raise SystemExit(f"s6-svscanctl failed: {r.stderr or r.stdout}")

    if start:
        _run([str(S6_BIN / "s6-svc"), "-u", str(SVC_DIR)], check=False)
        # brief wait
        subprocess.run(
            [str(S6_BIN / "s6-svwait"), "-u", str(SVC_DIR)],
            check=False,
            timeout=15,
            capture_output=True,
        )

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text("1\n")
    st = _run([str(S6_BIN / "s6-svstat"), str(SVC_DIR)], check=False)
    print("mapper s6:", (st.stdout or st.stderr or "").strip())


def ensure() -> None:
    """Idempotent: if enabled marker set, register+start if needed."""
    if not STATE_FILE.exists() and not (SCANDIR / SVC_NAME).exists():
        # first-time: if VECTOR wants always-on, treat missing marker as install
        # Only auto-install when called from boot with ENABLED default
        if os.environ.get("MAPPER_S6_AUTO", "1") not in ("1", "true", "TRUE"):
            print("mapper s6: not enabled (no marker); skip")
            return
    if is_up():
        print("mapper s6: ok (up)")
        return
    install(start=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="CredentialMapper s6 supervisor helper")
    ap.add_argument("--ensure", action="store_true", help="idempotent start if enabled")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.uninstall:
        uninstall()
        return
    if args.status:
        print("up" if is_up() else "down")
        if SVC_DIR.exists():
            print(_run([str(S6_BIN / "s6-svstat"), str(SVC_DIR)], check=False).stdout)
        return
    if args.ensure:
        ensure()
        return
    install(start=True)


if __name__ == "__main__":
    main()
