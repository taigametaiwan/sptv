from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from audit_m3u import parse as audit_parse
from sptv_api import (
    Config,
    Match,
    count_real_streams,
    expiry_from_url,
    load_env_file,
    parse_match_fields,
    playlist_text,
    publish_candidate,
    remaining_ttl_seconds,
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
            self.assertEqual(config.min_ttl_seconds, 900)
            self.assertEqual(config.preserve_old_min_ttl_seconds, 60)
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
                'https://cdn.example/old.flv?auth_key=2000-x\n',
                encoding="utf-8",
            )
            result = publish_candidate(
                out,
                "#EXTM3U\n",
                min_real_streams=1,
                now_epoch=1000,
                preserve_old_min_ttl_seconds=60,
            )
            self.assertEqual(result.status, "PRESERVED_UNEXPIRED")
            self.assertIn("old.flv", out.read_text(encoding="utf-8"))

    def test_expired_seed_is_removed_instead_of_preserved_forever(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sptv.m3u"
            out.write_text(
                '#EXTM3U\n#EXTINF:-1 group-title="SP TV (China)",Expired\n'
                'https://cdn.example/expired.flv?auth_key=900-x\n',
                encoding="utf-8",
            )
            result = publish_candidate(
                out,
                "#EXTM3U\n",
                min_real_streams=1,
                now_epoch=1000,
                preserve_old_min_ttl_seconds=60,
            )
            self.assertEqual(result.status, "EMPTY_NO_VALID_KEY")
            self.assertEqual(out.read_text(encoding="utf-8"), "#EXTM3U\n")
            self.assertEqual(result.expired_removed, 1)

    def test_fresh_candidate_replaces_same_path_and_keeps_other_valid_old_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sptv.m3u"
            out.write_text(
                '#EXTM3U\n#EXTINF:-1,Old A\nhttps://cdn.example/a.flv?auth_key=1800-old\n'
                '#EXTINF:-1,Old B\nhttps://cdn.example/b.flv?auth_key=1900-old\n',
                encoding="utf-8",
            )
            candidate = (
                '#EXTM3U\n#EXTINF:-1,Fresh A\nhttps://cdn.example/a.flv?auth_key=2500-new\n'
            )
            result = publish_candidate(
                out,
                candidate,
                min_real_streams=1,
                now_epoch=1000,
                preserve_old_min_ttl_seconds=60,
            )
            text = out.read_text(encoding="utf-8")
            self.assertEqual(result.status, "PUBLISHED_FRESH")
            self.assertIn("2500-new", text)
            self.assertNotIn("1800-old", text)
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

    def test_workflow_matches_external_15_minute_dispatch_design(self) -> None:
        root = Path(__file__).parents[1]
        workflow = (root / ".github/workflows/update-sptv.yml").read_text(encoding="utf-8")
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("cron:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("repository_dispatch:", workflow)
        self.assertIn("refresh-sptv", workflow)
        self.assertIn("cancel-in-progress: true", workflow)
        self.assertIn('SPTV_MIN_TTL_SECONDS: "900"', workflow)
        self.assertIn("--min-remaining-seconds 30", workflow)

    def test_source_never_probes_flv_media(self) -> None:
        source = (Path(__file__).parents[1] / "sptv_api.py").read_text(encoding="utf-8")
        self.assertNotIn("Range", source)
        self.assertNotIn("verify_stream", source.lower())
        self.assertNotIn("session.get(stream.media_url", source)


if __name__ == "__main__":
    unittest.main()
