#!/usr/bin/env python3
"""
Push summarized-video records to glance's Supabase signal table.

One row per video, upserted on video_id into `public.youtube_videos` via
PostgREST with the service-role key. The glance hub on the other side polls
that table and turns rows into deck cards.

Credentials come from the environment only (never config.json):
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

Push failures never fail a download: the video id is recorded in a retry
list (.glance_push_failed.txt) and re-pushed by `summarize_backfill.py
--retry-failed`. The file is a retry list, not an archive — upsert
idempotency makes re-pushing already-pushed rows harmless.
"""

import logging
import os
from typing import Any, Callable, Dict, Optional, Set, Tuple

DEFAULTS = {
    "glance_push": False,
    "glance_table": "youtube_videos",
    "push_failed_file": ".glance_push_failed.txt",
}


class GlancePusher:
    """Upserts video records into the glance Supabase table."""

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger('GlancePusher')
        cfg = dict(DEFAULTS)
        cfg.update(config.get('summarize', {}) or {})
        self.table = cfg['glance_table']
        self.failed_file = cfg['push_failed_file']

        self.supabase_url = (os.environ.get('SUPABASE_URL') or '').rstrip('/')
        self.service_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or ''

        self.enabled = bool(cfg.get('glance_push'))
        if not self.enabled:
            self.logger.info("Glance push disabled (summarize.glance_push is false)")
            return
        for var, value in (('SUPABASE_URL', self.supabase_url),
                           ('SUPABASE_SERVICE_ROLE_KEY', self.service_key)):
            if not value:
                self.enabled = False
                self.logger.warning(f"Glance push disabled: {var} not set")
                return
        self.logger.info(f"Glance push enabled: {self.supabase_url}/rest/v1/{self.table}")

    # ------------------------------------------------------------------

    def push_video(self, record: Dict[str, Any]) -> bool:
        """Upsert one record. Never raises — a Supabase outage must not
        fail a download. Failure records the id for the retry sweep."""
        if not self.enabled or not record:
            return False
        video_id = record.get('video_id', '?')
        try:
            import requests  # lazy import; optional dependency
            res = requests.post(
                f"{self.supabase_url}/rest/v1/{self.table}",
                headers={
                    'apikey': self.service_key,
                    'Authorization': f'Bearer {self.service_key}',
                    'Content-Type': 'application/json',
                    'Prefer': 'resolution=merge-duplicates,return=minimal',
                },
                json=record,
                timeout=30,
            )
            if 200 <= res.status_code < 300:
                self.logger.info(f"glance_push: upserted {video_id}")
                self._remove_failed(video_id)
                return True
            self.logger.error(
                f"glance_push: HTTP {res.status_code} for {video_id}: "
                f"{res.text[:300]}")
        except Exception as e:
            self.logger.error(f"glance_push: failed for {video_id}: {e}")
        self._record_failed(video_id)
        return False

    def retry_failed(self, build_record: Callable[[str], Optional[Dict[str, Any]]]
                     ) -> Tuple[int, int]:
        """Re-push every id in the retry list. Returns (pushed, still_failed)."""
        failed = self._load_failed()
        if not failed:
            return 0, 0
        pushed = 0
        for video_id in sorted(failed):
            record = build_record(video_id)
            if record and self.push_video(record):
                pushed += 1
        remaining = self._load_failed()
        return pushed, len(remaining)

    # ------------------------------------------------------------------

    def _load_failed(self) -> Set[str]:
        try:
            with open(self.failed_file, 'r') as f:
                return {line.strip() for line in f if line.strip()}
        except FileNotFoundError:
            return set()
        except Exception as e:
            self.logger.warning(f"glance_push: could not read {self.failed_file}: {e}")
            return set()

    def _save_failed(self, ids: Set[str]):
        try:
            with open(self.failed_file, 'w') as f:
                for video_id in sorted(ids):
                    f.write(video_id + '\n')
        except Exception as e:
            self.logger.warning(f"glance_push: could not write {self.failed_file}: {e}")

    def _record_failed(self, video_id: str):
        ids = self._load_failed()
        if video_id not in ids:
            ids.add(video_id)
            self._save_failed(ids)

    def _remove_failed(self, video_id: str):
        ids = self._load_failed()
        if video_id in ids:
            ids.discard(video_id)
            self._save_failed(ids)
