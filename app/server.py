from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify, render_template, request

from app.config import get_settings
from app.db import connect, migrate, query_all
from app.ingest import ingest_snapshot_date, lookback_snapshot_dates_utc, yesterday_utc_string

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cf_archiver")

app = Flask(__name__, template_folder="templates")
_scheduler: BackgroundScheduler | None = None
_db_lock = threading.Lock()
_migrate_lock = threading.Lock()
_migrated_sqlite_path: str | None = None
_backfill_lock = threading.Lock()
_backfill_in_progress = False


def get_conn():
    global _migrated_sqlite_path
    settings = get_settings()
    conn = connect(settings.sqlite_path)
    path_key = str(settings.sqlite_path)
    with _migrate_lock:
        if _migrated_sqlite_path != path_key:
            migrate(conn)
            _migrated_sqlite_path = path_key
    return conn, settings


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/last-run")
def api_last_run():
    with _db_lock:
        conn, _ = get_conn()
        row = conn.execute(
            """
            SELECT id, started_at, finished_at, status, target_date_utc, rows_written, error_message, duration_ms
            FROM ingestion_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return jsonify({"ok": True, "last_run": None})
    return jsonify(
        {
            "ok": True,
            "last_run": {
                "id": row["id"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "status": row["status"],
                "target_date_utc": row["target_date_utc"],
                "rows_written": row["rows_written"],
                "error_message": row["error_message"],
                "duration_ms": row["duration_ms"],
            },
        }
    )


@app.route("/partials/last-run")
def partial_last_run():
    with _db_lock:
        conn, _ = get_conn()
        row = conn.execute(
            """
            SELECT finished_at, status, target_date_utc, rows_written, error_message, duration_ms
            FROM ingestion_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return render_template("partials/last_run.html", row=row)


def _parse_date(s: str) -> datetime:
    s = (s or "").strip()
    if len(s) != 10:
        raise ValueError("Usa YYYY-MM-DD")
    return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)


@app.route("/api/facts")
def api_facts():
    start_s = request.args.get("start", "").strip()
    end_s = request.args.get("end", "").strip()
    if not start_s or not end_s:
        return jsonify({"ok": False, "error": "Parametri start e end (YYYY-MM-DD) obbligatori"}), 400
    try:
        start_dt = _parse_date(start_s)
        end_dt = _parse_date(end_s)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if end_dt < start_dt:
        return jsonify({"ok": False, "error": "end deve essere >= start"}), 400

    with _db_lock:
        conn, _ = get_conn()
        rows = query_all(
            conn,
            """
            SELECT snapshot_date_utc, ua_kind, has_query_string, edge_response_status, hits
            FROM fact_googlebot_daily_query_status
            WHERE snapshot_date_utc >= ? AND snapshot_date_utc <= ?
            ORDER BY snapshot_date_utc, ua_kind, has_query_string, edge_response_status
            """,
            (start_s, end_s),
        )

    facts = [
        {
            "d": r["snapshot_date_utc"],
            "uk": (r["ua_kind"] or "googlebot").strip(),
            "b": int(r["has_query_string"]),
            "s": int(r["edge_response_status"]),
            "h": int(r["hits"]),
        }
        for r in rows
    ]

    return jsonify(
        {
            "ok": True,
            "start": start_s,
            "end": end_s,
            "facts": facts,
            "rows": len(rows),
        }
    )


