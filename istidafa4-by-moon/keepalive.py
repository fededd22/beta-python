"""
Keep-Alive automatique + petit serveur web (Flask).

Fonctionne exactement comme le keep-alive du projet précédent (server.ts) :

  1. Le domaine public est détecté automatiquement à partir des en-têtes
     `X-Forwarded-Host` / `Host` des requêtes reçues (ou fourni via APP_URL).
     Il est mémorisé dans DATA_DIR/detected-host.json pour survivre aux
     redémarrages.
  2. Toutes les 30 secondes, le bot appelle lui-même
     https://<domaine-public>/health afin que la plateforme d'hébergement ne
     le considère pas comme inactif.

Aucune URL n'est codée en dur et aucune configuration manuelle n'est requise.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from threading import Thread
from urllib.parse import urlparse

import requests
from flask import Flask, request

# ==================== CONFIGURATION ====================
# Port d'écoute : injecté par la plateforme via PORT (voir docker-entrypoint.sh).
PORT = int(os.environ.get("PORT") or 8080)

# Dossier des données persistantes (detected-host.json, scripts, ...).
DATA_DIR = os.environ.get("DATA_DIR") or os.getcwd()
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except OSError:
    pass  # les écritures individuelles loggent leurs propres erreurs

KEEP_ALIVE_INTERVAL_S = int(os.environ.get("KEEP_ALIVE_INTERVAL") or 30)
KEEP_ALIVE_TIMEOUT_S = 10

DETECTED_HOST_FILE = os.path.join(DATA_DIR, "detected-host.json")

_cached_public_host = None
_last_ping = {"ok": None, "status": None, "ms": None, "at": None, "error": None}


def add_log(message: str) -> None:
    """Log horodaté (même format que le projet précédent)."""
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    print(f"[{ts}] {message}", flush=True)


# ==================== DÉTECTION DU DOMAINE PUBLIC ====================
def _is_likely_public_host(host: str) -> bool:
    host = (host or "").split(":")[0].strip().lower()
    if not host or host in ("localhost", "0.0.0.0"):
        return False
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        return False
    return "." in host


def _remember_public_host(host: str) -> None:
    global _cached_public_host
    host = (host or "").split(":")[0].strip().lower()
    if not _is_likely_public_host(host) or host == _cached_public_host:
        return
    _cached_public_host = host
    try:
        with open(DETECTED_HOST_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"host": host, "updatedAt": datetime.now(timezone.utc).isoformat()},
                f, indent=2,
            )
    except OSError:
        pass  # best-effort uniquement
    add_log(f"Auto-detected public domain: {host}")


def _load_persisted_host() -> None:
    global _cached_public_host
    try:
        if os.path.exists(DETECTED_HOST_FILE):
            with open(DETECTED_HOST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("host") and _is_likely_public_host(data["host"]):
                _cached_public_host = data["host"]
    except (OSError, ValueError):
        pass


_load_persisted_host()


def get_public_domain() -> str:
    """APP_URL (si défini) > domaine auto-détecté > chaîne vide."""
    app_url = os.environ.get("APP_URL", "").strip()
    if app_url:
        parsed = urlparse(app_url if "://" in app_url else f"https://{app_url}")
        if parsed.hostname:
            return parsed.hostname
    return _cached_public_host or ""


# ==================== SERVEUR WEB (FLASK) ====================
app = Flask(__name__)
# /health est appelé toutes les 30 s : on évite de polluer les logs.
logging.getLogger("werkzeug").setLevel(logging.WARNING)


@app.before_request
def _detect_host_from_request():
    forwarded = request.headers.get("X-Forwarded-Host") or request.headers.get("Host")
    if forwarded:
        _remember_public_host(forwarded.split(",")[0].strip())


@app.route("/")
def index():
    return "Bot is alive and running!"


@app.route("/health")
def health():
    return "OK", 200


def _run_flask() -> None:
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)


def start_web_server() -> None:
    """Démarre Flask dans un thread séparé."""
    Thread(target=_run_flask, daemon=True).start()
    add_log(f"Web server (Flask) listening on http://0.0.0.0:{PORT}")


# ==================== KEEP-ALIVE AUTOMATIQUE ====================
def _ping_self_blocking() -> None:
    domain = get_public_domain()
    if not domain:
        return
    url = f"https://{domain}/health"
    start = time.monotonic()
    try:
        res = requests.get(
            url,
            timeout=KEEP_ALIVE_TIMEOUT_S,
            headers={"User-Agent": "KeepAlive/1.0"},
        )
        ms = int((time.monotonic() - start) * 1000)
        icon = "✅" if res.status_code == 200 else f"⚠️{res.status_code}"
        add_log(f"[Keep-Alive] {icon} {url} ({ms}ms)")
        _last_ping.update(ok=res.status_code == 200, status=res.status_code,
                          ms=ms, at=datetime.now(timezone.utc).isoformat(), error=None)
    except requests.RequestException as e:
        add_log(f"[Keep-Alive] ❌ {url} -- {e}")
        _last_ping.update(ok=False, status=None, ms=None,
                          at=datetime.now(timezone.utc).isoformat(), error=str(e))


async def keep_alive_task() -> None:
    """Boucle infinie : ping du domaine public toutes les KEEP_ALIVE_INTERVAL_S s."""
    add_log(f"[Keep-Alive] Started -- self-pinging every {KEEP_ALIVE_INTERVAL_S}s.")
    waiting_logs = 0
    while True:
        try:
            if get_public_domain():
                waiting_logs = 0
                # requests est bloquant -> thread séparé pour ne pas figer le bot
                await asyncio.to_thread(_ping_self_blocking)
            else:
                waiting_logs += 1
                if waiting_logs == 1 or waiting_logs % 10 == 0:
                    add_log("[Keep-Alive] Public domain not detected yet -- waiting for the "
                            "first incoming request (or set APP_URL).")
        except Exception as e:  # ne jamais tuer la boucle
            add_log(f"[Keep-Alive] Unexpected error: {e}")
        await asyncio.sleep(KEEP_ALIVE_INTERVAL_S)


def get_status() -> dict:
    return {
        "domain": get_public_domain() or None,
        "interval_s": KEEP_ALIVE_INTERVAL_S,
        "port": PORT,
        "last_ping": dict(_last_ping),
    }
