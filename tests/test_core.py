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
    load_env_file,
    parse_match_fields,
    playlist_text,
    publish_candidate,
    signed_at_from_url,
    streams_from_player_payload,
)


class CoreTests(unittest.TestCase):
    def test_config_from_env_uses_real_defaults(self) -> None:
        old = os.environ.pop("SPTV_HOME_URL", None)
        try:
            config = Config.from_env()
            self.assertEqual(config.home_url, "https://www.sptv.com/en/")
            self.assertEqual(config.delay_min_seconds, 4.0)
        finally:
            if old is not None:
                os.environ["SPTV_HOME_URL"] = old

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

    def test_auth_first_component_is_signing_timestamp(self) -> None:
        url = "https://cdn.example/sport/a.flv?auth_key=1785093935-5793-0-deadbeef"
        epoch, iso = signed_at_from_url(url)
        self.assertEqual(epoch, 1785093935)
        self.assertEqual(iso, "2026-07-26T19:25:35+00:00")

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

    def test_playlist_matches_reference_style_without_headers(self) -> None:
        config = Config(emit_headers=False)
        match = Match("1", datetime(2026, 7, 27, 0, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")), "POL D1", "A", "B")
        payload = {"code": 0, "purl": [{"url": "https://cdn.example/sport/1.flv?auth_key=1785093935-x"}]}
        stream = streams_from_player_payload(payload, match=match, api_url="api", page_url="page", max_lines=1)[0]
        text = playlist_text([stream], config=config)
        self.assertIn('group-title="SP TV (China)"', text)
        self.assertNotIn("#EXTVLCOPT", text)
        self.assertEqual(count_real_streams(text), 1)

    def test_empty_candidate_preserves_last_good(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sptv.m3u"
            out.write_text("#EXTM3U\n#EXTINF:-1,Old\nhttps://cdn.example/old.flv?auth_key=1-x\n", encoding="utf-8")
            published, reason = publish_candidate(out, "#EXTM3U\n", min_real_streams=1)
            self.assertFalse(published)
            self.assertIn("preserved last-good", reason)
            self.assertIn("old.flv", out.read_text(encoding="utf-8"))

    def test_audit_reference_spacing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.m3u"
            path.write_text(
                '#EXTM3U\n#EXTINF:-1 tvg-logo="" group-title="SP TV (China)" , A\n'
                'https://cdn.example/1.flv?auth_key=1785093935-a\n'
                '#EXTINF:-1 tvg-logo="" group-title="SP TV (China)" , B\n'
                'https://freem3u.xyz/static/no-signal/low.m3u8\n',
                encoding="utf-8",
            )
            report = audit_parse(path)
            self.assertEqual(report["real_flv"], 1)
            self.assertEqual(report["placeholders_or_other"], 1)

    def test_workflow_has_no_schedule_cron(self) -> None:
        workflow = (Path(__file__).parents[1] / ".github/workflows/update-sptv.yml").read_text(encoding="utf-8")
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("cron:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("repository_dispatch:", workflow)


if __name__ == "__main__":
    unittest.main()
