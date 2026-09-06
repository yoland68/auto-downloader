"""The glance-only lane (glance T-314), offline: yt-dlp and Gemini stubbed,
the sidecar/record machinery real.

    python3 -m pytest tests

Pins, in the order they would hurt:
  * the row says which lane it came through — ingest_mode='glance_only',
    download_path None, playlist_id from CONFIG (a watch URL cannot know it);
    the download lane's row says 'download'
  * the sidecar is the completion marker: a summarized video is not pending
  * the lane refuses to run without a pusher (spend for nothing)
  * URL mode failing falls through to captions, fetched at most once
"""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from glance_only import GlanceOnlyIngester, playlist_id_from_url  # noqa: E402
from summarizer import VideoSummarizer, make_record  # noqa: E402

SL_URL = "https://www.youtube.com/playlist?list=PLCBrsPqTz60U"
VID = "sn2qfuxTNG4"


def _info(video_id=VID, **over):
    base = dict(id=video_id, title="Chai Jing on Zhu Rongji", channel="Chai Jing",
                webpage_url=f"https://www.youtube.com/watch?v={video_id}",
                upload_date="20260901", duration=1234, description="desc",
                chapters=[], tags=["t"], view_count=7, thumbnail="https://i/x.jpg")
    base.update(over)
    return base


class FakeSummarizer(VideoSummarizer):
    """Real summarize_info / sidecar IO; Gemini replaced by canned answers."""

    def __init__(self, url_answer="**TL;DR** from the url", transcript_answer=None):
        super().__init__({"summarize": {"enabled": False}},
                         logger=logging.getLogger("test"))
        self.enabled = True  # bypass the key/SDK gate; no client is ever called
        self.url_answer = url_answer
        self.transcript_answer = transcript_answer
        self.url_calls = 0
        self.transcript_calls = 0

    def _summarize_via_url(self, info):
        self.url_calls += 1
        return self.url_answer

    def _summarize_via_transcript(self, info, text):
        self.transcript_calls += 1
        return self.transcript_answer and f"{self.transcript_answer} [{len(text)} chars]"


class FakePusher:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.records = []

    def push_video(self, record):
        self.records.append(record)
        return True


def _lane(tmp_path, summarizer=None, pusher=None, listing=(VID,), info=None,
          captions=None, **cfg_over):
    cfg = {"glance_only": {"enabled": True, "state_dir": str(tmp_path / "state"),
                           "playlists": [{"url": SL_URL, "label": "SL"}],
                           "sleep_between_s": 0, **cfg_over}}
    lane = GlanceOnlyIngester(cfg, summarizer or FakeSummarizer(),
                              pusher if pusher is not None else FakePusher(),
                              logger=logging.getLogger("test"))
    # yt-dlp is the network; replace the three reads, never the machinery.
    lane.list_playlist = lambda url: list(listing)
    lane.fetch_info = lambda video_id: dict(info or _info(video_id))
    calls = {"captions": 0}

    def fetch_transcript_text(video_id):
        calls["captions"] += 1
        return captions
    lane.fetch_transcript_text = fetch_transcript_text
    lane._caption_calls = calls
    return lane


# -- the row ------------------------------------------------------------------

def test_playlist_id_is_parsed_from_the_url():
    assert playlist_id_from_url(SL_URL) == "PLCBrsPqTz60U"
    assert playlist_id_from_url("https://youtube.com/playlist?list=PLCBrsPqTz60U&si=abc") == "PLCBrsPqTz60U"
    assert playlist_id_from_url("https://www.youtube.com/watch?v=x") is None


def test_glance_only_row_names_its_lane(tmp_path):
    lane = _lane(tmp_path)
    counts = lane.run_once()
    assert counts == {"pending": 1, "summarized": 1, "pushed": 1, "failed": 0}
    [row] = lane.pusher.records
    assert row["video_id"] == VID
    assert row["ingest_mode"] == "glance_only"
    assert row["download_path"] is None
    assert row["playlist_id"] == "PLCBrsPqTz60U"     # from config, not yt-dlp
    assert row["metadata"]["playlist_label"] == "SL"
    assert row["metadata"]["input_mode"] == "url"
    assert row["summary_md"] == "**TL;DR** from the url"
    assert row["upload_date"] == "2026-09-01"
    assert row["title"] == "Chai Jing on Zhu Rongji"


