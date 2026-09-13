"""Bulk import: upload or paste -> preview & map -> confirm -> report."""
import io

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, send_file, url_for

from ..app_factory import get_service
from ..services import import_service as imp

bp = Blueprint("imports", __name__)

PREVIEW_ROW_LIMIT = 500


def _import_dir():
    return current_app.config["APP_CONFIG"].IMPORT_DIR


@bp.get("/import")
def start():
    g.active_nav = "add"
    return render_template("imports/start.html", fields=imp.IMPORT_FIELDS, max_rows=imp.MAX_ROWS)


@bp.post("/import")
def upload():
    g.active_nav = "add"
    upload_file = request.files.get("file")
    pasted = request.form.get("pasted", "")
    try:
        if upload_file and upload_file.filename:
            table = imp.read_upload(upload_file.filename, upload_file.read())
        elif pasted.strip():
            table = imp.read_delimited_text(pasted, "pasted data")
        else:
            raise imp.ImportFileError("Choose a CSV or Excel file, or paste rows copied from a spreadsheet.")
    except imp.ImportFileError as exc:
        flash(str(exc), "bad")
        return render_template("imports/start.html", fields=imp.IMPORT_FIELDS, max_rows=imp.MAX_ROWS, pasted=pasted), 400
    token = imp.save_session(_import_dir(), table)
    return redirect(url_for(".preview", token=token))


@bp.route("/import/<token>", methods=["GET", "POST"])
def preview(token):
    g.active_nav = "add"
    table = imp.load_session(_import_dir(), token)
    if table is None:
        flash("This import preview has expired or was already imported. Upload the file again.", "warn")
        return redirect(url_for(".start"))
    service = get_service()
    if request.method == "POST":
        mapping = imp.mapping_from_form(request.form, table.headers)
        policy = request.form.get("policy", "skip")
    else:
        mapping = imp.auto_map(table.headers)
        policy = "skip"
    result = imp.build_preview(table, mapping, service.repo, policy)

    if request.method == "POST" and request.form.get("step") == "confirm":
        if result.mapping_errors:
            flash(result.mapping_errors[0], "bad")
        elif not (result.count("import") or result.count("update")):
            flash("There are no valid rows to import. Fix the file or the column mapping first.", "bad")
        else:
            report = imp.commit_preview(result, service)
            imp.delete_session(_import_dir(), token)
            g.active_nav = "add"
            return render_template("imports/result.html", report=report, source_name=table.source_name)

    return render_template("imports/preview.html", token=token, table=table, preview=result, mapping=mapping,
                           fields=imp.IMPORT_FIELDS, policies=imp.DUPLICATE_POLICIES, row_limit=PREVIEW_ROW_LIMIT)


@bp.get("/import/template.csv")
def template_csv():
    return send_file(io.BytesIO(imp.template_csv()), mimetype="text/csv", as_attachment=True,
                     download_name="opportunity-finder-import-template.csv")


@bp.get("/import/template.xlsx")
def template_xlsx():
    return send_file(io.BytesIO(imp.template_xlsx()), as_attachment=True,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     download_name="opportunity-finder-import-template.xlsx")
