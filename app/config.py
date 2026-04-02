from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv_if_present() -> None:
    root = Path(__file__).resolve().parent.parent
    for base in (root, Path.cwd()):
        path = base / ".env"
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val
        break


@dataclass(frozen=True)
class Settings:
    zone_id: str
    api_token: str
    sqlite_path: Path
    http_host: str
    http_port: int
    ingest_hour_utc: int
    ingest_minute_utc: int
    user_agent_like: str
    ingest_on_startup: bool
    graphql_limit_per_chunk: int
    graphql_pause_sec: float
    backfill_lookback_calendar_days: int
    ua_googlebot_image: str
    ua_googlebot_video: str
    ua_googlebot_news: str


def get_settings() -> Settings:
    _load_dotenv_if_present()
    zone = (os.environ.get("CLOUDFLARE_ZONE_ID") or os.environ.get("CF_ZONE_ID") or "").strip()
    token = (os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get("CF_API_TOKEN") or "").strip()
    sqlite_s = (os.environ.get("SQLITE_PATH") or "./data/cf_googlebot.db").strip()
    host = (os.environ.get("HTTP_HOST") or "0.0.0.0").strip()
    port = int(os.environ.get("HTTP_PORT") or "8080")
    h_utc = int(os.environ.get("INGEST_HOUR_UTC") or "3")
    m_utc = int(os.environ.get("INGEST_MINUTE_UTC") or "0")
    ua = (os.environ.get("USER_AGENT_LIKE") or "%Googlebot%").strip() or "%Googlebot%"
    on_start = (os.environ.get("INGEST_ON_STARTUP") or "").lower() in ("1", "true", "yes")
    lim = int(os.environ.get("GRAPHQL_LIMIT_PER_CHUNK") or "10000")
    pause = float(os.environ.get("GRAPHQL_PAUSE_SEC") or "0.35")
    backfill_days = int(os.environ.get("BACKFILL_LOOKBACK_DAYS") or "8")
    backfill_days = max(1, min(14, backfill_days))
    ua_img = (os.environ.get("UA_GOOGLEBOT_IMAGE") or "%Googlebot-Image%").strip() or "%Googlebot-Image%"
    ua_vid = (os.environ.get("UA_GOOGLEBOT_VIDEO") or "%Googlebot-Video%").strip() or "%Googlebot-Video%"
    ua_news = (os.environ.get("UA_GOOGLEBOT_NEWS") or "%Googlebot-News%").strip() or "%Googlebot-News%"
    return Settings(
        zone_id=zone,
        api_token=token,
        sqlite_path=Path(sqlite_s).expanduser().resolve(),
        http_host=host,
        http_port=port,
        ingest_hour_utc=h_utc,
        ingest_minute_utc=m_utc,
        user_agent_like=ua,
        ingest_on_startup=on_start,
        graphql_limit_per_chunk=max(100, min(10000, lim)),
        graphql_pause_sec=max(0.0, pause),
        backfill_lookback_calendar_days=backfill_days,
        ua_googlebot_image=ua_img,
        ua_googlebot_video=ua_vid,
        ua_googlebot_news=ua_news,
    )
