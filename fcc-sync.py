#!/usr/bin/env python3
"""fcc-sync — export/import free-claude-code configuration between devices.

Bundles ~/.fcc/.env (every provider key, base URL, and routing setting)
plus all OAuth login tokens in ~/.fcc/auth/ into one small tarball, and
restores it anywhere — installing free-claude-code itself via uv if the
target machine doesn't have it. Pure stdlib; runs on Linux, macOS, and
Windows.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

FCC_DIR = Path.home() / ".fcc"
ENV_FILE = FCC_DIR / ".env"
AUTH_DIR = FCC_DIR / "auth"
LOG_FILE = FCC_DIR / "logs" / "server.log"
LOCAL_BIN = Path.home() / ".local" / "bin"

IS_WINDOWS = os.name == "nt"
DEFAULT_PORT = 8082


def die(msg: str) -> "None":
    print(f"fcc-sync: {msg}", file=sys.stderr)
    raise SystemExit(1)


# ---------------------------------------------------------------- config

def env_value(key: str, default: str) -> str:
    """Read KEY=... from ~/.fcc/.env (last definition wins, like fcc)."""
    if not ENV_FILE.is_file():
        return default
    found = default
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            found = line.split("=", 1)[1].strip()
    return found


def fcc_host() -> str:
    host = env_value("HOST", "127.0.0.1")
    return "127.0.0.1" if host in {"0.0.0.0", "::", "[::]", ""} else host


def fcc_port() -> int:
    try:
        return int(env_value("PORT", str(DEFAULT_PORT)))
    except ValueError:
        return DEFAULT_PORT


def status_url() -> str:
    return f"http://{fcc_host()}:{fcc_port()}/admin/api/status"


# ---------------------------------------------------------------- http

def get_json(url: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def server_up(timeout: float = 3.0) -> bool:
    return get_json(status_url(), timeout=timeout) is not None


def port_open(timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((fcc_host(), fcc_port()), timeout=timeout):
            return True
    except OSError:
        return False


def provider_count() -> int | None:
    d = get_json(status_url())
    if not d:
        return None
    return sum(1 for p in d.get("provider_status", [])
               if p.get("status") not in ("missing_key", "missing_config", "disconnected"))


# ---------------------------------------------------------------- discovery

def fcc_version() -> str:
    # Best source: uv's own tool listing (cross-platform).
    uv = find_uv()
    if uv:
        try:
            out = subprocess.run([uv, "tool", "list"], capture_output=True,
                                 text=True, timeout=30).stdout
            for line in out.splitlines():
                if line.startswith("free-claude-code"):
                    for part in line.split():
                        if part.startswith("v"):
                            return part[1:]
        except (OSError, subprocess.SubprocessError):
            pass
    # Fallback: dist-info directories in uv's tool environments.
    roots = [Path.home() / ".local" / "share" / "uv" / "tools"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "uv" / "tools")
    for root in roots:
        for pattern in ("free-claude-code/lib/python*/site-packages/free_claude_code-*.dist-info",
                        "free-claude-code/Lib/site-packages/free_claude_code-*.dist-info"):
            for dist in root.glob(pattern):
                name = dist.name
                return name[len("free_claude_code-"):-len(".dist-info")]
    return "unknown"


def _which_any(name: str) -> Path | None:
    """Find an executable by name, also checking ~/.local/bin (often off PATH)."""
    found = shutil.which(name)
    if found:
        return Path(found)
    for candidate in (LOCAL_BIN / name, LOCAL_BIN / (name + ".exe")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def find_fcc_server() -> Path | None:
    for name in ("fcc-server", "fcc-server.exe"):
        found = _which_any(name)
        if found:
            return found
    return None


def find_uv() -> Path | None:
    for name in ("uv", "uv.exe"):
        found = _which_any(name)
        if found:
            return found
    return None


# ---------------------------------------------------------------- server lifecycle

def stop_server() -> None:
    if not port_open():
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/IM", "fcc-server.exe"],
                       capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "fcc-server"], capture_output=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not port_open():
            return
        time.sleep(0.5)
    print("fcc-sync: warning: server still responding after stop attempt",
          file=sys.stderr)


def start_server() -> bool:
    server_bin = find_fcc_server()
    if not server_bin:
        die("fcc-server not found")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    with open(LOG_FILE, "ab") as log:
        subprocess.Popen([str(server_bin)], stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, **kwargs)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if server_up():
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------- export

def cmd_export(args: argparse.Namespace) -> int:
    if not ENV_FILE.is_file():
        die("no ~/.fcc/.env found — nothing to export")

    out = Path(args.file) if args.file else Path.home() / (
        f"fcc-backup-{_dt.datetime.now():%Y%m%d-%H%M}.tar.gz")
    count = provider_count()

    with tempfile.TemporaryDirectory() as tmp:
        manifest = {
            "tool": "fcc-sync",
            "fcc_version": fcc_version(),
            "exported_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "hostname": platform.node(),
            "configured_providers": count,
        }
        manifest_path = Path(tmp) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        with tarfile.open(out, "w:gz") as tf:
            tf.add(ENV_FILE, arcname=".env")
            # Every OAuth token file, whatever provider it belongs to.
            if AUTH_DIR.is_dir():
                for f in sorted(AUTH_DIR.glob("*.json")):
                    tf.add(f, arcname=f"auth/{f.name}")
            tf.add(manifest_path, arcname="manifest.json")

    if not IS_WINDOWS:
        os.chmod(out, 0o600)

    print(f"Exported {count if count is not None else '?'} providers "
          f"(fcc {fcc_version()}) -> {out} ({out.stat().st_size / 1024:.1f}K)")
    print()
    print("Move it to your other device, then run:")
    print(f'  scp "{out}" <user>@<host>:')
    print("  fcc-sync import ~/fcc-backup-*.tar.gz")
    return 0


# ---------------------------------------------------------------- import

def _extract_member(tf: tarfile.TarFile, member: tarfile.TarInfo, dest: Path) -> None:
    src = tf.extractfile(member)
    if src is None:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as out:
        shutil.copyfileobj(src, out)


def _norm_member(name: str) -> str:
    """Normalize a tar member name ('./.env' and '.env' are the same file)."""
    while name.startswith("./"):
        name = name[2:]
    return name


def cmd_import(args: argparse.Namespace) -> int:
    file = Path(args.file)
    if not file.is_file():
        die(f"file not found: {file}")

    try:
        tf = tarfile.open(file, "r:gz")
    except (tarfile.TarError, OSError):
        die(f"not a valid tar.gz archive: {file}")

    with tf:
        names = {_norm_member(m.name) for m in tf.getmembers()}
        if ".env" not in names:
            die(f"not an fcc-sync backup (no .env inside): {file}")

        print(f"Importing {file}")

        # 1. Back up any existing config first.
        if ENV_FILE.is_file():
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            bak = ENV_FILE.with_name(f".env.bak-{stamp}")
            shutil.copy2(ENV_FILE, bak)
            print(f"  existing config backed up -> {bak}")

        # 2. Stop the server so it doesn't race the file swap.
        if port_open():
            print("  stopping fcc server...")
            stop_server()

        # 3. Restore: .env plus every auth token (never session data or caches).
        restored = []
        for m in tf.getmembers():
            name = _norm_member(m.name)
            if name == ".env":
                _extract_member(tf, m, ENV_FILE)
                restored.append(".env")
            elif name.startswith("auth/") and name.endswith(".json"):
                _extract_member(tf, m, FCC_DIR / name)
                restored.append(name)
        if not IS_WINDOWS:
            ENV_FILE.chmod(0o600)
            for f in AUTH_DIR.glob("*.json"):
                f.chmod(0o600)
        print(f"  restored {', '.join(restored) or 'nothing'}")

    # 4. Install fcc if this device doesn't have it.
    if not find_fcc_server():
        print("  fcc not installed — installing via uv...")
        uv_bin = find_uv()
        if not uv_bin:
            print("  uv not found — installing uv first...")
            if IS_WINDOWS:
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                "-Command", "irm https://astral.sh/uv/install.ps1 | iex"],
                               check=False)
            else:
                subprocess.run("curl -LsSf https://astral.sh/uv/install.sh | sh",
                               shell=True, check=False)
            uv_bin = find_uv()
            if not uv_bin:
                die("could not install uv; get it from https://docs.astral.sh/uv/ "
                    "and re-run")
        subprocess.run([str(uv_bin), "tool", "install", "free-claude-code"],
                       check=False)
        if not find_fcc_server():
            die("fcc-server still not available after install attempt")

    # 5. Start the server and wait for the admin API.
    print("  starting fcc server...")
    if not start_server():
        die(f"server did not come up within 30s — check {LOG_FILE}")

    # 6. Summarise.
    d = get_json(status_url())
    count = provider_count()
    model = f"{d.get('model', '?')} ({d.get('provider', '?')})" if d else "?"
    print()
    print(f"Done. {count if count is not None else '?'} providers configured, "
          f"active model: {model}")
    print("Note: ChatGPT/Copilot logins may need re-doing if their tokens are "
          "machine-bound —")
    print(f"check http://{fcc_host()}:{fcc_port()}/admin if those providers "
          "show as disconnected.")
    return 0


# ---------------------------------------------------------------- status

def cmd_status(_: argparse.Namespace) -> int:
    d = get_json(status_url())
    if not d:
        print(f"fcc server: not running ({status_url()})")
        return 0
    print(f"fcc server:  running on {d.get('host', '?')}:{d.get('port', '?')}")
    print(f"active model: {d.get('model', '?')} ({d.get('provider', '?')})")
    provs = [p for p in d.get("provider_status", [])
             if p.get("status") not in ("missing_key", "missing_config", "disconnected")]
    print(f"providers:    {len(provs)} configured")
    for p in provs:
        print(f"  - {p.get('provider_id', '?'):<20} {p.get('display_name', '')}")
    return 0


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fcc-sync",
        description="export/import free-claude-code config between devices")
    sub = parser.add_subparsers(dest="command")

    p_export = sub.add_parser("export", help="bundle ~/.fcc/.env + OAuth tokens")
    p_export.add_argument("file", nargs="?", help="output tarball (default "
                            "~/fcc-backup-<date>.tar.gz)")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="restore a bundle")
    p_import.add_argument("file", help="backup tarball to import")
    p_import.set_defaults(func=cmd_import)

    p_status = sub.add_parser("status", help="server state, model, providers")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
