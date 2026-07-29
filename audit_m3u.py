#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

AUTH_RE = re.compile(r"[?&]auth_key=(\d+)-")
MIN_AUTH_EPOCH = 946684800  # 2000-01-01 UTC
MAX_AUTH_EPOCH = 4102444800  # 2100-01-01 UTC


def parse(path: Path, *, now_epoch: int | None = None) -> dict[str, object]:
    current = int(time.time()) if now_epoch is None else int(now_epoch)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    raw_lines = text.splitlines()

    first_nonempty = next((line.strip() for line in raw_lines if line.strip()), "")
    header_valid = first_nonempty == "#EXTM3U"
    header_count = sum(1 for line in raw_lines if line.strip() == "#EXTM3U")

    extinf_count = 0
    entries = 0
    real_flv = 0
    placeholders = 0
    malformed = 0
    orphan_urls = 0
    orphan_extinf = 0
    duplicate_headers = max(0, header_count - 1)
    groups: dict[str, int] = {}
    group_real_flv: dict[str, int] = {}
    group_other: dict[str, int] = {}
    expiries: list[int] = []
    remaining: list[int] = []
    missing_expiry = 0
    stable_paths: list[str] = []
    pending_group: str | None = None

    if not header_valid:
        malformed += 1
    malformed += duplicate_headers

    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue
        if line == "#EXTM3U":
            continue
        if line.startswith("#EXTINF"):
            extinf_count += 1
            if pending_group is not None:
                orphan_extinf += 1
                malformed += 1
            match = re.search(r'group-title="([^"]*)"', line)
            pending_group = match.group(1) if match else ""
            continue
        if line.startswith("#"):
            # Entry directives such as EXTVLCOPT are allowed after EXTINF.
            # Global comments/directives are also allowed outside an entry.
            continue
        if line.startswith(("http://", "https://")):
            if pending_group is None:
                orphan_urls += 1
                malformed += 1
                continue

            entries += 1
            group = pending_group
            groups[group] = groups.get(group, 0) + 1
            pending_group = None

            parts = urllib.parse.urlsplit(line)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                malformed += 1
                continue
            if parts.path.lower().endswith(".flv"):
                real_flv += 1
                group_real_flv[group] = group_real_flv.get(group, 0) + 1
                stable_paths.append(f"{parts.netloc.lower()}{parts.path.lower()}")
                match = AUTH_RE.search(line)
                if match:
                    value = int(match.group(1))
                    if MIN_AUTH_EPOCH <= value <= MAX_AUTH_EPOCH:
                        expiries.append(value)
                        remaining.append(value - current)
                    else:
                        missing_expiry += 1
                else:
                    missing_expiry += 1
            else:
                placeholders += 1
                group_other[group] = group_other.get(group, 0) + 1
            continue

        malformed += 1
        if pending_group is not None:
            orphan_extinf += 1
            pending_group = None

    if pending_group is not None:
        orphan_extinf += 1
        malformed += 1

    duplicates = len(stable_paths) - len(set(stable_paths))
    gaps = [b - a for a, b in zip(sorted(expiries), sorted(expiries)[1:])]
    utc = ZoneInfo("UTC")
    return {
        "header_valid": header_valid,
        "header_count": header_count,
        "duplicate_headers": duplicate_headers,
        "extinf_count": extinf_count,
        "entries": entries,
        "orphan_urls": orphan_urls,
        "orphan_extinf": orphan_extinf,
        "real_flv": real_flv,
        "placeholders_or_other": placeholders,
        "malformed": malformed,
        "duplicate_stable_paths": duplicates,
        "groups": groups,
        "group_real_flv": group_real_flv,
        "group_other": group_other,
        "expiry_count": len(expiries),
        "missing_expiry": missing_expiry,
        "expiry_min_epoch": min(expiries) if expiries else None,
        "expiry_max_epoch": max(expiries) if expiries else None,
        "expiry_min_utc": datetime.fromtimestamp(min(expiries), utc).isoformat(timespec="seconds") if expiries else None,
        "expiry_max_utc": datetime.fromtimestamp(max(expiries), utc).isoformat(timespec="seconds") if expiries else None,
        "expiry_span_seconds": max(expiries) - min(expiries) if len(expiries) >= 2 else 0,
        "remaining_ttl_min_seconds": min(remaining) if remaining else None,
        "remaining_ttl_max_seconds": max(remaining) if remaining else None,
        "expired_count": sum(1 for value in remaining if value <= 0),
        "gap_min_seconds": min(gaps) if gaps else None,
        "gap_max_seconds": max(gaps) if gaps else None,
        "gap_mean_seconds": round(statistics.mean(gaps), 3) if gaps else None,
        "gap_median_seconds": statistics.median(gaps) if gaps else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit cấu trúc và thời hạn key M3U SPTV, không gọi mạng.")
    parser.add_argument("path", nargs="?", default="sptv.m3u")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-empty", action="store_true", help="Cho phép playlist chưa có FLV ở giờ yên.")
    parser.add_argument(
        "--min-remaining-seconds",
        type=int,
        default=0,
        help="Trong strict mode, mọi FLV phải còn ít nhất số giây này.",
    )
    args = parser.parse_args()
    path = Path(args.path)
    if not path.exists():
        print(f"ERROR: không tồn tại {path}", file=sys.stderr)
        return 2
    report = parse(path)
    for key, value in report.items():
        print(f"{key}: {value}")
    empty_is_error = report["real_flv"] == 0 and not args.allow_empty
    ttl_min = report["remaining_ttl_min_seconds"]
    ttl_error = bool(report["real_flv"]) and (
        report["missing_expiry"] != 0 or ttl_min is None or ttl_min < max(0, args.min_remaining_seconds)
    )
    structure_error = (
        not report["header_valid"]
        or report["header_count"] != 1
        or report["extinf_count"] != report["entries"]
        or report["orphan_urls"] != 0
        or report["orphan_extinf"] != 0
        or report["malformed"] != 0
    )
    if args.strict and (
        empty_is_error
        or structure_error
        or report["duplicate_stable_paths"] != 0
        or ttl_error
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
