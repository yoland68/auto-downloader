#!/usr/bin/env python3
"""
Glance-only playlist lane (glance T-314).

Some playlists Yoland wants summarized into the glance deck but NOT downloaded:
no mp4, no Plex entry, nothing on disk but the summary. This module polls
those playlists, fetches each new video's metadata with yt-dlp
(--skip-download), summarizes it with the SAME Gemini summarizer the download
lane uses (URL mode; auto-captions as the fallback), and upserts a
youtube_videos row with ingest_mode='glance_only' and download_path=None. The
glance hub turns it into a card exactly like a downloaded video; the deck
withholds "Open in Plex" because of the lane.

State lives under `glance_only.state_dir` (default ./glance_only):
    <id>.info.json      yt-dlp metadata, plus the playlist we found it in
                        (yt-dlp cannot know that from a watch URL)
    <id>.summary.md     the summary sidecar — THE completion marker, as in
                        the download lane: the artifact is the state, so it
                        cannot desync from a separate list
    <id>.en.vtt         auto-captions, present only when URL mode failed

Config (config.json):
    "glance_only": {
        "enabled": true,
        "playlists": [{"url": "https://youtube.com/playlist?list=...", "label": "SL"}],
        "state_dir": "./glance_only",
        "check_interval_seconds": 900,
        "max_per_tick": 3,
        "sleep_between_s": 15
    }

Credentials are the download lane's (GEMINI_API_KEY, SUPABASE_URL,
SUPABASE_SERVICE_ROLE_KEY from the environment). The lane disables itself,
saying why, when the summarizer or the pusher is disabled: a summary nobody
pushes is Gemini spend for nothing, and the download lane's
`summarize.enabled` gate is not to be bypassed by a second config block.

Runs as its own scheduler job. It is NOT behind the download lane's
1-video-per-hour rate limit — that limit exists because downloads are what
YouTube throttles; a metadata read and a Gemini call are not a download.
"""

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playlist_manager import yt_dlp_auth_args

DEFAULTS = {
    "enabled": False,
    "playlists": [],
    "state_dir": "./glance_only",
    "check_interval_seconds": 900,
    "max_per_tick": 3,           # Gemini calls per pass; the backlog drains over ticks
    "sleep_between_s": 15,       # between Gemini calls, same as summarize_backfill
    "yt_dlp_timeout_s": 120,
}

INGEST_MODE = 'glance_only'

_PLAYLIST_ID_RE = re.compile(r'[?&]list=([A-Za-z0-9_-]+)')
_VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')


def playlist_id_from_url(url: str) -> Optional[str]:
    m = _PLAYLIST_ID_RE.search(url or '')
    return m.group(1) if m else None


