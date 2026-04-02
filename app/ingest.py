"""
Job di ingest per un giorno civile UTC (DATA_MODEL v1.1): partizione UA + query string, scrittura SQLite.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.cloudflare_client import (
    aggregate_groups_to_daily_status,
    fetch_groups_no_query_string,
    fetch_groups_with_query_string,
)
from app.config import Settings

log = logging.getLogger(__name__)

UA_GOOGLEBOT = "googlebot"
UA_IMAGE = "googlebot_image"
UA_OTHER = "googlebot_other"


def utc_day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _merge_status_counts(*maps: dict[int, int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for m in maps:
        for k, v in m.items():
            out[k] = out.get(k, 0) + v
    return out


def _subtract_status_counts(base: dict[int, int], *subs: dict[int, int]) -> dict[int, int]:
    keys: set[int] = set(base.keys())
    for s in subs:
        keys |= set(s.keys())
    out: dict[int, int] = {}
    for k in keys:
        v = base.get(k, 0) - sum(s.get(k, 0) for s in subs)
        if v > 0:
            out[k] = v
    return out


def ingest_snapshot_date(
    conn: Any,
    settings: Settings,
    snapshot_date_utc: str,
    max_retries: int = 3,
) -> dict[str, Any]:
    """
    Idempotenza: elimina righe del fatto per snapshot_date_utc, poi reinserisce con nuovo source_run_id.

    Per ogni bucket has_query_string: 4 fetch (broad, image, video, news);
    googlebot_other = video + news per status; googlebot = broad − image − other (solo valori > 0).
    """
    t0 = time.perf_counter()
    started_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ingestion_runs (started_at, status, target_date_utc, rows_written)
        VALUES (?, 'running', ?, 0)
        """,
        (started_iso, snapshot_date_utc),
    )
    run_id = cur.lastrowid
    conn.commit()

    result: dict[str, Any] = {
        "run_id": run_id,
        "target_date_utc": snapshot_date_utc,
        "ok": False,
        "rows_written": 0,
        "truncated": False,
        "error": None,
    }

    try:
        y, m, d = (int(snapshot_date_utc[0:4]), int(snapshot_date_utc[5:7]), int(snapshot_date_utc[8:10]))
        day = date(y, m, d)
    except (ValueError, IndexError):
        msg = f"Data non valida: {snapshot_date_utc}"
        _finish_run(conn, run_id, False, 0, msg, t0)
        result["error"] = msg
        return result

    since_dt, until_dt = utc_day_bounds(day)
    zone = settings.zone_id
    token = settings.api_token
    lim = settings.graphql_limit_per_chunk
    pause = settings.graphql_pause_sec
    ua_broad = settings.user_agent_like
    ua_image = settings.ua_googlebot_image
    ua_video = settings.ua_googlebot_video
    ua_news = settings.ua_googlebot_news

    def fetch_one(
        has_qs: int,
        pattern: str,
    ) -> tuple[dict[int, int], int, bool]:
        if has_qs == 0:
            g, ch, tr = fetch_groups_no_query_string(
                zone, token, since_dt, until_dt, pattern, lim, pause
            )
        else:
            g, ch, tr = fetch_groups_with_query_string(
                zone, token, since_dt, until_dt, pattern, lim, pause
            )
        agg = aggregate_groups_to_daily_status(g, snapshot_date_utc, has_qs)
        return agg, ch, tr

    last_err: str | None = None
    chunks_total = 0
    trunc_any = False
    aggs: dict[int, dict[str, dict[int, int]]] = {
        0: {UA_GOOGLEBOT: {}, UA_IMAGE: {}, UA_OTHER: {}},
        1: {UA_GOOGLEBOT: {}, UA_IMAGE: {}, UA_OTHER: {}},
    }

    for attempt in range(max_retries):
        try:
            chunks_total = 0
            trunc_any = False
            for has_qs in (0, 1):
                b, cb, tb = fetch_one(has_qs, ua_broad)
                i, ci, ti = fetch_one(has_qs, ua_image)
                v, cv, tv = fetch_one(has_qs, ua_video)
                n, cn, tn = fetch_one(has_qs, ua_news)
                chunks_total += cb + ci + cv + cn
                trunc_any = trunc_any or tb or ti or tv or tn
                other = _merge_status_counts(v, n)
                core = _subtract_status_counts(b, i, other)
                aggs[has_qs][UA_GOOGLEBOT] = core
                aggs[has_qs][UA_IMAGE] = i
                aggs[has_qs][UA_OTHER] = other
            last_err = None
            break
        except (ValueError, RuntimeError, OSError) as e:
            last_err = str(e)
            log.warning("ingest attempt %s failed: %s", attempt + 1, last_err)
            time.sleep(2.0 * (attempt + 1))

    if last_err is not None:
        _finish_run(conn, run_id, False, 0, last_err, t0)
        result["error"] = last_err
        return result

    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM fact_googlebot_daily_query_status WHERE snapshot_date_utc = ?",
            (snapshot_date_utc,),
        )
        rows = 0
        for has_qs in (0, 1):
            for ua_kind, agg in aggs[has_qs].items():
                for status_code, hits in sorted(agg.items()):
                    if hits <= 0:
                        continue
                    conn.execute(
                        """
                        INSERT INTO fact_googlebot_daily_query_status
                          (snapshot_date_utc, ua_kind, has_query_string, edge_response_status, hits, ingested_at, source_run_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (snapshot_date_utc, ua_kind, has_qs, status_code, hits, ingested_at, run_id),
                    )
                    rows += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        msg = f"DB: {e}"
        _finish_run(conn, run_id, False, 0, msg, t0)
        result["error"] = msg
        return result

    _finish_run(conn, run_id, True, rows, None, t0)
    log.info(
        "ingest ok run_id=%s date=%s rows=%s chunks=%s truncated=%s",
        run_id,
        snapshot_date_utc,
        rows,
        chunks_total,
        trunc_any,
    )
    result["ok"] = True
    result["rows_written"] = rows
    result["truncated"] = trunc_any
    return result


def _finish_run(conn: Any, run_id: int, ok: bool, rows: int, err: str | None, t0: float) -> None:
    finished = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ms = int((time.perf_counter() - t0) * 1000)
    status = "success" if ok else "failed"
    conn.execute(
        """
        UPDATE ingestion_runs
        SET finished_at = ?, status = ?, rows_written = ?, error_message = ?, duration_ms = ?
        WHERE id = ?
        """,
        (finished, status, rows, err, ms, run_id),
    )
    conn.commit()


def yesterday_utc_string(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    y = (now.date() - timedelta(days=1))
    return y.strftime("%Y-%m-%d")


def lookback_snapshot_dates_utc(
    now: datetime | None = None,
    calendar_days: int = 8,
) -> list[str]:
    """
    Giorni civili UTC da (oggi − calendar_days) a ieri incluso.
    Default 8 = tipica finestra «7+1» entro cui le API Analytics restituiscono ancora dati.
    """
    now = now or datetime.now(timezone.utc)
    today = now.date()
    n = max(1, min(14, calendar_days))
    out: list[str] = []
    for i in range(n, 0, -1):
        d = today - timedelta(days=i)
        out.append(d.strftime("%Y-%m-%d"))
    return out
