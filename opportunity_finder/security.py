"""Local-only protections: host allow-list, CSRF tokens and security headers.

The app has no login because it binds to 127.0.0.1. These checks stop a web page
open in the same browser from driving the app (CSRF) or reaching it through a
DNS-rebinding trick (Host header check).
"""
from __future__ import annotations

import hmac
import secrets

from flask import Flask, abort, request, session
from werkzeug.exceptions import BadRequest

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'")


def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


class CSRFError(BadRequest):
    friendly = "Your page was open too long or came from somewhere else. Reload the page and try again."


def init_security(app: Flask) -> None:
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def _check_host():
        host = (request.host or "").rsplit(":", 1)[0].lower() if not request.host.startswith("[") else request.host.split("]")[0] + "]"
        allowed = app.config["ALLOWED_HOSTS"]
        # An entry starting with a dot allows every subdomain of it, e.g. ".up.railway.app".
        if host not in allowed and not any(entry.startswith(".") and host.endswith(entry) for entry in allowed):
            abort(400)

    @app.before_request
    def _check_csrf():
        if not app.config.get("CSRF_ENABLED", True) or request.method in SAFE_METHODS:
            return
        expected = session.get("_csrf")
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not expected or not sent or not hmac.compare_digest(str(expected), str(sent)):
            raise CSRFError()

    @app.after_request
    def _headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", CSP)
        return response
