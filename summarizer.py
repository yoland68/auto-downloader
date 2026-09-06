#!/usr/bin/env python3
"""
Gemini video summarizer.

Post-download step: generate a Markdown summary for a downloaded video with
the Gemini API, write it as a `.summary.md` sidecar next to the mp4, and
embed it into the mp4's synopsis metadata (the field Plex/Infuse show as
"Summary"). The original YouTube description is preserved in the
`description` tag.

The Gemini call itself never needed the file: URL mode hands Gemini the
YouTube URL, transcript mode hands it caption text. `summarize_info()` is that
file-free core, shared with the glance-only lane (glance_only.py), which
summarizes playlists that are never downloaded. `make_record()` is the shared
row shape for glance's youtube_videos table; the lane is its `ingest_mode`.

Input modes:
  * "url"        — hand Gemini the YouTube URL directly (it ingests the video)
  * "transcript" — feed the already-downloaded .srt/.vtt captions as text
  * "auto"       — URL unless the video is too long or has no public URL;
                   transcript as fallback when URL mode fails

The Gemini API key comes from the GEMINI_API_KEY environment variable only —
never from config.json. If the key or the google-genai package is missing,
the summarizer disables itself cleanly and the downloader keeps working.
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

VIDEO_ID_RE = re.compile(r'\[([A-Za-z0-9_-]{11})\]')

# Summary sidecar header, parsed back by build_record().
_HEADER_RE = re.compile(
    r'<!--\s*video_id:\s*(?P<video_id>\S+)\s*\|\s*model:\s*(?P<model>\S+)'
    r'\s*\|\s*input:\s*(?P<input>\S+)\s*\|\s*generated:\s*(?P<generated>\S+)\s*-->'
)

DEFAULTS = {
    "enabled": False,
    "gemini_model": "gemini-2.5-flash",
    "input_mode": "auto",            # auto | url | transcript
    "url_max_duration_s": 7200,      # above this, auto prefers transcript mode
    "max_output_tokens": 4096,
    "request_timeout_s": 300,
    "max_retries": 3,
    "inject_summary_to_metadata": True,
}


def find_video_file(download_path: Path, video_id: str) -> Optional[Path]:
    """Locate the mp4 for a video id.

    NOTE: rglob(f'*[{video_id}].mp4') is wrong — glob treats [...] as a
    character class, so that pattern matches nothing. Filter by substring.
    """
    for p in sorted(download_path.rglob('*.mp4')):
        if f'[{video_id}]' in p.name:
            return p
    return None


def make_record(video_id: str, info: Dict[str, Any], summary_md: str,
                header: Dict[str, str], default_model: str, *,
                playlist_id: Optional[str], download_path: Optional[str],
                ingest_mode: str) -> Dict[str, Any]:
    """The youtube_videos row, for either lane.

    ingest_mode is 'download' (file on the Plex machine, download_path set)
    or 'glance_only' (summarized from the URL, download_path None). The
    column is NOT NULL with a two-value CHECK on glance's side (migration
    040), so a third value is rejected by the database, not laundered here.
    """
    upload_date = None
    raw_date = info.get('upload_date')  # yt-dlp YYYYMMDD
    if raw_date and re.fullmatch(r'\d{8}', str(raw_date)):
        upload_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    return {
        "video_id": info.get('id') or video_id,
        "playlist_id": playlist_id,
        "title": info.get('title') or video_id,
        "channel": info.get('channel') or info.get('uploader'),
        "url": info.get('webpage_url')
               or f"https://www.youtube.com/watch?v={video_id}",
        "upload_date": upload_date,
        "duration_s": info.get('duration'),
        "description": info.get('description'),
        "summary_md": summary_md,
        "summarized_at": header.get('generated')
                         or datetime.now(timezone.utc).isoformat(),
        "summary_model": header.get('model') or default_model,
        "download_path": download_path,
        "thumbnail": info.get('thumbnail'),
        "ingest_mode": ingest_mode,
        "metadata": {
            "input_mode": header.get('input'),
            "chapters": [
                {"title": c.get('title'), "start_time": c.get('start_time')}
                for c in (info.get('chapters') or [])
            ],
            "tags": (info.get('tags') or [])[:20],
            "view_count": info.get('view_count'),
        },
    }


class VideoSummarizer:
    """Summarizes downloaded videos with Gemini and writes sidecar/metadata."""

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger('VideoSummarizer')
        self.config = dict(DEFAULTS)
        self.config.update(config.get('summarize', {}) or {})
        self.download_path = Path(config.get('download_path', './downloads'))

        self.client = None
        self.enabled = bool(self.config.get('enabled'))
        if not self.enabled:
            self.logger.info("Summarizer disabled (summarize.enabled is false)")
            return
        if not os.environ.get('GEMINI_API_KEY'):
            self.enabled = False
            self.logger.warning("Summarizer disabled: GEMINI_API_KEY not set")
            return
        try:
            from google import genai  # lazy import; optional dependency
            self.client = genai.Client()  # reads GEMINI_API_KEY itself
            self.logger.info(
                f"Summarizer enabled (model: {self.config['gemini_model']})")
        except Exception as e:
            self.enabled = False
            self.logger.warning(f"Summarizer disabled: google-genai unavailable: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summarize_video(self, video_id: str, force: bool = False,
                        mode: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Full post-step for one video.

        Returns the glance record dict on success (also when the summary
        already existed and force is False), or None on skip/failure.
        Never raises.
        """
        try:
            return self._summarize_video(video_id, force=force, mode=mode)
        except Exception as e:
            self.logger.error(f"summarize: unexpected error for {video_id}: {e}")
            return None

    def build_record(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Rebuild the Supabase row from on-disk .info.json + .summary.md."""
        video_path = find_video_file(self.download_path, video_id)
        if not video_path:
            self.logger.warning(f"build_record: no mp4 found for {video_id}")
            return None
        info = self._load_info(video_path)
        summary_path = self._summary_path(video_path)
        summary_md, header = self.read_summary_md(summary_path)
        if summary_md is None:
            self.logger.warning(f"build_record: no summary sidecar for {video_id}")
            return None

        try:
            rel_path = str(video_path.relative_to(self.download_path))
        except ValueError:
            rel_path = str(video_path)

        if not info.get('title'):
            info = {**info, 'title': video_path.stem}
        return make_record(
            video_id, info, summary_md, header, self.config['gemini_model'],
            playlist_id=info.get('playlist_id'), download_path=rel_path,
            ingest_mode='download')

    def bakeoff(self, video_id: str) -> Dict[str, bool]:
        """Run BOTH input modes, writing .summary.url.md / .summary.transcript.md.

        Never writes the real .summary.md, injects metadata, or pushes.
        Returns {mode: succeeded}.
        """
        results = {"url": False, "transcript": False}
        video_path = find_video_file(self.download_path, video_id)
        if not video_path:
            self.logger.warning(f"bakeoff: no mp4 found for {video_id}")
            return results
        info = self._load_info(video_path)
        transcript_path = self._find_transcript(video_id, video_path)

        summary = self._summarize_via_url(info)
        if summary:
            self.write_summary_file(
                Path(str(video_path)[:-len(video_path.suffix)] + '.summary.url.md'),
                video_id, info, summary, 'url')
            results["url"] = True

        if transcript_path:
            text = self._transcript_to_text(transcript_path)
            summary = self._summarize_via_transcript(info, text)
            if summary:
                self.write_summary_file(
                    Path(str(video_path)[:-len(video_path.suffix)]
                         + '.summary.transcript.md'),
                    video_id, info, summary, 'transcript')
                results["transcript"] = True
        else:
            self.logger.info(f"bakeoff: no transcript for {video_id}, "
                             "skipping transcript mode")
        return results

    # ------------------------------------------------------------------
    # Core flow
    # ------------------------------------------------------------------

    def _summarize_video(self, video_id: str, force: bool,
                         mode: Optional[str]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        video_path = find_video_file(self.download_path, video_id)
        if not video_path:
            self.logger.warning(f"summarize: no mp4 found for {video_id}")
            return None

        summary_path = self._summary_path(video_path)
        if summary_path.exists() and not force:
            self.logger.debug(f"summarize: {video_id} already summarized")
            return self.build_record(video_id)

        info = self._load_info(video_path)
        transcript_path = self._find_transcript(video_id, video_path)
        transcript = ((lambda: self._transcript_to_text(transcript_path))
                      if transcript_path else None)
        result = self.summarize_info(info, mode=mode, transcript=transcript,
                                     video_id=video_id)
        if result is None:
            return None
        summary, used_mode = result

        self.write_summary_file(summary_path, video_id, info, summary, used_mode)
        self.logger.info(f"summarize: wrote {summary_path.name} ({used_mode} mode)")

        if self.config.get('inject_summary_to_metadata', True):
            self._inject_summary_metadata(
                video_path, summary, (info.get('description') or '').strip())

        return self.build_record(video_id)

    def summarize_info(self, info: Dict[str, Any], mode: Optional[str] = None,
                       transcript: Optional[Callable[[], Optional[str]]] = None,
                       video_id: str = '?') -> Optional[Tuple[str, str]]:
        """Summarize from metadata alone. Returns (summary_md, used_mode) or None.

        The file-free core both lanes share. `transcript` is a zero-arg
        callable returning caption text (or None), invoked at most once and
        only when transcript mode is actually needed — the download lane pays
        a file read for it, the glance-only lane a yt-dlp round trip, and
        neither should pay when URL mode succeeds. Never raises.
        """
        if not self.enabled:
            return None
        cache: Dict[str, Optional[str]] = {}

        def caption_text() -> Optional[str]:
            if 'text' not in cache:
                try:
                    cache['text'] = transcript() if transcript else None
                except Exception as e:
                    self.logger.error(f"summarize: transcript fetch failed for "
                                      f"{video_id}: {e}")
                    cache['text'] = None
            return cache['text'] or None

        chosen = mode or self.config['input_mode']
        if chosen == 'auto':
            chosen = self._choose_mode(info, has_transcript=transcript is not None)

        if chosen == 'url':
            summary = self._summarize_via_url(info)
            if summary:
                return summary, 'url'
            text = caption_text()
            if text:
                self.logger.info(f"summarize: URL mode failed for {video_id}, "
                                 "falling back to transcript")
                summary = self._summarize_via_transcript(info, text)
                if summary:
                    return summary, 'transcript'
        else:  # transcript
            text = caption_text()
            summary = self._summarize_via_transcript(info, text) if text else None
            if summary:
                return summary, 'transcript'
            self.logger.info(f"summarize: transcript mode unavailable/failed "
                             f"for {video_id}, trying URL mode")
            summary = self._summarize_via_url(info)
            if summary:
                return summary, 'url'

        self.logger.error(f"summarize: both input modes failed for {video_id}")
        return None

    def _choose_mode(self, info: Dict[str, Any], has_transcript: bool) -> str:
        duration = info.get('duration') or 0
        url = info.get('webpage_url')
        if url and duration <= self.config['url_max_duration_s']:
            return 'url'
        if has_transcript:
            return 'transcript'
        return 'url'  # last resort: try URL anyway, accept failure

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    def _summary_path(self, video_path: Path) -> Path:
        return Path(str(video_path)[:-len(video_path.suffix)] + '.summary.md')

    def _load_info(self, video_path: Path) -> Dict[str, Any]:
        info_path = video_path.with_suffix('.info.json')
        if not info_path.exists():
            self.logger.warning(f"summarize: .info.json not found at {info_path}")
            return {}
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"summarize: failed to read {info_path}: {e}")
            return {}

    def _find_transcript(self, video_id: str, video_path: Path) -> Optional[Path]:
        base = str(video_path)[:-len(video_path.suffix)]
        for ext in ('.en.srt', '.en.vtt'):
            candidate = Path(base + ext)
            if candidate.exists():
                return candidate
        # The SRT second pass can't resolve %(playlist_title)s for bare
        # watch?v= URLs, so its files land flat in the download root.
        for p in sorted(self.download_path.rglob('*.srt')):
            if f'[{video_id}]' in p.name:
                return p
        for p in sorted(self.download_path.rglob('*.vtt')):
            if f'[{video_id}]' in p.name:
                return p
        return None

    def _transcript_to_text(self, path: Path) -> str:
        """Strip srt/vtt cue machinery and collapse auto-caption repeats."""
        try:
            raw = path.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            self.logger.error(f"summarize: failed to read transcript {path}: {e}")
            return ''
        lines: List[str] = []
        prev = None
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.isdigit():
                continue
            if line.startswith(('WEBVTT', 'Kind:', 'Language:', 'NOTE')):
                continue
            if '-->' in line:
                continue
            # strip inline cue tags like <c> and <00:00:01.000>
            line = re.sub(r'<[^>]+>', '', line).strip()
            if not line or line == prev:
                continue  # auto-caption rolling window repeats lines
            lines.append(line)
            prev = line
        text = '\n'.join(lines)
        return text[:800_000]  # safety valve; flash has a 1M-token context

    # ------------------------------------------------------------------
    # Gemini
    # ------------------------------------------------------------------

    def _prompt(self, info: Dict[str, Any], transcript_text: Optional[str] = None) -> str:
        duration = info.get('duration')
        if duration:
            h, rem = divmod(int(duration), 3600)
            m, s = divmod(rem, 60)
            duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        else:
            duration_str = "unknown"

        chapters = info.get('chapters') or []
        chapter_lines = '\n'.join(
            f"  - [{int(c.get('start_time') or 0)}s] {c.get('title')}"
            for c in chapters) or "  (none)"

        description = (info.get('description') or '').strip()[:4000]

        parts = [
            "You are summarizing a YouTube video for a personal media library.",
            "",
            "VIDEO METADATA",
            f"Title: {info.get('title')} | Channel: "
            f"{info.get('channel') or info.get('uploader')} | "
            f"Uploaded: {info.get('upload_date')} | Duration: {duration_str}",
            f"Chapters:\n{chapter_lines}",
            "Description (may contain sponsor/link noise — use judiciously):",
            description or "(none)",
        ]
        if transcript_text is not None:
            parts += [
                "",
                "TRANSCRIPT (auto-generated captions; may contain ASR errors):",
                transcript_text,
            ]
        parts += [
            "",
            "Write a Markdown summary:",
            "1. One-line TL;DR as the very first line "
            "(media apps truncate long summaries).",
            '2. "Key points": 4-8 bullets of the actual arguments/results, '
            "not topics.",
            '3. "Outline": per-chapter one-liners if chapters exist, else skip.',
            '4. "Notable quotes": up to 3, only if genuinely notable.',
            "Be concrete and information-dense. No preamble, no meta-commentary.",
        ]
        return '\n'.join(parts)

    def _summarize_via_url(self, info: Dict[str, Any]) -> Optional[str]:
        url = info.get('webpage_url')
        if not url:
            return None
        try:
            from google.genai import types
        except Exception:
            return None
        contents = types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=url)),
            types.Part(text=self._prompt(info)),
        ])
        return self._call_gemini(contents)

    def _summarize_via_transcript(self, info: Dict[str, Any],
                                  transcript_text: str) -> Optional[str]:
        if not transcript_text:
            return None
        return self._call_gemini(self._prompt(info, transcript_text))

    def _call_gemini(self, contents: Any) -> Optional[str]:
        if not self.client:
            return None
        try:
            from google.genai import types, errors
        except Exception:
            return None

        max_retries = int(self.config['max_retries'])
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.config['gemini_model'],
                    contents=contents,
                    config=types.GenerateContentConfig(
                        max_output_tokens=int(self.config['max_output_tokens']),
                        http_options=types.HttpOptions(
                            timeout=int(self.config['request_timeout_s']) * 1000),
                    ),
                )
                text = (response.text or '').strip()
                if text:
                    return text
                self.logger.warning("summarize: Gemini returned empty response")
                return None
            except errors.APIError as e:
                if getattr(e, 'code', None) in (429, 503) and attempt < max_retries - 1:
                    delay = min(2 ** attempt * 15, 120)
                    self.logger.warning(
                        f"summarize: Gemini {e.code}, retrying in {delay}s "
                        f"(attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                self.logger.error(f"summarize: Gemini API error: {e}")
                return None
            except Exception as e:
                self.logger.error(f"summarize: Gemini call failed: {e}")
                return None
        return None

    # ------------------------------------------------------------------
    # Outputs
    # ------------------------------------------------------------------

    def write_summary_file(self, path: Path, video_id: str,
                            info: Dict[str, Any], summary: str, mode: str):
        generated = datetime.now(timezone.utc).isoformat()
        model = self.config['gemini_model']
        content = (
            f"<!-- video_id: {video_id} | model: {model} | input: {mode} "
            f"| generated: {generated} -->\n"
            f"# {info.get('title') or video_id}\n\n"
            f"{summary}\n"
        )
        tmp_path = path.with_name(path.name + '.tmp')
        tmp_path.write_text(content, encoding='utf-8')
        os.replace(tmp_path, path)

    def read_summary_md(self, path: Path):
        """Return (summary body, header dict) or (None, {}) if absent."""
        if not path.exists():
            return None, {}
        try:
            content = path.read_text(encoding='utf-8')
        except Exception as e:
            self.logger.error(f"summarize: failed to read {path}: {e}")
            return None, {}
        header = {}
        m = _HEADER_RE.search(content)
        if m:
            header = {'model': m.group('model'), 'input': m.group('input'),
                      'generated': m.group('generated')}
            content = content[m.end():]
        # Drop the "# {title}" heading we wrote; keep the body.
        body = re.sub(r'^\s*#[^\n]*\n', '', content.lstrip('\n'), count=1).strip()
        return body, header

    def _inject_summary_metadata(self, video_path: Path, summary: str,
                                 description: str) -> bool:
        """Embed summary -> synopsis and original description -> description.

        Same ffmpeg stream-copy/tempfile/os.replace discipline as
        _inject_description_to_metadata in downloader.py.
        """
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                suffix='.mp4', dir=video_path.parent, prefix='.tmp_')
            os.close(tmp_fd)

            cmd = ['ffmpeg', '-y', '-i', str(video_path),
                   '-metadata', f'synopsis={summary}']
            if description:
                cmd.extend(['-metadata', f'description={description}'])
            cmd.extend(['-c', 'copy', tmp_path])

            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=120)
            if result.returncode != 0:
                self.logger.error(
                    f"summarize: ffmpeg inject failed for {video_path.name}: "
                    f"{result.stderr[-500:]}")
                Path(tmp_path).unlink(missing_ok=True)
                return False

            os.replace(tmp_path, video_path)
            self.logger.info(
                f"summarize: embedded summary into {video_path.name}")
            return True
        except Exception as e:
            self.logger.error(
                f"summarize: metadata inject error for {video_path.name}: {e}")
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
            return False
