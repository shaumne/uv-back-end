"""
Gunicorn production configuration for the UV Dosimeter API.

Usage:
    gunicorn -c gunicorn.conf.py app.main:app

Worker model:
    UvicornWorker — runs FastAPI/ASGI apps under Gunicorn's process manager.
    Provides multi-process fault isolation + Uvicorn's async event loop.

Scaling:
    workers = (2 × CPU cores) + 1  — standard recommended formula.
    Adjust via the GUNICORN_WORKERS environment variable for containerised
    environments where the CPU count may differ from the host.

Timeouts:
    timeout = 120 s — generous for computer vision endpoints that may
                       spend up to 60 s on large images.
    keepalive = 5   — reuse connections from mobile clients (HTTP/1.1).
"""
import multiprocessing
import os

# ── Binding ───────────────────────────────────────────────────────────────────
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# ── Worker configuration ──────────────────────────────────────────────────────
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(
    os.getenv("GUNICORN_WORKERS", (multiprocessing.cpu_count() * 2) + 1)
)
worker_connections = 1000
threads = 1  # UvicornWorker is single-threaded async; threads > 1 not needed

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout = 120          # Generous timeout for CV pipeline
graceful_timeout = 30  # Allow in-flight requests to finish on reload/shutdown
keepalive = 5

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "-"        # stdout
errorlog = "-"         # stderr
loglevel = os.getenv("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)sμs'

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = "uv_dosimeter_api"

# ── Security ──────────────────────────────────────────────────────────────────
# Forward real client IP from reverse proxy (nginx / Cloud Run).
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
