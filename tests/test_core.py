from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from audit_m3u import parse as audit_parse
from sptv_api import (
    Config,
    HttpAttempt,
    Match,
    count_real_streams,
    expiry_from_url,
    load_env_file,
    metadata_from_player_payload,
    parse_match_fields,
    player_payload_diagnostics,
    player_payload_is_valid,
    playlist_text,
    publish_candidate,
    remaining_ttl_seconds,
    run,
    SptvClient,
    streams_from_player_payload,
)


class CoreTests(unittest.TestCase):
    def test_config_from_env_uses_refresh_cycle_defaults(self) -> None:
        keys = ["SPTV_HOME_URL", "SPTV_MIN_TTL_SECONDS"]
        old = {key: os.environ.pop(key, None) for key in keys}
        try:
            config = Config.from_env()
            self.assertEqual(config.home_url, "https://www.sptv.com/en/")
            self.assertEqual(config.delay_min_seconds, 4.0)
            self.assertEqual(config.min_ttl_seconds, 300)
            self.assertEqual(config.preserve_old_min_ttl_seconds, 60)
            self.assertEqual(config.max_scan_seconds, 210)
        finally:
            for key, value in old.items():
                if value is not None:
                    os.environ[key] = value

    def test_load_env_file_does_not_override_existing_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("SPTV_TEST_VALUE=from-file\n", encoding="utf-8")
            os.environ["SPTV_TEST_VALUE"] = "existing"
            try:
                load_env_file(env_path)
                self.assertEqual(os.environ["SPTV_TEST_VALUE"], "existing")
            finally:
                os.environ.pop("SPTV_TEST_VALUE", None)

    def test_auth_first_component_is_expiry_timestamp(self) -> None:
        url = "https://cdn.example/sport/a.flv?auth_key=1785093935-5793-0-deadbeef"
        epoch, iso = expiry_from_url(url)
        self.assertEqual(epoch, 1785093935)
        self.assertEqual(iso, "2026-07-26T19:25:35+00:00")
        self.assertEqual(remaining_ttl_seconds(url, 1785093000), 935)

    def test_parse_schedule_indexes(self) -> None:
        fields = [""] * 44
        fields[0] = "5238077"
        fields[7] = "POL D1"
        fields[14] = "Home"
        fields[18] = "Away"
        fields[43] = "202607270030"
        match = parse_match_fields(fields)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.player_id, "5238077")
        self.assertEqual(match.home, "Home")
        self.assertEqual(match.away, "Away")
        self.assertEqual(match.start_at.strftime("%H:%M %d/%m"), "23:30 26/07")

    def test_player_payload_dedupes_by_stable_path(self) -> None:
        match = Match("1", datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")), "League", "A", "B")
        payload = {
            "code": 0,
            "purl": [
                {"url": "https://cdn.example/sport/1.flv?auth_key=1785093935-a"},
                {"url": "https://cdn.example/sport/1.flv?auth_key=1785093940-b"},
                {"url": "https://cdn.example/sport/2.m3u8"},
            ],
        }
        streams = streams_from_player_payload(
            payload,
            match=match,
            api_url="https://api.example",
            page_url="https://page.example",
            max_lines=4,
        )
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0].expires_at_epoch, 1785093935)

    def test_player_payload_accepts_nested_and_json_string_urls(self) -> None:
        match = Match("1", datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")), "League", "A", "B")
        payload = {
            "data": {
                "code": "0",
                "purl": '["https:\\/\\/cdn.example\\/sport\\/10.flv?auth_key=1785093935-a",'
                '{"src":"https:\\/\\/cdn.example\\/sport\\/11.flv?auth_key=1785093940-b"}]',
            }
        }
        streams = streams_from_player_payload(
            payload,
            match=match,
            api_url="https://api.example",
            page_url="https://page.example",
            max_lines=4,
        )
        self.assertEqual([item.line_number for item in streams], [1, 2])

    def test_playlist_matches_reference_style_without_headers(self) -> None:
        config = Config(emit_headers=False)
        match = Match("1", datetime(2026, 7, 27, 0, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")), "POL D1", "A", "B")
        payload = {"code": 0, "purl": [{"url": "https://cdn.example/sport/1.flv?auth_key=1785093935-x"}]}
        stream = streams_from_player_payload(payload, match=match, api_url="api", page_url="page", max_lines=1)[0]
        text = playlist_text([stream], config=config)
        self.assertIn('group-title="SP TV (China)"', text)
        self.assertNotIn("#EXTVLCOPT", text)
        self.assertEqual(count_real_streams(text), 1)

    def test_empty_candidate_preserves_only_unexpired_previous_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sptv.m3u"
            out.write_text(
                '#EXTM3U\n#EXTINF:-1 group-title="SP TV (China)",Old\n'
                'https://cdn.example/old.flv?auth_key=1785094000-x\n',
                encoding="utf-8",
            )
            result = publish_candidate(
                out,
                "#EXTM3U\n",
                min_real_streams=1,
                now_epoch=1785093000,
                preserve_old_min_ttl_seconds=60,
            )
            self.assertEqual(result.status, "PRESERVED_UNEXPIRED")
            self.assertIn("old.flv", out.read_text(encoding="utf-8"))

    def test_expired_seed_is_removed_instead_of_preserved_forever(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sptv.m3u"
            out.write_text(
                '#EXTM3U\n#EXTINF:-1 group-title="SP TV (China)",Expired\n'
                'https://cdn.example/expired.flv?auth_key=1785092900-x\n',
                encoding="utf-8",
            )
            result = publish_candidate(
                out,
                "#EXTM3U\n",
                min_real_streams=1,
                now_epoch=1785093000,
                preserve_old_min_ttl_seconds=60,
            )
            self.assertEqual(result.status, "EMPTY_NO_VALID_KEY")
            self.assertEqual(out.read_text(encoding="utf-8"), "#EXTM3U\n")
            self.assertEqual(result.expired_removed, 1)

    def test_fresh_candidate_replaces_same_path_and_keeps_other_valid_old_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sptv.m3u"
            out.write_text(
                '#EXTM3U\n#EXTINF:-1,Old A\nhttps://cdn.example/a.flv?auth_key=1785093800-old\n'
                '#EXTINF:-1,Old B\nhttps://cdn.example/b.flv?auth_key=1785093900-old\n',
                encoding="utf-8",
            )
            candidate = (
                '#EXTM3U\n#EXTINF:-1,Fresh A\nhttps://cdn.example/a.flv?auth_key=1785094500-new\n'
            )
            result = publish_candidate(
                out,
                candidate,
                min_real_streams=1,
                now_epoch=1785093000,
                preserve_old_min_ttl_seconds=60,
            )
            text = out.read_text(encoding="utf-8")
            self.assertEqual(result.status, "PUBLISHED_FRESH")
            self.assertIn("1785094500-new", text)
            self.assertNotIn("1785093800-old", text)
            self.assertIn("b.flv", text)
            self.assertEqual(result.final_count, 2)

    def test_audit_reports_expiry_and_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.m3u"
            path.write_text(
                '#EXTM3U\n#EXTINF:-1 tvg-logo="" group-title="SP TV (China)" , A\n'
                'https://cdn.example/1.flv?auth_key=1785094000-a\n',
                encoding="utf-8",
            )
            report = audit_parse(path, now_epoch=1785093000)
            self.assertEqual(report["real_flv"], 1)
            self.assertEqual(report["remaining_ttl_min_seconds"], 1000)
            self.assertEqual(report["missing_expiry"], 0)


    def test_expiry_rejects_impossible_epoch(self) -> None:
        self.assertEqual(
            expiry_from_url("https://cdn.example/a.flv?auth_key=999999999999-x"),
            (None, None),
        )

    def test_player_metadata_accepts_csv_string(self) -> None:
        fields = [""] * 44
        fields[0] = "5238077"
        fields[7] = "CSV League"
        fields[14] = "CSV Home"
        fields[18] = "CSV Away"
        fields[43] = "202607270030"
        fallback = Match("5238077", None, "", "", "")
        parsed = metadata_from_player_payload(
            {"code": 0, "m": ",".join(fields), "purl": []},
            fallback,
            "Asia/Shanghai",
        )
        self.assertEqual(parsed.league, "CSV League")
        self.assertEqual(parsed.home, "CSV Home")
        self.assertEqual(parsed.away, "CSV Away")
        self.assertIsNotNone(parsed.start_at)

    def test_json_error_records_one_http_attempt(self) -> None:
        class BadJsonResponse:
            url = "https://api.example/player"
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self):
                raise ValueError("bad json")

        client = SptvClient(Config(network_retries=0))
        client.session.get = lambda *args, **kwargs: BadJsonResponse()  # type: ignore[method-assign]
        payload, attempts = client._get_json("https://api.example/player")
        self.assertIsNone(payload)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].status, 200)
        self.assertIn("ValueError", attempts[0].error)

    def test_player_payload_health_distinguishes_quiet_from_invalid(self) -> None:
        self.assertTrue(player_payload_is_valid({"code": 0, "purl": []}))
        self.assertTrue(player_payload_is_valid({"data": {"code": 1, "purl": []}}))
        self.assertFalse(player_payload_is_valid({}))
        self.assertFalse(player_payload_is_valid({"unexpected": []}))
        self.assertFalse(player_payload_is_valid(None))

    def test_candidate_below_threshold_merges_with_valid_previous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sptv.m3u"
            out.write_text(
                '#EXTM3U\n#EXTINF:-1,Old A\nhttps://cdn.example/a.flv?auth_key=1785094000-old\n',
                encoding="utf-8",
            )
            candidate = (
                '#EXTM3U\n#EXTINF:-1,Fresh B\nhttps://cdn.example/b.flv?auth_key=1785094100-new\n'
            )
            result = publish_candidate(
                out,
                candidate,
                min_real_streams=2,
                now_epoch=1785093000,
                preserve_old_min_ttl_seconds=60,
            )
            text = out.read_text(encoding="utf-8")
            self.assertEqual(result.status, "PUBLISHED_MERGED")
            self.assertEqual(result.final_count, 2)
            self.assertIn("a.flv", text)
            self.assertIn("b.flv", text)

    def test_audit_detects_orphan_url_and_missing_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.m3u"
            path.write_text(
                "https://cdn.example/a.flv?auth_key=1785094000-a\n",
                encoding="utf-8",
            )
            report = audit_parse(path, now_epoch=1785093000)
            self.assertFalse(report["header_valid"])
            self.assertEqual(report["orphan_urls"], 1)
            self.assertGreaterEqual(report["malformed"], 2)

    def test_audit_detects_orphan_extinf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.m3u"
            path.write_text(
                '#EXTM3U\n#EXTINF:-1,A\n#EXTINF:-1,B\n'
                'https://cdn.example/b.flv?auth_key=1785094000-a\n',
                encoding="utf-8",
            )
            report = audit_parse(path, now_epoch=1785093000)
            self.assertEqual(report["extinf_count"], 2)
            self.assertEqual(report["entries"], 1)
            self.assertEqual(report["orphan_extinf"], 1)
            self.assertGreater(report["malformed"], 0)

    def test_strict_audit_rejects_url_without_extinf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.m3u"
            path.write_text(
                '#EXTM3U\nhttps://cdn.example/a.flv?auth_key=1785094000-a\n',
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).parents[1] / "audit_m3u.py"), str(path), "--strict"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)

    def test_run_fails_and_preserves_playlist_when_all_player_calls_invalid(self) -> None:
        class FailedClient:
            def __init__(self, config: Config) -> None:
                self.config = config

            def warm_session(self) -> HttpAttempt:
                return HttpAttempt("https://www.sptv.com/en/", 200, 0.01)

            def fetch_player(self, match: Match):
                return [], [HttpAttempt("https://api.example", 500, 0.01, "HTTP 500")], {
                    "valid_payload": False,
                    "code": None,
                    "stream_item_count": 0,
                }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "sptv.m3u"
            debug = Path(tmp) / "debug.json"
            original = (
                '#EXTM3U\n#EXTINF:-1,Old\n'
                'https://cdn.example/old.flv?auth_key=1785094000-old\n'
            )
            output.write_text(original, encoding="utf-8")
            config = Config(delay_min_seconds=0, delay_max_seconds=0, network_retries=0)
            from unittest.mock import patch

            with patch("sptv_api.SptvClient", FailedClient):
                code = run(
                    config=config,
                    output_path=output,
                    debug_path=debug,
                    exact_ids=["5238077"],
                    random_seed=1,
                )
            self.assertEqual(code, 3)
            self.assertEqual(output.read_text(encoding="utf-8"), original)
            self.assertIn("PLAYER_API_FAILED_ALL", debug.read_text(encoding="utf-8"))

    def test_run_accepts_valid_empty_player_response_as_quiet_hour(self) -> None:
        class QuietClient:
            def __init__(self, config: Config) -> None:
                self.config = config

            def warm_session(self) -> HttpAttempt:
                return HttpAttempt("https://www.sptv.com/en/", 200, 0.01)

            def fetch_player(self, match: Match):
                payload = {"code": 0, "purl": []}
                return [], [HttpAttempt("https://api.example", 200, 0.01)], player_payload_diagnostics(payload)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "sptv.m3u"
            debug = Path(tmp) / "debug.json"
            output.write_text("#EXTM3U\n", encoding="utf-8")
            config = Config(delay_min_seconds=0, delay_max_seconds=0, network_retries=0)
            from unittest.mock import patch

            with patch("sptv_api.SptvClient", QuietClient):
                code = run(
                    config=config,
                    output_path=output,
                    debug_path=debug,
                    exact_ids=["5238077"],
                    random_seed=1,
                )
            self.assertEqual(code, 0)
            self.assertIn('"valid_player_responses": 1', debug.read_text(encoding="utf-8"))

    def test_workflow_matches_five_minute_schedule_design(self) -> None:
        root = Path(__file__).parents[1]
        workflow = (root / ".github/workflows/update-sptv.yml").read_text(encoding="utf-8")
        self.assertIn("schedule:", workflow)
        self.assertIn('cron: "*/5 * * * *"', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("repository_dispatch:", workflow)
        self.assertIn("refresh-sptv", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("git reset --hard origin/main", workflow)
        self.assertNotIn("git pull --rebase", workflow)
        self.assertIn("git diff --quiet -- sptv.m3u", workflow)
        self.assertIn('SPTV_MAX_SCAN_SECONDS: "210"', workflow)
        self.assertIn('SPTV_MIN_TTL_SECONDS: "300"', workflow)
        self.assertIn("--min-remaining-seconds 30", workflow)

    def test_source_never_probes_flv_media(self) -> None:
        source = (Path(__file__).parents[1] / "sptv_api.py").read_text(encoding="utf-8")
        self.assertNotIn("Range", source)
        self.assertNotIn("verify_stream", source.lower())
        self.assertNotIn("session.get(stream.media_url", source)


if __name__ == "__main__":
    unittest.main()
