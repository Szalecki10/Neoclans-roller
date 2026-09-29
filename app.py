"""
Neoclans Roller – serwer (Flask).

Lokalnie:   python app.py            -> http://localhost:5000
Na Renderze: gunicorn app:app        (patrz render.yaml i README.md)
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import threading
import time
from datetime import timedelta
from functools import wraps

from flask import Flask, jsonify, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

import genetics
from storage import open_store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(BASE_DIR, "seed_config.json")

# Windows potrafi mieć w rejestrze .js = text/plain, a przeglądarka wtedy nie załaduje modułów.
mimetypes.add_type("text/javascript", ".js")

# --------------------------------------------------------------------------- hasło admina

# W kodzie jest tylko hash (scrypt), nie samo hasło. Zmiana hasła:
#   python -c "from werkzeug.security import generate_password_hash as g; print(g(input('Hasło: ')))"
# wklej wynik poniżej, commit, push. Zmiana hasła wylogowuje wszystkich.
ADMIN_PASSWORD_HASH = (
    "scrypt:32768:8:1$l19Kg9CYVjZ6ABtF$5e74a34696ad1294f32ca36665f91d907d95d9790b697d417ab5537327aaa6b0"
    "342e064cfb80a99eebec885885f5cc1219fae4444f2bc933edf78de91eacc289"
)

app = Flask(__name__, static_folder="static", static_url_path="")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")) or os.environ.get("COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
app.json.ensure_ascii = False
app.json.sort_keys = False

# --------------------------------------------------------------------------- konfiguracja (tabela genów)


def load_seed():
    with open(SEED_PATH, encoding="utf-8") as fh:
        config, errors, _ = genetics.clean_config(json.load(fh))
    if errors:
        raise RuntimeError("seed_config.json jest niepoprawny: " + "; ".join(errors))
    return config


class ConfigHolder:
    """Trzyma aktualną konfigurację w pamięci i co chwilę odświeża ją z bazy."""

    def __init__(self, store, ttl=30.0):
        self.store = store
        self.ttl = ttl
        self._lock = threading.Lock()
        self._data = None
        self._loaded_at = 0.0

    def get(self):
        with self._lock:
            if self._data is None or time.monotonic() - self._loaded_at > self.ttl:
                latest = self.store.latest()
                if latest is None:
                    data = load_seed()
                    self.store.save(data, "Dane startowe")
                else:
                    data = latest["data"]
                self._data = data
                self._loaded_at = time.monotonic()
            return self._data

    def replace(self, data):
        with self._lock:
            self._data = data
            self._loaded_at = time.monotonic()


store = open_store(BASE_DIR)
configs = ConfigHolder(store)

# Klucz podpisujący ciasteczko sesji: losowy, trzymany w bazie (nie w repo, bo z nim dałoby się
# podrobić logowanie). Doklejony hash hasła sprawia, że zmiana hasła unieważnia stare sesje.
app.secret_key = hashlib.sha256(
    (store.secret("session_key") + ADMIN_PASSWORD_HASH).encode()
).digest()

# --------------------------------------------------------------------------- pomocnicze


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def bad_request(message, errors=None):
    payload = {"error": message}
    if errors:
        payload["errors"] = errors
    return jsonify(payload), 400


def clamp_int(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return jsonify(error="Zaloguj się jako admin."), 401
        return view(*args, **kwargs)

    return wrapper


@app.errorhandler(HTTPException)
def http_error(exc):
    if request.path.startswith("/api/"):
        return jsonify(error=exc.description or exc.name), exc.code
    return exc


@app.errorhandler(Exception)
def unexpected_error(exc):
    app.logger.exception("Nieoczekiwany błąd")
    return jsonify(error="Coś poszło nie tak po stronie serwera."), 500


# --------------------------------------------------------------------------- strony


@app.get("/")
def index_page():
    return app.send_static_file("index.html")


@app.get("/admin")
def admin_page():
    return app.send_static_file("admin.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True)


# --------------------------------------------------------------------------- API publiczne


@app.get("/api/config")
def public_config():
    return jsonify(genetics.public_config(configs.get()))


@app.post("/api/roll")
def roll():
    data = body()
    config = configs.get()
    mode = data.get("mode")
    if mode not in {m["id"] for m in config["modes"]}:
        return bad_request("Wybierz tryb losowania.")
    sex = data.get("sex") if data.get("sex") in (genetics.FEMALE, genetics.MALE) else None
    count = clamp_int(data.get("count"), 1, 20, 1)
    cats = [genetics.describe(config, genetics.roll_cat(config, mode, sex)) for _ in range(count)]
    return jsonify(cats=cats)


@app.post("/api/parse")
def parse():
    """Sprawdza wpisany genotyp; gdy jest kompletny, od razu zwraca też opis kota."""
    data = body()
    sex = data.get("sex")
    if sex not in (genetics.FEMALE, genetics.MALE):
        return bad_request("Brak płci.")
    config = configs.get()
    result = genetics.parse_genotype(config, str(data.get("text") or "")[:2000], sex)
    if not result["errors"] and not result["missing"]:
        result["cat"] = genetics.describe(config, {"sex": sex, "genotype": result["genotype"]})
    return jsonify(result)


def parse_parent(config, text, sex, label):
    text = str(text or "")[:2000]
    if not text.strip():
        return None, [f"{label}: wpisz genotyp."]
    result = genetics.parse_genotype(config, text, sex)
    errors = [f"{label}: {e}" for e in result["errors"]]
    if result["missing"]:
        errors.append(f"{label}: brakuje genów {', '.join(result['missing'])}.")
    return result["genotype"], errors


@app.post("/api/breed")
def breed():
    data = body()
    config = configs.get()
    mother, errors = parse_parent(config, data.get("mother"), genetics.FEMALE, "Matka")
    father, father_errors = parse_parent(config, data.get("father"), genetics.MALE, "Ojciec")
    errors += father_errors
    if errors:
        return bad_request("Popraw genotypy rodziców.", errors)
    count = clamp_int(data.get("count"), 1, 12, 1)
    kittens = []
    for _ in range(count):
        kitten = genetics.roll_kitten(config, mother, father)
        described = genetics.describe(config, kitten)
        described["probability"] = kitten["probability"]
        kittens.append(described)
    return jsonify(
        mother=genetics.describe(config, {"sex": genetics.FEMALE, "genotype": mother}),
        father=genetics.describe(config, {"sex": genetics.MALE, "genotype": father}),
        kittens=kittens,
    )


# --------------------------------------------------------------------------- API admina

_failed_logins: dict[str, list[float]] = {}
_failed_lock = threading.Lock()


@app.post("/api/admin/login")
def login():
    ip = request.remote_addr or "?"
    now = time.time()
    with _failed_lock:
        recent = [t for t in _failed_logins.get(ip, []) if now - t < 15 * 60]
        _failed_logins[ip] = recent
        if len(recent) >= 10:
            return jsonify(error="Za dużo nieudanych prób. Spróbuj za kwadrans."), 429
    password = body().get("password")
    if not isinstance(password, str) or not check_password_hash(ADMIN_PASSWORD_HASH, password):
        with _failed_lock:
            _failed_logins.setdefault(ip, []).append(now)
        time.sleep(0.5)
        return jsonify(error="Złe hasło."), 401
    with _failed_lock:
        _failed_logins.pop(ip, None)
    session.clear()
    session["admin"] = True
    session.permanent = True
    return jsonify(ok=True)


@app.post("/api/admin/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/admin/me")
def me():
    return jsonify(admin=bool(session.get("admin")))


@app.get("/api/admin/config")
@require_admin
def admin_config():
    latest = store.latest()
    config = latest["data"] if latest else configs.get()
    return jsonify(
        config=config,
        versionId=latest["id"] if latest else None,
        savedAt=latest["createdAt"] if latest else None,
    )


@app.post("/api/admin/preview")
@require_admin
def admin_preview():
    config, errors, warnings = genetics.clean_config(body().get("config"))
    preview = None
    if not errors:
        preview = genetics.preview(config)
    return jsonify(errors=errors, warnings=warnings, preview=preview)


@app.put("/api/admin/config")
@require_admin
def admin_save():
    data = body()
    config, errors, warnings = genetics.clean_config(data.get("config"))
    if errors:
        return bad_request("Popraw błędy przed zapisem.", errors)
    note = str(data.get("note") or "Zapis z panelu admina")[:200]
    version_id = store.save(config, note)
    configs.replace(config)
    return jsonify(config=config, versionId=version_id, warnings=warnings)


@app.get("/api/admin/versions")
@require_admin
def admin_versions():
    return jsonify(versions=store.versions())


@app.get("/api/admin/versions/<int:version_id>")
@require_admin
def admin_version(version_id):
    version = store.version(version_id)
    if version is None:
        return jsonify(error="Nie ma takiej wersji."), 404
    return jsonify(version)


if __name__ == "__main__":
    configs.get()  # utwórz dane startowe od razu
    port = int(os.environ.get("PORT", "5000"))
    print(f"[neoclans] http://localhost:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