@app.route("/api/trigger-ingest", methods=["POST"])
def api_trigger_ingest():
    settings = get_settings()
    if not settings.zone_id or not settings.api_token:
        return jsonify({"ok": False, "error": "Configura CLOUDFLARE_ZONE_ID e CLOUDFLARE_API_TOKEN"}), 400
    body = request.get_json(silent=True) or {}
    date_s = (request.args.get("date") or body.get("date") or "").strip()
    if not date_s:
        date_s = yesterday_utc_string()
    try:
        _parse_date(date_s)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    def job():
        with _db_lock:
            conn, s = get_conn()
            ingest_snapshot_date(conn, s, date_s)

    t = threading.Thread(target=job, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Ingest avviato in background", "target_date_utc": date_s})


@app.route("/api/trigger-backfill", methods=["POST"])
def api_trigger_backfill():
    settings = get_settings()
    if not settings.zone_id or not settings.api_token:
        return jsonify({"ok": False, "error": "Configura CLOUDFLARE_ZONE_ID e CLOUDFLARE_API_TOKEN"}), 400

    body = request.get_json(silent=True) or {}
    raw_days = body.get("days")
    if raw_days is not None:
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "days deve essere un intero"}), 400
        days = max(1, min(14, days))
    else:
        days = settings.backfill_lookback_calendar_days

    dates = lookback_snapshot_dates_utc(calendar_days=days)

    global _backfill_in_progress
    with _backfill_lock:
        if _backfill_in_progress:
            return jsonify({"ok": False, "error": "Un backfill è già in corso"}), 409
        _backfill_in_progress = True

    def job():
        global _backfill_in_progress
        import time

        try:
            for idx, d in enumerate(dates):
                log.info("backfill [%s/%s] %s", idx + 1, len(dates), d)
                with _db_lock:
                    conn, s = get_conn()
                    out = ingest_snapshot_date(conn, s, d)
                if not out.get("ok"):
                    log.warning("backfill giorno %s fallito: %s", d, out.get("error"))
                if idx < len(dates) - 1:
                    time.sleep(0.25)
            log.info("backfill completato (%s giorni)", len(dates))
        finally:
            with _backfill_lock:
                _backfill_in_progress = False

    threading.Thread(target=job, daemon=True).start()
    return jsonify(
        {
            "ok": True,
            "message": f"Backfill avviato in background ({len(dates)} giorni UTC, più vecchio → ieri).",
            "dates": dates,
            "day_count": len(dates),
        }
    )


@app.route("/")
def index():
    settings = get_settings()
    return render_template(
        "index.html",
        configured=bool(settings.zone_id and settings.api_token),
        zone_tail=(settings.zone_id[-6:] if len(settings.zone_id) >= 6 else ""),
        backfill_days=settings.backfill_lookback_calendar_days,
    )


def _scheduled_ingest():
    settings = get_settings()
    if not settings.zone_id or not settings.api_token:
        log.warning("ingest schedulato saltato: mancano ZONE_ID o TOKEN")
        return
    target = yesterday_utc_string()
    log.info("ingest schedulato: target=%s", target)
    with _db_lock:
        conn, s = get_conn()
        out = ingest_snapshot_date(conn, s, target)
    if not out.get("ok"):
        log.error("ingest fallito: %s", out.get("error"))


def _maybe_ingest_on_startup():
    settings = get_settings()
    if not settings.ingest_on_startup:
        return
    if not settings.zone_id or not settings.api_token:
        return

    def delayed():
        import time

        time.sleep(5)
        _scheduled_ingest()

    threading.Thread(target=delayed, daemon=True).start()


def create_app():
    return app


def main():
    settings = get_settings()
    with _db_lock:
        conn, _ = get_conn()
        conn.close()
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _scheduled_ingest,
        CronTrigger(hour=settings.ingest_hour_utc, minute=settings.ingest_minute_utc),
        id="daily_ingest",
        replace_existing=True,
    )
    _scheduler.start()
    log.info(
        "Scheduler UTC: ogni giorno alle %02d:%02d",
        settings.ingest_hour_utc,
        settings.ingest_minute_utc,
    )
    _maybe_ingest_on_startup()

    try:
        from waitress import serve

        log.info("HTTP su http://%s:%s", settings.http_host, settings.http_port)
        serve(app, host=settings.http_host, port=settings.http_port, threads=4)
    except KeyboardInterrupt:
        pass
    finally:
        if _scheduler:
            _scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
