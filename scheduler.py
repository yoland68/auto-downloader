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

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = logging.getLogger('DownloadScheduler')

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info(f"\nReceived signal {signum}. Shutting down gracefully...")
        self.running = False

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

            self.downloader.download()

            duration = time.time() - start_time
            self.logger.info(f"Check completed in {duration:.1f} seconds")

        except Exception as e:
            self.logger.error(f"Error in download job: {e}", exc_info=True)
        finally:
            self.is_downloading = False
            self.download_lock.release()

    def run(self):
        """Start the scheduler and run continuously."""
        self.logger.info("=" * 70)
        self.logger.info("YouTube Playlist Auto-Downloader - Scheduler Started")
        self.logger.info("=" * 70)
        self.logger.info(f"Monitoring playlist: {self.downloader.config.get('playlist_url')}")
        self.logger.info(f"Download path: {Path(self.downloader.config.get('download_path')).absolute()}")
        self.logger.info(f"Check interval: {self.downloader.config.get('check_interval_seconds', 60)} seconds")
        self.logger.info(f"Archive file: {self.downloader.config.get('archive_file')}")
        self.logger.info("=" * 70)
        self.logger.info("Press Ctrl+C to stop")
        self.logger.info("")

        # Get check interval from config
        check_interval = self.downloader.config.get('check_interval_seconds', 60)

        # Schedule the download job
        schedule.every(check_interval).seconds.do(self.download_job)

        # Run the first check immediately
        self.logger.info("Running initial check...")
        self.download_job()

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
