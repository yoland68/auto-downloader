#!/usr/bin/env python3
"""
Backfill / bake-off / retry CLI for the Gemini video summarizer.

Walks the downloads directory, finds every video (mp4 whose name carries an
11-char [VIDEOID]), summarizes any video lacking a .summary.md sidecar, and
pushes the records to glance's Supabase table.

The completion marker is the .summary.md sidecar itself — the summary is the
artifact, so its presence is ground truth and cannot desync from a separate
state file. Only push failures get a state file (.glance_push_failed.txt).

Usage examples:
  python3 summarize_backfill.py --dry-run
  python3 summarize_backfill.py --bakeoff --video R13BD8qKeTg
  python3 summarize_backfill.py --sleep 15 --limit 200
  python3 summarize_backfill.py --push-only
  python3 summarize_backfill.py --retry-failed
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict

from summarizer import VideoSummarizer, VIDEO_ID_RE
from glance_push import GlancePusher


def setup_logging() -> logging.Logger:
    logger = logging.getLogger('SummarizeBackfill')
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(handler)
    return logger


def find_videos(download_path: Path) -> Dict[str, Path]:
    """Map video_id -> mp4 path for every downloaded video."""
    videos: Dict[str, Path] = {}
    for p in sorted(download_path.rglob('*.mp4')):
        m = VIDEO_ID_RE.search(p.name)
        if m:
            videos.setdefault(m.group(1), p)
    return videos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-c', '--config', default='config.json')
    parser.add_argument('--video', action='append', default=[],
                        help='Only these video ids (repeatable)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Stop after N new summaries (API budget guard)')
    parser.add_argument('--force', action='store_true',
                        help='Re-summarize even if .summary.md exists')
    parser.add_argument('--mode', choices=['auto', 'url', 'transcript'],
                        default=None, help='Override summarize.input_mode')
    parser.add_argument('--bakeoff', action='store_true',
                        help='Run BOTH modes; write .summary.url.md and '
                             '.summary.transcript.md; no real sidecar, '
                             'metadata inject, or push')
    parser.add_argument('--push-only', action='store_true',
                        help='No Gemini calls; build+push records for every '
                             'video that already has a .summary.md')
    parser.add_argument('--retry-failed', action='store_true',
                        help='Only re-push ids from the failed-push list')
    parser.add_argument('--sleep', type=float, default=15,
                        help='Seconds between Gemini calls (default 15)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    logger = setup_logging()

    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config {args.config}: {e}")
        return 1

    # Force-enable the summarizer for explicit CLI runs (still requires
    # GEMINI_API_KEY + the SDK); config's `enabled` gates the downloader hook.
    config.setdefault('summarize', {})
    if not args.push_only and not args.retry_failed:
        config['summarize']['enabled'] = True

    summarizer = VideoSummarizer(config, logger=logger)
    pusher = GlancePusher(config, logger=logger)
    download_path = Path(config.get('download_path', './downloads'))

    if args.retry_failed:
        pushed, still_failed = pusher.retry_failed(summarizer.build_record)
        logger.info(f"retry: pushed {pushed}, still failed {still_failed}")
        return 0 if still_failed == 0 else 1

    videos = find_videos(download_path)
    if args.video:
        missing = [v for v in args.video if v not in videos]
        for v in missing:
            logger.warning(f"video {v} not found under {download_path}")
        videos = {v: videos[v] for v in args.video if v in videos}

    logger.info(f"Found {len(videos)} video(s)")

    if args.dry_run:
        for video_id, path in videos.items():
            summary_exists = summarizer._summary_path(path).exists()
            action = 'skip (summarized)' if summary_exists and not args.force \
                     else 'summarize + push'
            if args.push_only:
                action = 'push' if summary_exists else 'skip (no summary)'
            logger.info(f"  {video_id}  {action}  {path.name}")
        return 0

    if args.bakeoff:
        for video_id in videos:
            logger.info(f"bakeoff: {video_id}")
            results = summarizer.bakeoff(video_id)
            logger.info(f"bakeoff: {video_id} -> {results}")
            time.sleep(args.sleep)
        return 0

    summarized = skipped = failed = pushed = 0
    for video_id, path in videos.items():
        already = summarizer._summary_path(path).exists()

        if args.push_only:
            if not already:
                skipped += 1
                continue
            record = summarizer.build_record(video_id)
            if record and pusher.push_video(record):
                pushed += 1
            else:
                failed += 1
            continue

        if already and not args.force:
            skipped += 1
            record = summarizer.build_record(video_id)
            if record and pusher.enabled:
                if pusher.push_video(record):
                    pushed += 1
            continue

        if args.limit is not None and summarized >= args.limit:
            logger.info(f"--limit {args.limit} reached, stopping")
            break

        record = summarizer.summarize_video(video_id, force=args.force,
                                            mode=args.mode)
        if record is None:
            failed += 1
            continue
        summarized += 1
        if pusher.enabled and pusher.push_video(record):
            pushed += 1
        time.sleep(args.sleep)

    logger.info(f"Done: summarized={summarized} skipped={skipped} "
                f"failed={failed} pushed={pushed}")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
