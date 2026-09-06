#!/usr/bin/env python3
"""
Playlist Download Scheduler
Continuously monitors and downloads new videos from a YouTube playlist.
"""

import time
import signal
import sys
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock

import schedule

from downloader import PlaylistDownloader
from glance_only import GlanceOnlyIngester


class DownloadScheduler:
    """Manages scheduled playlist downloads."""

    def __init__(self, config_path: str = "config.json"):
        """
        Initialize the scheduler.

        Args:
            config_path: Path to the configuration file
        """
        self.config_path = config_path
        self.downloader = PlaylistDownloader(config_path)
        self.running = True
        self.check_count = 0
        self.download_lock = Lock()  # Prevent concurrent downloads
        self.is_downloading = False
        self.skipped_checks = 0
        self.last_download_time = 0  # Track when last download occurred
        self.videos_downloaded = 0  # Count successful downloads
        self.rate_limit_skips = 0  # Count checks skipped due to rate limit
        self.last_refresh_time = 0  # When the playlist cache was last refreshed
        self.consecutive_refresh_failures = 0  # Drives exponential backoff
        self.next_refresh_allowed = 0  # Epoch seconds; set while backing off

        # T-314: the glance-only lane shares the downloader's summarizer and
        # pusher (one Gemini client, one retry file) but runs as its own job,
        # outside the download rate limit — see glance_only.py's docstring.
        self.glance_only = GlanceOnlyIngester(
            self.downloader.config, self.downloader.summarizer,
            self.downloader.glance_pusher, logger=self.logger)
        self.glance_only_passes = 0

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = logging.getLogger('DownloadScheduler')

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info(f"\nReceived signal {signum}. Shutting down gracefully...")
        self.running = False

    def _check_rate_limit(self) -> bool:
        """
        Check if enough time has passed since last download.

        Returns:
            True if download is allowed, False if rate limited
        """
        download_interval_hours = self.downloader.config.get('download_interval_hours', 1)

        # If set to 0, disable rate limiting (original behavior)
        if download_interval_hours == 0:
            return True

        download_interval_seconds = download_interval_hours * 3600
        current_time = time.time()
        time_since_last_download = current_time - self.last_download_time

        if time_since_last_download >= download_interval_seconds:
            return True
        else:
            time_remaining = download_interval_seconds - time_since_last_download
            hours = int(time_remaining // 3600)
            minutes = int((time_remaining % 3600) // 60)
            seconds = int(time_remaining % 60)
            self.logger.info(
                f"Rate limit: Next download available in {hours:02d}:{minutes:02d}:{seconds:02d}"
            )
            return False

    def _refresh_interval_seconds(self) -> float:
        """Base interval between playlist refreshes, in seconds."""
        hours = self.downloader.config.get('playlist_refresh_interval_hours', 1)
        return float(hours) * 3600

    def _should_refresh_playlist(self) -> bool:
        """
        Decide whether to re-fetch the playlist.

        An empty queue used to trigger a full playlist fetch on every check
        (once a minute), which is what got this account throttled by YouTube.
        Refreshes are now spaced by playlist_refresh_interval_hours, and backed
        off further after consecutive failures.

        Returns:
            True if a refresh should run now
        """
        now = time.time()

        if now < self.next_refresh_allowed:
            remaining = int(self.next_refresh_allowed - now)
            self.logger.debug(
                f"Playlist refresh backing off after "
                f"{self.consecutive_refresh_failures} failure(s); "
                f"retrying in {remaining // 60:02d}:{remaining % 60:02d}"
            )
            return False

        interval_seconds = self._refresh_interval_seconds()
        if interval_seconds <= 0:
            return True

        elapsed = now - self.last_refresh_time
        if elapsed >= interval_seconds:
            return True

        remaining = int(interval_seconds - elapsed)
        self.logger.debug(
            f"Playlist refresh not due for "
            f"{remaining // 3600:02d}:{(remaining % 3600) // 60:02d}:{remaining % 60:02d}"
        )
        return False

    def _record_refresh_result(self, success: bool):
        """
        Record the outcome of a refresh and schedule the next attempt.

        On failure the delay doubles per consecutive failure, capped by
        playlist_refresh_backoff_max_hours, so a throttled or broken fetch
        stops hammering YouTube every check.
        """
        now = time.time()
        self.last_refresh_time = now

        if success:
            if self.consecutive_refresh_failures:
                self.logger.info(
                    f"Playlist refresh recovered after "
                    f"{self.consecutive_refresh_failures} consecutive failure(s)"
                )
            self.consecutive_refresh_failures = 0
            self.next_refresh_allowed = 0
            return

        self.consecutive_refresh_failures += 1

        # Floor the base so backoff still applies when refreshing is unthrottled.
        base = max(self._refresh_interval_seconds(), 300)
        max_backoff = float(
            self.downloader.config.get('playlist_refresh_backoff_max_hours', 6)
        ) * 3600
        delay = min(base * (2 ** (self.consecutive_refresh_failures - 1)), max_backoff)
        self.next_refresh_allowed = now + delay

        self.logger.error(
            f"Playlist refresh failed {self.consecutive_refresh_failures} time(s) "
            f"in a row; next attempt in {int(delay) // 3600:02d}:"
            f"{(int(delay) % 3600) // 60:02d}:{int(delay) % 60:02d}"
        )

    def download_job(self):
        """Job function that gets executed on schedule."""
        self.check_count += 1

        # Try to acquire the lock without blocking
        if not self.download_lock.acquire(blocking=False):
            self.skipped_checks += 1
            self.logger.warning(
                f"Check #{self.check_count} - SKIPPED (previous download still in progress) "
                f"- Total skipped: {self.skipped_checks}"
            )
            return

        try:
            self.is_downloading = True
            start_time = time.time()
            self.logger.info(
                f"Check #{self.check_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # Check rate limit
            if not self._check_rate_limit():
                self.rate_limit_skips += 1
                self.logger.info(f"Check #{self.check_count} - SKIPPED (rate limit)")
                return

            # Check if playlist manager is available
            if not self.downloader.playlist_manager:
                self.logger.error("Playlist manager not initialized. Using legacy download mode.")
                self.downloader.download()
                duration = time.time() - start_time
                self.logger.info(f"Check completed in {duration:.1f} seconds")
                return

            # Get next video from queue
            next_video = self.downloader.playlist_manager.get_next_video()

            if not next_video:
                # Gate the refresh: an empty queue must not re-fetch the whole
                # playlist on every check.
                if not self._should_refresh_playlist():
                    return

                self.logger.info("Download queue is empty. Checking for new videos...")

                # Refresh cache and queue to detect new videos
                refreshed = self.downloader.playlist_manager.refresh_cache_and_queue()
                self._record_refresh_result(refreshed)

                if refreshed:
                    next_video = self.downloader.playlist_manager.get_next_video()

                    if not next_video:
                        self.logger.info("No new videos found in playlist. All caught up!")
                        status = self.downloader.playlist_manager.get_queue_status()
                        self.logger.info(
                            f"Status: {status['downloaded']}/{status['total_videos']} videos downloaded"
                        )
                    else:
                        queue = self.downloader.playlist_manager.load_download_queue()
                        self.logger.info(f"Found {len(queue)} new video(s) in playlist")
                else:
                    self.logger.error("Failed to refresh playlist cache")
                    return

            # Download single video if available
            if next_video:
                queue_length = len(self.downloader.playlist_manager.load_download_queue())
                self.logger.info(f"Downloading video {next_video} ({queue_length} remaining in queue)")

                if self.downloader.download_single_video(next_video):
                    # Remove from queue on success
                    self.downloader.playlist_manager.remove_from_queue(next_video)
                    self.last_download_time = time.time()
                    self.videos_downloaded += 1
                    self.logger.info(f"Total videos downloaded this session: {self.videos_downloaded}")
                else:
                    self.logger.error(f"Failed to download video {next_video}. Will retry on next check.")

            duration = time.time() - start_time
            self.logger.info(f"Check completed in {duration:.1f} seconds")

        except Exception as e:
            self.logger.error(f"Error in download job: {e}", exc_info=True)
        finally:
            self.is_downloading = False
            self.download_lock.release()

    def glance_only_job(self):
        """Scheduled pass of the glance-only lane. `schedule` runs jobs on the
        main thread one at a time, so this never overlaps a download; a long
        download merely delays it to the next tick. Never raises."""
        self.glance_only_passes += 1
        try:
            self.glance_only.run_once()
        except Exception as e:
            self.logger.error(f"Error in glance-only job: {e}", exc_info=True)

    def run(self):
        """Start the scheduler and run continuously."""
        self.logger.info("=" * 70)
        self.logger.info("YouTube Playlist Auto-Downloader - Scheduler Started")
        self.logger.info("=" * 70)
        self.logger.info(f"Monitoring playlist: {self.downloader.config.get('playlist_url')}")
        self.logger.info(f"Download path: {Path(self.downloader.config.get('download_path')).absolute()}")
        self.logger.info(f"Check interval: {self.downloader.config.get('check_interval_seconds', 60)} seconds")

        download_interval_hours = self.downloader.config.get('download_interval_hours', 1)
        if download_interval_hours == 0:
            self.logger.info("Rate limiting: DISABLED (downloads as fast as possible)")
        else:
            self.logger.info(f"Rate limiting: 1 video every {download_interval_hours} hour(s)")

        refresh_hours = self.downloader.config.get('playlist_refresh_interval_hours', 1)
        if refresh_hours == 0:
            self.logger.info("Playlist refresh: every check (NOT recommended)")
        else:
            self.logger.info(f"Playlist refresh: at most once every {refresh_hours} hour(s)")
        self.logger.info(
            f"Playlist fetch timeout: "
            f"{self.downloader.config.get('playlist_fetch_timeout_seconds', 300)}s"
        )

        self.logger.info(f"Archive file: {self.downloader.config.get('archive_file')}")
        self.logger.info(f"Queue file: {self.downloader.config.get('download_queue_file', '.download_queue.txt')}")
        self.logger.info(f"Cache file: {self.downloader.config.get('playlist_cache_file', '.playlist_cache.txt')}")
        self.logger.info("=" * 70)
        self.logger.info("Press Ctrl+C to stop")
        self.logger.info("")

        # Get check interval from config
        check_interval = self.downloader.config.get('check_interval_seconds', 60)

        # Schedule the download job
        schedule.every(check_interval).seconds.do(self.download_job)

        # T-314: the glance-only lane, on its own interval
        if self.glance_only.enabled:
            glance_interval = int(self.glance_only.config.get('check_interval_seconds', 900))
            self.logger.info(f"Glance-only lane: every {glance_interval}s, up to "
                             f"{self.glance_only.config.get('max_per_tick')} video(s) per pass")
            schedule.every(glance_interval).seconds.do(self.glance_only_job)

        # Run the first check immediately
        self.logger.info("Running initial check...")
        self.download_job()
        if self.glance_only.enabled:
            self.glance_only_job()

        # Main scheduler loop
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                time.sleep(5)  # Wait a bit before retrying

        self.logger.info("Scheduler stopped.")
        self.logger.info(f"Total checks performed: {self.check_count}")
        if self.skipped_checks > 0:
            self.logger.info(f"Checks skipped due to long downloads: {self.skipped_checks}")
        if self.rate_limit_skips > 0:
            self.logger.info(f"Checks skipped due to rate limiting: {self.rate_limit_skips}")
        self.logger.info(f"Videos downloaded this session: {self.videos_downloaded}")


def main():
    """Main entry point for the scheduler."""
    import argparse

    parser = argparse.ArgumentParser(
        description='YouTube Playlist Auto-Downloader Scheduler',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Use default config.json
  %(prog)s -c my_config.json  # Use custom config file
        """
    )
    parser.add_argument(
        '-c', '--config',
        default='config.json',
        help='Path to configuration file (default: config.json)'
    )

    args = parser.parse_args()

    # Check if config file exists
    if not Path(args.config).exists():
        print(f"Error: Configuration file '{args.config}' not found.")
        print("\nPlease create a config.json file first.")
        print("See README.md for configuration details.")
        sys.exit(1)

    try:
        scheduler = DownloadScheduler(args.config)
        scheduler.run()
    except KeyboardInterrupt:
        print("\nShutdown requested by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
