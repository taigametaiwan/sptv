#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import statistics
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

AUTH_RE = re.compile(r"[?&]auth_key=(\d+)-")


def parse(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    entries = 0
    real_flv = 0
    placeholders = 0
    malformed = 0
    groups: dict[str, int] = {}
    group_real_flv: dict[str, int] = {}
    group_other: dict[str, int] = {}
    signed: list[int] = []
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
                    # Chỉ nhận Unix epoch hợp lý (2000-2100); một số nguồn khác
                    # dùng auth_key có trường số không phải timestamp.
                    if 946684800 <= value <= 4102444800:
                        signed.append(value)
            else:
                placeholders += 1
                group_other[pending_group] = group_other.get(pending_group, 0) + 1
        elif line and not line.startswith("#"):
            malformed += 1

    duplicates = len(stable_paths) - len(set(stable_paths))
    gaps = [b - a for a, b in zip(sorted(signed), sorted(signed)[1:])]
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
        "signed_count": len(signed),
        "signed_min_epoch": min(signed) if signed else None,
        "signed_max_epoch": max(signed) if signed else None,
        "signed_min_utc": datetime.fromtimestamp(min(signed), utc).isoformat(timespec="seconds") if signed else None,
        "signed_max_utc": datetime.fromtimestamp(max(signed), utc).isoformat(timespec="seconds") if signed else None,
        "signed_span_seconds": max(signed) - min(signed) if len(signed) >= 2 else 0,
        "gap_min_seconds": min(gaps) if gaps else None,
        "gap_max_seconds": max(gaps) if gaps else None,
        "gap_mean_seconds": round(statistics.mean(gaps), 3) if gaps else None,
        "gap_median_seconds": statistics.median(gaps) if gaps else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit cấu trúc M3U SPTV, không gọi mạng.")
    parser.add_argument("path", nargs="?", default="sptv.m3u")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-empty", action="store_true", help="Cho phép playlist chưa có FLV ở lần chạy yên giờ.")
    args = parser.parse_args()
    path = Path(args.path)
    if not path.exists():
        print(f"ERROR: không tồn tại {path}", file=sys.stderr)
        return 2
    report = parse(path)
    for key, value in report.items():
        print(f"{key}: {value}")
    empty_is_error = report["real_flv"] == 0 and not args.allow_empty
    if args.strict and (empty_is_error or report["malformed"] != 0 or report["duplicate_stable_paths"] != 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
