"""
Client GraphQL Cloudflare — httpRequestsAdaptiveGroups con filtri DATA_MODEL (doppia query).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"

CHUNK_DAYS = 7
LOOKBACK_MAX_AGE = timedelta(days=8) - timedelta(minutes=45)

# Passata A: senza query string | Passata B: con query string (vedi docs/DATA_MODEL.md §5)
QUERY_EMPTY_QS = """query ($zoneTag: string!, $since: string!, $until: string!, $ua: string!, $lim: int!) {
  viewer {
    zones(filter: {zoneTag: $zoneTag}) {
      groups: httpRequestsAdaptiveGroups(
        limit: $lim
        orderBy: [count_DESC]
        filter: { datetime_geq: $since, datetime_lt: $until, userAgent_like: $ua, clientRequestQuery: "" }
      ) {
        count
        dimensions { datetimeHour edgeResponseStatus }
      }
    }
  }
}"""

QUERY_NONEMPTY_QS = """query ($zoneTag: string!, $since: string!, $until: string!, $ua: string!, $lim: int!) {
  viewer {
    zones(filter: {zoneTag: $zoneTag}) {
      groups: httpRequestsAdaptiveGroups(
        limit: $lim
        orderBy: [count_DESC]
        filter: { datetime_geq: $since, datetime_lt: $until, userAgent_like: $ua, clientRequestQuery_like: "%_%" }
      ) {
        count
        dimensions { datetimeHour edgeResponseStatus }
      }
    }
  }
}"""


def graphql_post(token: str, query: str, variables: dict, timeout: int = 120) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = Request(
        GRAPHQL_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            return json.loads(raw) if raw else {"errors": [{"message": raw}]}
        except json.JSONDecodeError:
            return {"errors": [{"message": raw}]}


def _fetch_merged_groups_inner(
    zone_id: str,
    token: str,
    since_dt: datetime,
    until_exclusive_dt: datetime,
    pattern: str,
    limit_per_chunk: int,
    query_document: str,
    pause_sec: float,
) -> tuple[list[dict], int, bool]:
    if until_exclusive_dt <= since_dt:
        return [], 0, False

    now = datetime.now(timezone.utc)
    since_utc = since_dt.astimezone(timezone.utc) if since_dt.tzinfo else since_dt.replace(tzinfo=timezone.utc)
    age = now - since_utc
    if age > LOOKBACK_MAX_AGE:
        approx_first = (now - LOOKBACK_MAX_AGE).strftime("%Y-%m-%d %H:%MZ")
        raise ValueError(
            "LOOKBACK: dati troppo vecchi per httpRequestsAdaptiveGroups (limite Cloudflare ~1 settimana + 1 giorno). "
            f"Inizio richiesto troppo indietro (~{age.days}d). Orientativo non prima di {approx_first} UTC."
        )

    zone_id = zone_id.strip()
    all_groups: list[dict] = []
    truncated_any = False
    chunk_start = since_dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    end_bound = until_exclusive_dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    chunk_idx = 0

    while chunk_start < end_bound:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end_bound)
        variables = {
            "zoneTag": zone_id,
            "since": chunk_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "until": chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ua": pattern,
            "lim": limit_per_chunk,
        }
        data = graphql_post(token, query_document, variables)
        if data.get("errors"):
            raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False))

        zones = (((data.get("data") or {}).get("viewer") or {}).get("zones")) or []
        if not zones:
            raise RuntimeError("Nessuna zona nella risposta GraphQL")
        groups = zones[0].get("groups") or []
        all_groups.extend(groups)
        if len(groups) >= limit_per_chunk:
            truncated_any = True

        chunk_idx += 1
        chunk_start = chunk_end
        if chunk_start < end_bound and pause_sec > 0:
            time.sleep(pause_sec)

    return all_groups, chunk_idx, truncated_any


def fetch_groups_no_query_string(
    zone_id: str,
    token: str,
    since_dt: datetime,
    until_exclusive_dt: datetime,
    pattern: str,
    limit_per_chunk: int,
    pause_sec: float,
) -> tuple[list[dict], int, bool]:
    """has_query_string = 0 lato salvataggio."""
    return _fetch_merged_groups_inner(
        zone_id,
        token,
        since_dt,
        until_exclusive_dt,
        pattern,
        limit_per_chunk,
        QUERY_EMPTY_QS,
        pause_sec,
    )


def fetch_groups_with_query_string(
    zone_id: str,
    token: str,
    since_dt: datetime,
    until_exclusive_dt: datetime,
    pattern: str,
    limit_per_chunk: int,
    pause_sec: float,
) -> tuple[list[dict], int, bool]:
    """has_query_string = 1 lato salvataggio."""
    return _fetch_merged_groups_inner(
        zone_id,
        token,
        since_dt,
        until_exclusive_dt,
        pattern,
        limit_per_chunk,
        QUERY_NONEMPTY_QS,
        pause_sec,
    )


def day_key_from_datetime_hour(iso_hour: str) -> str:
    if not iso_hour or len(iso_hour) < 10:
        return "unknown"
    return iso_hour[:10]


def aggregate_groups_to_daily_status(
    groups: list[dict],
    snapshot_date_utc: str,
    _has_query_string: int,
) -> dict[int, int]:
    """Somma hits per edge_response_status per il giorno snapshot (filtra righe che non sono quel giorno UTC)."""
    out: dict[int, int] = {}
    for row in groups:
        dims = row.get("dimensions") or {}
        hour = dims.get("datetimeHour") or ""
        day = day_key_from_datetime_hour(hour)
        if day != snapshot_date_utc:
            continue
        st = dims.get("edgeResponseStatus")
        try:
            code = int(st) if st is not None else -1
        except (TypeError, ValueError):
            code = -1
        if code < 0:
            continue
        cnt = int(row.get("count") or 0)
        out[code] = out.get(code, 0) + cnt
    return out