class GlanceOnlyIngester:
    """Polls glance-only playlists; summarizes and pushes without downloading."""

    def __init__(self, config: Dict[str, Any], summarizer, pusher,
                 logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger('GlanceOnly')
        self.config = dict(DEFAULTS)
        self.config.update(config.get('glance_only', {}) or {})
        self.yt_dlp_options = config.get('yt_dlp_options', {}) or {}
        self.state_dir = Path(self.config['state_dir'])
        self.summarizer = summarizer
        self.pusher = pusher
        self.playlists: List[Dict[str, Any]] = [
            p for p in (self.config.get('playlists') or [])
            if isinstance(p, dict) and p.get('url')]
        self.enabled = self._decide_enabled()

    def _decide_enabled(self) -> bool:
        if not self.config.get('enabled'):
            self.logger.info("Glance-only lane disabled (glance_only.enabled is false)")
            return False
        if not self.playlists:
            self.logger.warning("Glance-only lane disabled: no playlists configured")
            return False
        if not (self.summarizer and getattr(self.summarizer, 'enabled', False)):
            self.logger.warning("Glance-only lane disabled: summarizer is disabled "
                                "(summarize.enabled false, GEMINI_API_KEY unset, or "
                                "google-genai missing)")
            return False
        if not (self.pusher and getattr(self.pusher, 'enabled', False)):
            self.logger.warning("Glance-only lane disabled: glance push is disabled "
                                "(summarize.glance_push false or SUPABASE_* unset) — "
                                "a summary nobody pushes is spend for nothing")
            return False
        self.state_dir.mkdir(parents=True, exist_ok=True)
        labels = ', '.join(
            f"{p.get('label') or '?'}={playlist_id_from_url(p['url']) or p['url']}"
            for p in self.playlists)
        self.logger.info(f"Glance-only lane enabled: {labels}; state in {self.state_dir}")
        return True

    # ------------------------------------------------------------------
    # Paths (the sidecar is the completion marker)
    # ------------------------------------------------------------------

    def summary_path(self, video_id: str) -> Path:
        return self.state_dir / f"{video_id}.summary.md"

    def info_path(self, video_id: str) -> Path:
        return self.state_dir / f"{video_id}.info.json"

    def is_done(self, video_id: str) -> bool:
        return self.summary_path(video_id).exists()

    # ------------------------------------------------------------------
    # yt-dlp reads (no downloads anywhere in this file)
    # ------------------------------------------------------------------

    def _run_yt_dlp(self, args: List[str], what: str) -> Optional[str]:
        cmd = ['yt-dlp', '--no-warnings'] + yt_dlp_auth_args(self.yt_dlp_options) + args
        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=int(self.config['yt_dlp_timeout_s']))
        except subprocess.TimeoutExpired:
            self.logger.error(f"glance_only: yt-dlp timeout ({what})")
            return None
        except Exception as e:
            self.logger.error(f"glance_only: yt-dlp failed to run ({what}): {e}")
            return None
        if res.returncode != 0:
            self.logger.error(f"glance_only: yt-dlp exit {res.returncode} ({what}): "
                              f"{res.stderr.strip()[:300]}")
            return None
        return res.stdout

    def list_playlist(self, url: str) -> List[str]:
        """Video ids in playlist order. [] on failure — logged, and a failed
        listing yields no work rather than wrong work (nothing here is ever
        deleted on absence, so an empty read is safe)."""
        out = self._run_yt_dlp(['--flat-playlist', '--get-id', url], f"list {url}")
        if out is None:
            return []
        ids = [line.strip() for line in out.splitlines() if line.strip()]
        bad = [i for i in ids if not _VIDEO_ID_RE.match(i)]
        if bad:
            self.logger.warning(f"glance_only: ignoring {len(bad)} non-id line(s) "
                                f"from {url}: {bad[:3]}")
        return [i for i in ids if _VIDEO_ID_RE.match(i)]

    def fetch_info(self, video_id: str) -> Optional[Dict[str, Any]]:
        out = self._run_yt_dlp(
            ['--skip-download', '--no-playlist', '--dump-single-json',
             f"https://www.youtube.com/watch?v={video_id}"],
            f"info {video_id}")
        if out is None:
            return None
        try:
            info = json.loads(out)
        except json.JSONDecodeError as e:
            self.logger.error(f"glance_only: unparseable info for {video_id}: {e}")
            return None
        return info if isinstance(info, dict) else None

    def fetch_transcript_text(self, video_id: str) -> Optional[str]:
        """Auto-captions via --skip-download, converted to plain text by the
        summarizer's own cue stripper. Only reached when URL mode failed."""
        out = self._run_yt_dlp(
            ['--skip-download', '--no-playlist', '--write-subs', '--write-auto-subs',
             '--sub-langs', 'en', '--sub-format', 'vtt',
             '--output', str(self.state_dir / '%(id)s'),
             f"https://www.youtube.com/watch?v={video_id}"],
            f"captions {video_id}")
        if out is None:
            return None
        for p in sorted(self.state_dir.glob(f"{video_id}*.vtt")):
            text = self.summarizer._transcript_to_text(p)
            if text:
                return text
        self.logger.info(f"glance_only: no captions for {video_id}")
        return None

    # ------------------------------------------------------------------
    # One video
    # ------------------------------------------------------------------

    def process(self, video_id: str, playlist: Dict[str, Any],
                force: bool = False) -> Optional[Dict[str, Any]]:
        """Metadata → summary → sidecar → record. Never raises; None on failure."""
        try:
            return self._process(video_id, playlist, force)
        except Exception as e:
            self.logger.error(f"glance_only: unexpected error for {video_id}: {e}")
            return None

    def _process(self, video_id: str, playlist: Dict[str, Any],
                 force: bool) -> Optional[Dict[str, Any]]:
        if self.is_done(video_id) and not force:
            return self.build_record(video_id)

        info = self.fetch_info(video_id)
        if not info:
            return None
        # A watch URL carries no playlist; record the one we found it in, so
        # the row's playlist_id is a fact rather than the null the download
        # lane has been writing (glance T-314 side finding).
        info['_glance_playlist_id'] = playlist_id_from_url(playlist['url'])
        info['_glance_playlist_label'] = playlist.get('label')
        self._write_json(self.info_path(video_id), info)

        result = self.summarizer.summarize_info(
            info, transcript=lambda: self.fetch_transcript_text(video_id),
            video_id=video_id)
        if result is None:
            return None
        summary, used_mode = result
        self.summarizer.write_summary_file(
            self.summary_path(video_id), video_id, info, summary, used_mode)
        self.logger.info(f"glance_only: summarized {video_id} ({used_mode} mode)")
        return self.build_record(video_id)

    def build_record(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Rebuild the row from the sidecars — the retry path's input too."""
        from summarizer import make_record
        summary_md, header = self.summarizer.read_summary_md(self.summary_path(video_id))
        if summary_md is None:
            self.logger.warning(f"glance_only: no summary sidecar for {video_id}")
            return None
        info = self._read_json(self.info_path(video_id)) or {}
        record = make_record(
            video_id, info, summary_md, header,
            self.summarizer.config['gemini_model'],
            playlist_id=info.get('_glance_playlist_id'),
            download_path=None, ingest_mode=INGEST_MODE)
        if info.get('_glance_playlist_label'):
            record['metadata']['playlist_label'] = info['_glance_playlist_label']
        return record

    # ------------------------------------------------------------------
    # One pass
    # ------------------------------------------------------------------

    def pending(self) -> List[Tuple[str, Dict[str, Any]]]:
        """(video_id, playlist) for every listed video without a sidecar, in
        playlist order, first playlist wins a video listed twice."""
        seen = set()
        out: List[Tuple[str, Dict[str, Any]]] = []
        for playlist in self.playlists:
            for video_id in self.list_playlist(playlist['url']):
                if video_id in seen:
                    continue
                seen.add(video_id)
                if not self.is_done(video_id):
                    out.append((video_id, playlist))
        return out

    def run_once(self, limit: Optional[int] = None, dry_run: bool = False,
                 sleep_s: Optional[float] = None) -> Dict[str, int]:
        """One pass: list, summarize up to `limit` new videos, push each.
        Never raises — a broken pass is logged and the next tick tries again."""
        counts = dict(pending=0, summarized=0, pushed=0, failed=0)
        if not self.enabled:
            return counts
        try:
            todo = self.pending()
            counts['pending'] = len(todo)
            limit = int(self.config['max_per_tick']) if limit is None else limit
            batch = todo[:limit]
            if not batch:
                self.logger.info("glance_only: nothing new")
                return counts
            self.logger.info(f"glance_only: {len(todo)} pending, taking {len(batch)}")
            sleep_s = float(self.config['sleep_between_s']) if sleep_s is None else sleep_s
            for i, (video_id, playlist) in enumerate(batch):
                if dry_run:
                    self.logger.info(f"  {video_id}  summarize + push  "
                                     f"[{playlist.get('label') or playlist['url']}]")
                    continue
                record = self.process(video_id, playlist)
                if record is None:
                    counts['failed'] += 1
                else:
                    counts['summarized'] += 1
                    if self.pusher.push_video(record):
                        counts['pushed'] += 1
                if i < len(batch) - 1 and sleep_s > 0:
                    time.sleep(sleep_s)
        except Exception as e:
            self.logger.error(f"glance_only: pass failed: {e}", exc_info=True)
        self.logger.info(f"glance_only: pass done {counts}")
        return counts

    # ------------------------------------------------------------------

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, path)

    def _read_json(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None
        except Exception as e:
            self.logger.error(f"glance_only: failed to read {path}: {e}")
            return None
