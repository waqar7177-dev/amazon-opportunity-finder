from flask import Blueprint, current_app, flash, g, redirect, render_template, request, send_file, url_for

from ..app_factory import get_service
from ..domain.settings import SETTING_GROUPS, validate_settings
from ..fees.engine import load_fee_table
from ..providers import provider_statuses
from ..services.backup import create_backup, restore_backup
from ..services.qualification import describe_rules
from ..services.risk_engine import risk_model_description

bp = Blueprint("settings", __name__)


def _page(values, errors, status=200):
    g.active_nav = "settings"
    service = get_service()
    config = current_app.config["APP_CONFIG"]
    return render_template(
        "settings.html", groups=SETTING_GROUPS, values=values, errors=errors, fee_table=load_fee_table(),
        providers=provider_statuses(config), risk_model=risk_model_description(), rules=describe_rules(service.settings),
        db_path=config.DATABASE_PATH, data_dir=config.DATA_DIR, updated_at=service.settings_repo.updated_at(),
        product_count=service.repo.count(include_archived=True),
    ), status


def _display(values: dict) -> dict:
    out = {}
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, float):
            out[name] = value
        else:
            out[name] = str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
    return out


@bp.get("/settings")
def index():
    return _page(_display(get_service().settings.to_dict()), {})


@bp.post("/settings")
def save():
    settings, errors = validate_settings(request.form)
    if errors:
        flash("Some settings need fixing — nothing was saved yet.", "bad")
        submitted = {name: request.form.get(name, "") for group in SETTING_GROUPS for name in (f["name"] for f in group["fields"])}
        for group in SETTING_GROUPS:
            for spec in group["fields"]:
                if spec["kind"] == "bool":
                    submitted[spec["name"]] = bool(request.form.get(spec["name"]))
        return _page(submitted, errors, 422)
    changed = get_service().save_settings(settings)
    flash(f"Settings saved. {changed} product{'s' if changed != 1 else ''} re-evaluated with the new rules.", "ok")
    return redirect(url_for(".index"))


@bp.post("/settings/reset")
def reset():
    changed = get_service().reset_settings()
    flash(f"Settings reset to the defaults. {changed} product{'s' if changed != 1 else ''} re-evaluated.", "ok")
    return redirect(url_for(".index"))


@bp.post("/settings/backup")
def backup():
    config = current_app.config["APP_CONFIG"]
    path = create_backup(config.DATABASE_PATH, config.BACKUP_DIR)
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="application/octet-stream")


@bp.post("/settings/restore")
def restore():
    config = current_app.config["APP_CONFIG"]
    upload = request.files.get("backup")
    if request.form.get("confirm") != "yes":
        flash("Tick the confirmation box to restore — restoring replaces all current data.", "warn")
        return redirect(url_for(".index") + "#backup")
    if not upload or not upload.filename:
        flash("Choose a backup file (.db) to restore.", "warn")
        return redirect(url_for(".index") + "#backup")
    ok, message, safety = restore_backup(upload.read(), config.DATABASE_PATH, config.BACKUP_DIR)
    if ok:
        flash(f"{message} A copy of your previous data was saved as {safety.name if safety else 'a backup'}.", "ok")
    else:
        flash(message, "bad")
    return redirect(url_for(".index") + "#backup")
