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


def parse(path: Path, *, now_epoch: int | None = None) -> dict[str, object]:
    current = int(time.time()) if now_epoch is None else int(now_epoch)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    entries = 0
    real_flv = 0
    placeholders = 0
    malformed = 0
    groups: dict[str, int] = {}
    group_real_flv: dict[str, int] = {}
    group_other: dict[str, int] = {}
    expiries: list[int] = []
    remaining: list[int] = []
    missing_expiry = 0
    stable_paths: list[str] = []
    pending_group = ""

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            entries += 1
            match = re.search(r'group-title="([^"]*)"', line)
            pending_group = match.group(1) if match else ""
            groups[pending_group] = groups.get(pending_group, 0) + 1
        elif line.startswith(("http://", "https://")):
            parts = urllib.parse.urlsplit(line)
            if not parts.netloc:
                malformed += 1
                continue
            if parts.path.lower().endswith(".flv"):
                real_flv += 1
                group_real_flv[pending_group] = group_real_flv.get(pending_group, 0) + 1
                stable_paths.append(f"{parts.netloc.lower()}{parts.path.lower()}")
                match = AUTH_RE.search(line)
                if match:
                    value = int(match.group(1))
                    if 946684800 <= value <= 4102444800:
                        expiries.append(value)
                        remaining.append(value - current)
                    else:
                        missing_expiry += 1
                else:
                    missing_expiry += 1
            else:
                placeholders += 1
                group_other[pending_group] = group_other.get(pending_group, 0) + 1
        elif line and not line.startswith("#"):
            malformed += 1

    duplicates = len(stable_paths) - len(set(stable_paths))
    gaps = [b - a for a, b in zip(sorted(expiries), sorted(expiries)[1:])]
    utc = ZoneInfo("UTC")
    return {
        "entries": entries,
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
    if args.strict and (
        empty_is_error
        or report["malformed"] != 0
        or report["duplicate_stable_paths"] != 0
        or ttl_error
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