def test_download_lane_row_says_download(tmp_path):
    """The complement: the download lane's build_record stamps its lane, so
    the column is written explicitly by both writers, never left to the
    database default from this side."""
    root = tmp_path / "downloads" / "wr3"
    root.mkdir(parents=True)
    mp4 = root / f"20260901 - A title [{VID}].mp4"
    mp4.write_bytes(b"")
    mp4.with_suffix(".info.json").write_text(json.dumps(_info()))
    s = FakeSummarizer()
    s.download_path = tmp_path / "downloads"
    s.write_summary_file(s._summary_path(mp4), VID, _info(), "body", "url")
    row = s.build_record(VID)
    assert row["ingest_mode"] == "download"
    assert row["download_path"] == f"wr3/20260901 - A title [{VID}].mp4"
    assert row["summary_md"] == "body"


def test_make_record_has_no_default_lane():
    with pytest.raises(TypeError):
        make_record(VID, _info(), "s", {}, "m", playlist_id=None, download_path=None)  # type: ignore[call-arg]


# -- the sidecar is the state ---------------------------------------------------

def test_summarized_video_is_not_pending_again(tmp_path):
    lane = _lane(tmp_path)
    lane.run_once()
    assert lane.is_done(VID)
    assert lane.summarizer.url_calls == 1
    counts = lane.run_once()
    assert counts == {"pending": 0, "summarized": 0, "pushed": 0, "failed": 0}
    assert lane.summarizer.url_calls == 1  # no second Gemini call


def test_build_record_rebuilds_from_sidecars_alone(tmp_path):
    """The retry path: a parked id is rebuilt from disk, no network."""
    lane = _lane(tmp_path)
    lane.run_once()
    lane.fetch_info = lambda video_id: pytest.fail("retry must not touch yt-dlp")
    row = lane.build_record(VID)
    assert row["ingest_mode"] == "glance_only"
    assert row["playlist_id"] == "PLCBrsPqTz60U"
    assert row["summary_md"] == "**TL;DR** from the url"


def test_max_per_tick_bounds_the_pass_and_the_rest_stays_pending(tmp_path):
    lane = _lane(tmp_path, listing=("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"),
                 max_per_tick=2)
    counts = lane.run_once()
    assert counts["pending"] == 3 and counts["summarized"] == 2
    assert lane.run_once()["summarized"] == 1


# -- refusals -------------------------------------------------------------------

def test_lane_refuses_without_a_pusher(tmp_path):
    lane = _lane(tmp_path, pusher=FakePusher(enabled=False))
    assert lane.enabled is False
    assert lane.run_once() == {"pending": 0, "summarized": 0, "pushed": 0, "failed": 0}
    assert lane.summarizer.url_calls == 0


def test_lane_refuses_without_a_summarizer(tmp_path):
    s = FakeSummarizer()
    s.enabled = False
    assert _lane(tmp_path, summarizer=s).enabled is False


def test_lane_refuses_when_not_enabled(tmp_path):
    assert _lane(tmp_path, enabled=False).enabled is False


# -- the fallback ---------------------------------------------------------------

def test_url_failure_falls_through_to_captions_once(tmp_path):
    lane = _lane(tmp_path, summarizer=FakeSummarizer(url_answer=None,
                                                     transcript_answer="from captions"),
                 captions="hello world")
    counts = lane.run_once()
    assert counts["summarized"] == 1
    [row] = lane.pusher.records
    assert row["metadata"]["input_mode"] == "transcript"
    assert row["summary_md"] == "from captions [11 chars]"
    assert lane._caption_calls["captions"] == 1


def test_no_captions_either_is_a_failure_not_a_row(tmp_path):
    lane = _lane(tmp_path, summarizer=FakeSummarizer(url_answer=None), captions=None)
    counts = lane.run_once()
    assert counts == {"pending": 1, "summarized": 0, "pushed": 0, "failed": 1}
    assert not lane.is_done(VID)          # no sidecar → retried next tick
    assert lane.pusher.records == []


def test_url_success_never_fetches_captions(tmp_path):
    lane = _lane(tmp_path, captions="should not be read")
    lane.run_once()
    assert lane._caption_calls["captions"] == 0
