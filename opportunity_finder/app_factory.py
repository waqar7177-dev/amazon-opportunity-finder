"""Flask application factory."""
from __future__ import annotations

import logging
import uuid
from logging.handlers import RotatingFileHandler

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from config import Config

from . import constants
from .database.db import connect, init_db
from .formatting import fmt_ago, fmt_date, fmt_datetime, fmt_int, fmt_money, fmt_number, fmt_pct, fmt_weight
from .security import init_security
from .services.product_service import ProductService

log = logging.getLogger("opportunity_finder")


def get_conn():
    if "db" not in g:
        from flask import current_app
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def get_service() -> ProductService:
    if "service" not in g:
        g.service = ProductService(get_conn())
    return g.service


def get_runner():
    from flask import current_app
    return current_app.extensions["research_runner"]


def _init_research(app: Flask, config: Config) -> None:
    from .database.research_repository import ResearchRepository
    from .services.research_jobs import ResearchRunner, browser_source_factory

    factory = config.RESEARCH_SOURCE_FACTORY or browser_source_factory(config.DATA_DIR)
    runner = ResearchRunner(config.DATABASE_PATH, factory, background=not config.RESEARCH_SYNC)
    app.extensions["research_runner"] = runner
    conn = connect(config.DATABASE_PATH)
    try:
        repo = ResearchRepository(conn)
        interrupted = repo.mark_interrupted()
        queued = repo.queued_search_ids()
        conn.commit()
    finally:
        conn.close()
    if interrupted:
        log.info("%s brand search(es) marked interrupted at start-up", interrupted)
    if queued:
        runner.wake()


def create_app(config: Config | None = None) -> Flask:
    config = config or Config()
    app = Flask(__name__)
    app.config.from_mapping(config.as_flask_mapping())
    app.config["DATABASE_PATH"] = config.DATABASE_PATH
    app.config["APP_CONFIG"] = config

    for folder in (config.DATA_DIR, config.LOG_DIR, config.BACKUP_DIR, config.IMPORT_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    _configure_logging(app, config)
    init_db(config.DATABASE_PATH)
    init_security(app)
    _init_research(app, config)

    @app.teardown_appcontext
    def _close_db(exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    _register_template_helpers(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    log.info("App started; database at %s", config.DATABASE_PATH)
    return app


def _configure_logging(app: Flask, config: Config) -> None:
    if any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        return
    handler = RotatingFileHandler(config.LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    handler.setLevel(logging.INFO)
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def _register_template_helpers(app: Flask) -> None:
    # Never reuse a Jinja built-in filter name here (int, round, list, default…): the app filter
    # silently replaces the built-in everywhere, including template arithmetic. See docs/FAILURES.md F2.
    custom_filters = dict(money=fmt_money, pct=fmt_pct, whole=fmt_int, number=fmt_number, weight=fmt_weight,
                          datetime=fmt_datetime, date=fmt_date, ago=fmt_ago)
    clashes = set(custom_filters) & set(app.jinja_env.filters)
    if clashes:  # pragma: no cover - guarded by tests
        raise RuntimeError(f"Custom template filters would shadow Jinja built-ins: {sorted(clashes)}")
    app.jinja_env.filters.update(custom_filters)
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    # Names used inside imported macros must be Jinja globals: `{% from ... import %}` macros never
    # see context-processor variables. See docs/FAILURES.md F3.
    app.jinja_env.globals.update(C=constants, APP_NAME=constants.APP_NAME, APP_VERSION=constants.APP_VERSION)

    @app.context_processor
    def _per_request():
        return {"active": getattr(g, "active_nav", "")}


def _register_blueprints(app: Flask) -> None:
    from .routes import api, dashboard, exports, imports, opportunities, products, research, settings

    for module in (dashboard, research, products, opportunities, imports, settings, exports, api):
        app.register_blueprint(module.bp)


def _register_error_handlers(app: Flask) -> None:
    messages = {
        400: ("Something in that request wasn't right", "Go back, reload the page and try again."),
        403: ("That action isn't allowed", "Reload the page and try again."),
        404: ("Page not found", "The product or page you were looking for doesn't exist. It may have been deleted."),
        405: ("That action isn't available here", "Use the buttons in the app rather than typing the address."),
        413: ("That file is too large", "Upload files up to 10 MB. Split large imports into smaller files."),
    }

    def wants_json() -> bool:
        return request.path.startswith("/api/")

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        title, hint = messages.get(exc.code, ("Something went wrong", "Please try again."))
        description = getattr(exc, "friendly", None) or hint
        if wants_json():
            return jsonify({"ok": False, "error": description}), exc.code
        return render_template("error.html", code=exc.code, title=title, message=description), exc.code

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        ref = uuid.uuid4().hex[:8].upper()
        log.exception("Unhandled error ref=%s path=%s", ref, request.path)
        message = f"The app hit an unexpected problem. Your data is safe. Reference {ref} is in data/logs/app.log."
        if wants_json():
            return jsonify({"ok": False, "error": message}), 500
        return render_template("error.html", code=500, title="Something went wrong", message=message), 500
