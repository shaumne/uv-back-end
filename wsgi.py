"""
WSGI entry point for PythonAnywhere (and other WSGI hosts).

FastAPI is ASGI; this file wraps it with a2wsgi so the app can run
on PythonAnywhere's WSGI server.

On PythonAnywhere, set: WSGI configuration file = /home/KULLANICI/.../wsgi.py
and ensure the project directory and virtualenv path are correct.
"""
import sys
from pathlib import Path

# Project root = directory containing this wsgi.py (backend/)
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from a2wsgi import ASGIMiddleware
from app.main import app

application = ASGIMiddleware(app)
