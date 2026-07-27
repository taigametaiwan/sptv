#!/usr/bin/env python3
"""SPTV API -> M3U, designed for low request volume.

The implementation intentionally does not probe FLV media and does not treat the
first numeric auth_key component as an expiry timestamp. It fetches the schedule
once, then fetches each player payload sequentially with a delay and jitter.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import random
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

VERSION = "0.1.0"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DATE12_RE = re.compile(r"^20\d{10}$")
PLAYER_ID_RE = re.compile(r"(?:/player/|[?&]id=)(\d{4,})", re.I)
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class Config:
    home_url: str = "https://www.sptv.com/en/"
    schedule_url: str = "https://www.sptv.com/data/zb.json"
    player_api_url: str = "https://www.sptv.com/ajax_zb.php"
    schedule_timezone: str = "Asia/Shanghai"
    past_minutes: int = 150
    future_minutes: int = 180
    max_matches: int = 120
    max_lines_per_match: int = 4
    request_timeout: float = 15.0
    delay_min_seconds: float = 4.0
    delay_max_seconds: float = 5.5
    network_retries: int = 1
    stop_after_denials: int = 2
    language: int = 2
    is_mobile: int = 0
    min_real_streams: int = 1
    include_placeholders: bool = False
    placeholder_url: str = "https://freem3u.xyz/static/no-signal/low.m3u8"
    group_title: str = "SP TV (China)"
    emit_headers: bool = False
    user_agent: str = DEFAULT_UA

    @classmethod
    def from_env(cls) -> "Config":
        defaults = cls()
        return cls(
            home_url=_env("SPTV_HOME_URL", defaults.home_url),
            schedule_url=_env("SPTV_SCHEDULE_URL", defaults.schedule_url),
            player_api_url=_env("SPTV_PLAYER_API_URL", defaults.player_api_url),
            schedule_timezone=_env("SPTV_SCHEDULE_TIMEZONE", defaults.schedule_timezone),
            past_minutes=_env_int("SPTV_PAST_MINUTES", defaults.past_minutes, 0, 1440),
            future_minutes=_env_int("SPTV_FUTURE_MINUTES", defaults.future_minutes, 0, 2880),
            max_matches=_env_int("SPTV_MAX_MATCHES", defaults.max_matches, 1, 500),
            max_lines_per_match=_env_int("SPTV_MAX_LINES_PER_MATCH", defaults.max_lines_per_match, 1, 10),
            request_timeout=_env_float("SPTV_REQUEST_TIMEOUT", defaults.request_timeout, 3.0, 60.0),
            delay_min_seconds=_env_float("SPTV_DELAY_MIN_SECONDS", defaults.delay_min_seconds, 0.0, 60.0),
            delay_max_seconds=_env_float("SPTV_DELAY_MAX_SECONDS", defaults.delay_max_seconds, 0.0, 60.0),
            network_retries=_env_int("SPTV_NETWORK_RETRIES", defaults.network_retries, 0, 3),
            stop_after_denials=_env_int("SPTV_STOP_AFTER_DENIALS", defaults.stop_after_denials, 1, 20),
            language=_env_int("SPTV_LANGUAGE", defaults.language, 1, 3),
            is_mobile=_env_int("SPTV_IS_MOBILE", defaults.is_mobile, 0, 1),
            min_real_streams=_env_int("SPTV_MIN_REAL_STREAMS", defaults.min_real_streams, 0, 500),
            include_placeholders=_env_bool("SPTV_INCLUDE_PLACEHOLDERS", defaults.include_placeholders),
            placeholder_url=_env("SPTV_PLACEHOLDER_URL", defaults.placeholder_url),
            group_title=_env("SPTV_GROUP_TITLE", defaults.group_title),
            emit_headers=_env_bool("SPTV_EMIT_HEADERS", defaults.emit_headers),
            user_agent=_env("SPTV_USER_AGENT", defaults.user_agent),
        ).normalized()

    def normalized(self) -> "Config":
        if self.delay_max_seconds < self.delay_min_seconds:
            self.delay_min_seconds, self.delay_max_seconds = self.delay_max_seconds, self.delay_min_seconds
        return self


@dataclass(slots=True)
class Match:
    player_id: str
    start_at: datetime | None
    league: str
    home: str
    away: str
    raw_fields: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Stream:
    player_id: str
    start_at: datetime | None
    league: str
    home: str
    away: str
    line_number: int
    media_url: str
    signed_at_epoch: int | None
    signed_at_utc: str | None
    player_api_url: str
    player_page_url: str


@dataclass(slots=True)
class HttpAttempt:
    url: str
    status: int
    elapsed: float
    error: str = ""


def log(message: str) -> None:
    print(message, flush=True)


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except ValueError:
        value = default
    return max(low, min(value, high))


def _env_float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)).strip())
    except ValueError:
        value = default
    return max(low, min(value, high))



def load_env_file(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE pairs without overriding existing environment values."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def sanitize_m3u(value: Any) -> str:
    return clean_text(value).replace('"', "'").replace(",", " ")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def csv_fields(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [clean_text(item) for item in raw]
    text = str(raw or "")
    try:
        return [clean_text(item) for item in next(csv.reader([text]))]
    except Exception:
        return [clean_text(item) for item in text.split(",")]


def field_at(fields: list[str], index: int) -> str:
    return clean_text(fields[index]) if 0 <= index < len(fields) else ""


def schedule_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Asia/Shanghai")


def parse_schedule_datetime(value: Any, timezone_name: str = "Asia/Shanghai") -> datetime | None:
    text = clean_text(value)
    if not DATE12_RE.fullmatch(text):
        return None
    try:
        local = datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=schedule_tz(timezone_name))
    except ValueError:
        return None
    return local.astimezone(VN_TZ)


def find_schedule_time(fields: list[str], timezone_name: str) -> datetime | None:
    preferred = parse_schedule_datetime(field_at(fields, 43), timezone_name)
    if preferred:
        return preferred
    for value in reversed(fields):
        parsed = parse_schedule_datetime(value, timezone_name)
        if parsed:
            return parsed
    return None


def parse_match_fields(fields: list[str], timezone_name: str = "Asia/Shanghai") -> Match | None:
    player_id = field_at(fields, 0)
    if not player_id.isdigit():
        fallback = field_at(fields, 34)
        player_id = fallback if fallback.isdigit() else ""
    if not player_id:
        return None
    return Match(
        player_id=player_id,
        start_at=find_schedule_time(fields, timezone_name),
        league=field_at(fields, 7),
        home=field_at(fields, 14),
        away=field_at(fields, 18),
        raw_fields=fields,
    )


def rows_from_schedule(payload: Any, timezone_name: str = "Asia/Shanghai") -> list[Match]:
    raw_rows: list[Any] = []
    if isinstance(payload, list):
        raw_rows = payload
    elif isinstance(payload, dict):
        for key in ("data", "rows", "matches", "items"):
            if isinstance(payload.get(key), list):
                raw_rows = payload[key]
                break
    output: list[Match] = []
    seen: set[str] = set()
    for raw in raw_rows:
        row = parse_match_fields(csv_fields(raw), timezone_name)
        if row and row.player_id not in seen:
            seen.add(row.player_id)
            output.append(row)
    return output


def player_id_from_value(value: str) -> str:
    text = clean_text(value)
    if text.isdigit():
        return text
    match = PLAYER_ID_RE.search(text)
    return match.group(1) if match else ""


def player_page(home_url: str, player_id: str) -> str:
    home = home_url.rstrip("/") + "/"
    parts = urllib.parse.urlsplit(home)
    language = parts.path.strip("/").split("/", 1)[0] or "en"
    if language not in {"en", "cn", "tw"}:
        language = "en"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, f"/{language}/player/{player_id}.html", "", ""))


def player_api_url(base: str, player_id: str, *, language: int = 2, is_mobile: int = 0) -> str:
    params = urllib.parse.urlencode({"act": "player", "isMobile": str(is_mobile), "id": player_id, "lan": str(language)})
    return base + ("&" if "?" in base else "?") + params


def signed_at_from_url(url: str) -> tuple[int | None, str | None]:
    """Read the first auth_key component as a signing/issuance timestamp.

    It is deliberately *not* treated as an expiry timestamp. The uploaded
    reference M3U shows one value generated roughly every five seconds while
    the source walks through matches sequentially.
    """
    try:
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("auth_key") or []
        first = values[0].split("-", 1)[0] if values else ""
        epoch = int(first) if first.isdigit() else None
    except Exception:
        epoch = None
    if epoch is None:
        return None, None
    try:
        iso = datetime.fromtimestamp(epoch, tz=ZoneInfo("UTC")).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return epoch, None
    return epoch, iso


def metadata_from_player_payload(payload: Any, fallback: Match, timezone_name: str) -> Match:
    if not isinstance(payload, dict):
        return fallback
    raw = payload.get("m")
    parsed = parse_match_fields(csv_fields(raw), timezone_name) if isinstance(raw, list) else None
    if not parsed:
        return fallback
    return Match(
        player_id=fallback.player_id or parsed.player_id,
        start_at=fallback.start_at or parsed.start_at,
        league=fallback.league or parsed.league,
        home=fallback.home or parsed.home,
        away=fallback.away or parsed.away,
        raw_fields=fallback.raw_fields or parsed.raw_fields,
    )


def streams_from_player_payload(
    payload: Any,
    *,
    match: Match,
    api_url: str,
    page_url: str,
    max_lines: int,
    timezone_name: str = "Asia/Shanghai",
) -> list[Stream]:
    if not isinstance(payload, dict):
        return []
    try:
        code = int(payload.get("code", -1))
    except (TypeError, ValueError):
        code = -1
    if code != 0:
        return []
    metadata = metadata_from_player_payload(payload, match, timezone_name)
    purl = payload.get("purl")
    if not isinstance(purl, list):
        return []
    output: list[Stream] = []
    seen_paths: set[str] = set()
    for item in purl:
        if not isinstance(item, dict):
            continue
        url = clean_text(item.get("url")).replace("\\/", "/")
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc or not parts.path.lower().endswith(".flv"):
            continue
        stable_path = f"{parts.netloc.lower()}{parts.path.lower()}"
        if stable_path in seen_paths:
            continue
        seen_paths.add(stable_path)
        signed_epoch, signed_iso = signed_at_from_url(url)
        output.append(
            Stream(
                player_id=metadata.player_id,
                start_at=metadata.start_at,
                league=metadata.league,
                home=metadata.home,
                away=metadata.away,
                line_number=len(output) + 1,
                media_url=url,
                signed_at_epoch=signed_epoch,
                signed_at_utc=signed_iso,
                player_api_url=api_url,
                player_page_url=page_url,
            )
        )
        if len(output) >= max_lines:
            break
    return output


class SptvClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Connection": "keep-alive",
            }
        )

    def _get_json(self, url: str, *, referer: str = "") -> tuple[Any, list[HttpAttempt]]:
        attempts: list[HttpAttempt] = []
        headers = {"Accept": "application/json,text/plain,*/*"}
        if referer:
            headers["Referer"] = referer
        for attempt_no in range(self.config.network_retries + 1):
            started = time.monotonic()
            try:
                response = self.session.get(url, headers=headers, timeout=self.config.request_timeout)
                elapsed = round(time.monotonic() - started, 3)
                attempts.append(HttpAttempt(url=str(response.url), status=response.status_code, elapsed=elapsed))
                if response.status_code in {403, 429}:
                    return None, attempts
                response.raise_for_status()
                return response.json(), attempts
            except (requests.RequestException, ValueError) as exc:
                elapsed = round(time.monotonic() - started, 3)
                attempts.append(HttpAttempt(url=url, status=0, elapsed=elapsed, error=f"{type(exc).__name__}: {exc}"))
                if attempt_no < self.config.network_retries:
                    time.sleep(min(3.0, 1.0 + attempt_no))
        return None, attempts

    def warm_session(self) -> HttpAttempt:
        started = time.monotonic()
        try:
            response = self.session.get(
                self.config.home_url,
                headers={"Accept": "text/html,application/xhtml+xml"},
                timeout=self.config.request_timeout,
            )
            return HttpAttempt(str(response.url), response.status_code, round(time.monotonic() - started, 3))
        except requests.RequestException as exc:
            return HttpAttempt(
                self.config.home_url,
                0,
                round(time.monotonic() - started, 3),
                f"{type(exc).__name__}: {exc}",
            )

    def fetch_schedule(self) -> tuple[list[Match], list[HttpAttempt]]:
        payload, attempts = self._get_json(self.config.schedule_url, referer=self.config.home_url)
        return rows_from_schedule(payload, self.config.schedule_timezone), attempts

    def fetch_player(self, match: Match) -> tuple[list[Stream], list[HttpAttempt], dict[str, Any]]:
        page = player_page(self.config.home_url, match.player_id)
        api = player_api_url(
            self.config.player_api_url,
            match.player_id,
            language=self.config.language,
            is_mobile=self.config.is_mobile,
        )
        payload, attempts = self._get_json(api, referer=page)
        streams = streams_from_player_payload(
            payload,
            match=match,
            api_url=api,
            page_url=page,
            max_lines=self.config.max_lines_per_match,
            timezone_name=self.config.schedule_timezone,
        )
        info = {
            "code": payload.get("code") if isinstance(payload, dict) else None,
            "pid": payload.get("pid") if isinstance(payload, dict) else None,
            "title": payload.get("title") if isinstance(payload, dict) else None,
            "purl_count": len(payload.get("purl", [])) if isinstance(payload, dict) and isinstance(payload.get("purl"), list) else 0,
        }
        return streams, attempts, info


def in_window(match: Match, now: datetime, past_minutes: int, future_minutes: int) -> bool:
    if match.start_at is None:
        return False
    delta = match.start_at - now
    return -timedelta(minutes=past_minutes) <= delta <= timedelta(minutes=future_minutes)


def channel_name(stream: Stream) -> str:
    when = stream.start_at.astimezone(VN_TZ).strftime("%H:%M %d/%m") if stream.start_at else "--:-- --/--"
    home = sanitize_m3u(stream.home) or "Đội nhà"
    away = sanitize_m3u(stream.away) or "Đội khách"
    league = sanitize_m3u(stream.league)
    league_text = f" [{league}]" if league else ""
    line_text = f" [Line {stream.line_number}]" if stream.line_number > 1 else ""
    return f"🟢 {when} ⚽ {home} vs {away}{league_text}{line_text} [flv]"


def placeholder_name(match: Match) -> str:
    when = match.start_at.astimezone(VN_TZ).strftime("%H:%M %d/%m") if match.start_at else "--:-- --/--"
    home = sanitize_m3u(match.home) or "Đội nhà"
    away = sanitize_m3u(match.away) or "Đội khách"
    league = sanitize_m3u(match.league)
    league_text = f" [{league}]" if league else ""
    return f"⚪ {when} ⚽ {home} vs {away}{league_text}"


def playlist_text(streams: Iterable[Stream], *, config: Config, placeholder_matches: Iterable[Match] = ()) -> str:
    lines = ["#EXTM3U"]
    for stream in streams:
        lines.append(f'#EXTINF:-1 tvg-logo="" group-title="{sanitize_m3u(config.group_title)}" , {channel_name(stream)}')
        if config.emit_headers:
            lines.append(f"#EXTVLCOPT:http-referrer={stream.player_page_url}")
            lines.append(f"#EXTVLCOPT:http-user-agent={config.user_agent}")
        lines.append(stream.media_url)
    if config.include_placeholders:
        for match in placeholder_matches:
            lines.append(f'#EXTINF:-1 tvg-logo="" group-title="{sanitize_m3u(config.group_title)}" , {placeholder_name(match)}')
            lines.append(config.placeholder_url)
    return "\n".join(lines) + "\n"


def count_real_streams(text: str) -> int:
    count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(("http://", "https://")):
            path = urllib.parse.urlsplit(line).path.lower()
            if path.endswith(".flv"):
                count += 1
    return count


def publish_candidate(output_path: Path, candidate_text: str, *, min_real_streams: int) -> tuple[bool, str]:
    real_count = count_real_streams(candidate_text)
    if real_count >= min_real_streams:
        atomic_write(output_path, candidate_text)
        return True, f"published {real_count} real streams"
    if output_path.exists() and count_real_streams(output_path.read_text(encoding="utf-8", errors="replace")) > 0:
        return False, f"candidate has {real_count}; preserved last-good playlist"
    if min_real_streams == 0:
        atomic_write(output_path, candidate_text)
        return True, "published empty playlist because minimum is zero"
    return False, f"candidate has {real_count}; no last-good playlist exists"


def sleep_between(config: Config, rng: random.Random) -> float:
    delay = rng.uniform(config.delay_min_seconds, config.delay_max_seconds)
    if delay > 0:
        time.sleep(delay)
    return delay


def run(
    *,
    config: Config,
    output_path: Path,
    debug_path: Path,
    exact_ids: list[str] | None = None,
    random_seed: int | None = None,
) -> int:
    started = time.monotonic()
    now = datetime.now(VN_TZ)
    rng = random.Random(random_seed)
    client = SptvClient(config)
    debug: dict[str, Any] = {
        "source": "sptv",
        "version": VERSION,
        "started_at": now.isoformat(timespec="seconds"),
        "configuration": asdict(config),
        "policy": {
            "media_probe": False,
            "player_requests": "sequential",
            "auth_key_first_field": "signed_at_not_expiry",
            "last_good_preserved_on_empty": True,
        },
        "home": {},
        "schedule": {},
        "matches": [],
        "summary": {},
    }

    warm = client.warm_session()
    debug["home"] = asdict(warm)
    log(f"[SPTV] Warm session: HTTP {warm.status} | {warm.elapsed:.2f}s")

    if exact_ids:
        rows = [Match(player_id=value, start_at=None, league="", home="", away="") for value in exact_ids]
        schedule_attempts: list[HttpAttempt] = []
    else:
        rows, schedule_attempts = client.fetch_schedule()
        debug["schedule"]["attempts"] = [asdict(item) for item in schedule_attempts]
        if not rows:
            debug["summary"] = {"status": "SCHEDULE_FAILED", "elapsed_seconds": round(time.monotonic() - started, 2)}
            atomic_write(debug_path, json.dumps(debug, ensure_ascii=False, indent=2) + "\n")
            log("[SPTV] Không lấy được lịch; giữ nguyên playlist cũ.")
            return 2
        rows = [row for row in rows if in_window(row, now, config.past_minutes, config.future_minutes)]

    rows.sort(key=lambda item: (item.start_at or datetime.max.replace(tzinfo=VN_TZ), item.player_id))
    rows = rows[: config.max_matches]
    debug["schedule"].update({"rows_selected": len(rows), "window": f"-{config.past_minutes}/+{config.future_minutes}"})
    log(f"[SPTV] Trận được chọn: {len(rows)}")

    all_streams: list[Stream] = []
    no_stream_matches: list[Match] = []
    denial_streak = 0
    delays: list[float] = []

    for index, match in enumerate(rows, start=1):
        streams, attempts, info = client.fetch_player(match)
        statuses = [attempt.status for attempt in attempts]
        if any(status in {403, 429} for status in statuses):
            denial_streak += 1
        else:
            denial_streak = 0

        all_streams.extend(streams)
        if not streams:
            no_stream_matches.append(match)
        debug["matches"].append(
            {
                "player_id": match.player_id,
                "start_at": match.start_at.isoformat(timespec="seconds") if match.start_at else None,
                "league": match.league,
                "home": match.home,
                "away": match.away,
                "attempts": [asdict(item) for item in attempts],
                "player": info,
                "streams": [
                    {**asdict(stream), "start_at": stream.start_at.isoformat(timespec="seconds") if stream.start_at else None}
                    for stream in streams
                ],
            }
        )
        status_text = "/".join(str(value) for value in statuses if value) or "ERR"
        log(f"[SPTV] {index}/{len(rows)} id={match.player_id} | HTTP {status_text} | streams={len(streams)}")

        if denial_streak >= config.stop_after_denials:
            log(f"[SPTV] Dừng sớm sau {denial_streak} lượt liên tiếp HTTP 403/429 để tránh tăng mức chặn.")
            break
        if index < len(rows):
            delay = sleep_between(config, rng)
            delays.append(round(delay, 3))

    # Stable de-duplication. Different signed query strings for the same FLV path count as one line.
    unique: list[Stream] = []
    seen: set[str] = set()
    for stream in all_streams:
        parts = urllib.parse.urlsplit(stream.media_url)
        stable = f"{parts.netloc.lower()}{parts.path.lower()}"
        if stable not in seen:
            seen.add(stable)
            unique.append(stream)

    unique.sort(key=lambda item: (item.start_at or datetime.max.replace(tzinfo=VN_TZ), item.player_id, item.line_number))
    candidate = playlist_text(unique, config=config, placeholder_matches=no_stream_matches)
    published, publish_reason = publish_candidate(output_path, candidate, min_real_streams=config.min_real_streams)

    signed_values = sorted(stream.signed_at_epoch for stream in unique if stream.signed_at_epoch is not None)
    debug["summary"] = {
        "status": "PUBLISHED" if published else "LAST_GOOD_PRESERVED",
        "matches_selected": len(rows),
        "matches_processed": len(debug["matches"]),
        "real_streams": len(unique),
        "placeholders": len(no_stream_matches) if config.include_placeholders else 0,
        "request_delays_seconds": delays,
        "signed_at_min_epoch": signed_values[0] if signed_values else None,
        "signed_at_max_epoch": signed_values[-1] if signed_values else None,
        "signed_at_span_seconds": signed_values[-1] - signed_values[0] if len(signed_values) >= 2 else 0,
        "published": published,
        "publish_reason": publish_reason,
        "output": str(output_path),
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    atomic_write(debug_path, json.dumps(debug, ensure_ascii=False, indent=2) + "\n")
    log(f"[SPTV] {publish_reason}")
    log(f"[SPTV] Debug: {debug_path}")
    return 0 if published or "preserved last-good" in publish_reason else 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lấy playlist SPTV qua API với nhịp gọi thấp, tuần tự.")
    parser.add_argument("--output", default="sptv.m3u", help="Đường dẫn M3U đầu ra.")
    parser.add_argument("--debug", default="debug/sptv_debug.json", help="Đường dẫn JSON chẩn đoán.")
    parser.add_argument("--player-id", action="append", default=[], help="Chỉ lấy một player ID; có thể lặp lại.")
    parser.add_argument("--seed", type=int, default=None, help="Seed jitter phục vụ kiểm thử.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_file()
    config = Config.from_env()
    exact_ids = [player_id_from_value(value) for value in args.player_id]
    exact_ids = [value for value in exact_ids if value]
    return run(
        config=config,
        output_path=Path(args.output).resolve(),
        debug_path=Path(args.debug).resolve(),
        exact_ids=exact_ids or None,
        random_seed=args.seed,
    )


if __name__ == "__main__":
    raise SystemExit(main())
