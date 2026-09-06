#!/usr/bin/env python3
"""
Playlist Manager
Handles playlist caching, queue management, and missing video detection.
"""

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def yt_dlp_auth_args(options: Dict[str, Any]) -> List[str]:
    """The cookie/extractor arguments every yt-dlp call here carries, read from
    config's `yt_dlp_options` — one home for the rule the download lane spells
    out inline in downloader.py (T-314 added a third caller and stopped there).

    Default is Chrome's macOS profile, exactly as the download lane defaults.
    """
    args: List[str] = []
    cookies_browser = options.get('cookies_from_browser')
    cookies_path = options.get('cookies_path') or options.get('cookies_from_browser_path')
    if cookies_browser:
        if cookies_path:
            args.extend(['--cookies-from-browser', f'{cookies_browser}:{cookies_path}'])
        else:
            args.extend(['--cookies-from-browser', cookies_browser])
    else:
        default_chrome_path = str(Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome')
        args.extend(['--cookies-from-browser', f'chrome:{default_chrome_path}'])
    if options.get('extractor_args'):
        args.extend(['--extractor-args', options['extractor_args']])
    return args


class PlaylistManager:
    """Manages playlist caching and download queue."""

    def __init__(
        self,
        playlist_url: str,
        cache_file: str = ".playlist_cache.txt",
        archive_file: str = ".download_archive.txt",
        queue_file: str = ".download_queue.txt",
        cookies_browser: Optional[str] = None,
        cookies_path: Optional[str] = None,
        extractor_args: Optional[str] = None,
        fetch_timeout_seconds: int = 300
    ):
        """
        Initialize the playlist manager.

        Args:
            playlist_url: YouTube playlist URL
            cache_file: Path to playlist cache file
            archive_file: Path to download archive file
            queue_file: Path to download queue file
            cookies_browser: Browser to extract cookies from
            cookies_path: Path to browser cookies
            extractor_args: yt-dlp extractor arguments
            fetch_timeout_seconds: Hard timeout for a single playlist fetch
        """
        self.playlist_url = playlist_url
        self.cache_file = Path(cache_file)
        self.archive_file = Path(archive_file)
        self.queue_file = Path(queue_file)
        self.cookies_browser = cookies_browser
        self.cookies_path = cookies_path
        self.extractor_args = extractor_args
        self.fetch_timeout_seconds = fetch_timeout_seconds
        self.logger = logging.getLogger('PlaylistManager')

    def _build_base_command(self) -> List[str]:
        """Build base yt-dlp command with authentication."""
        cmd = ['yt-dlp']

        # Add cookies
        if self.cookies_browser:
            if self.cookies_path:
                cmd.extend(['--cookies-from-browser', f'{self.cookies_browser}:{self.cookies_path}'])
            else:
                cmd.extend(['--cookies-from-browser', self.cookies_browser])
        else:
            # Default: use Chrome on macOS
            default_chrome_path = str(Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome')
            cmd.extend(['--cookies-from-browser', f'chrome:{default_chrome_path}'])

        # Add extractor arguments
        if self.extractor_args:
            cmd.extend(['--extractor-args', self.extractor_args])

        return cmd

    def fetch_playlist(self) -> List[str]:
        """
        Fetch the complete list of video IDs from the playlist.

        Returns:
            List of video IDs
        """
        try:
            self.logger.info(f"Fetching playlist: {self.playlist_url}")

            cmd = self._build_base_command()
            cmd.extend([
                '--flat-playlist',
                '--get-id',
                self.playlist_url
            ])

            self.logger.debug(f"Playlist fetch command: {' '.join(cmd)}")

            started = time.monotonic()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.fetch_timeout_seconds
            )
            elapsed = time.monotonic() - started

            if result.returncode == 0:
                video_ids = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
                self.logger.info(
                    f"Found {len(video_ids)} videos in playlist in {elapsed:.1f}s"
                )
                return video_ids
            else:
                self.logger.error(
                    f"Failed to fetch playlist after {elapsed:.1f}s "
                    f"(exit code {result.returncode})"
                )
                stderr = (result.stderr or '').strip()
                if stderr:
                    self.logger.error(f"Playlist fetch stderr:\n{stderr[-2000:]}")
                return []

        except subprocess.TimeoutExpired:
            self.logger.error(
                f"Playlist fetch timed out after {self.fetch_timeout_seconds}s. "
                f"YouTube may be throttling this account; consider raising "
                f"'playlist_fetch_timeout_seconds' in config.json."
            )
            return []
        except Exception as e:
            self.logger.error(f"Error fetching playlist: {e}", exc_info=True)
            return []

    def save_playlist_cache(self, video_ids: List[str]) -> bool:
        """
        Save video IDs to cache file.

        Args:
            video_ids: List of video IDs to cache

        Returns:
            True if successful
        """
        try:
            with open(self.cache_file, 'w') as f:
                f.write('\n'.join(video_ids) + '\n')
            self.logger.info(f"Saved {len(video_ids)} video IDs to {self.cache_file}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save playlist cache: {e}")
            return False

    def load_playlist_cache(self) -> List[str]:
        """
        Load video IDs from cache file.

        Returns:
            List of cached video IDs
        """
        try:
            if not self.cache_file.exists():
                self.logger.warning(f"Playlist cache not found: {self.cache_file}")
                return []

            with open(self.cache_file, 'r') as f:
                video_ids = [line.strip() for line in f if line.strip()]
            self.logger.info(f"Loaded {len(video_ids)} video IDs from cache")
            return video_ids
        except Exception as e:
            self.logger.error(f"Failed to load playlist cache: {e}")
            return []

    def load_download_archive(self) -> Set[str]:
        """
        Load downloaded video IDs from archive file.

        Returns:
            Set of downloaded video IDs
        """
        try:
            if not self.archive_file.exists():
                self.logger.info("Download archive not found (no videos downloaded yet)")
                return set()

            downloaded = set()
            with open(self.archive_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        # Format: "youtube VIDEO_ID" or just "VIDEO_ID"
                        parts = line.split()
                        video_id = parts[-1]  # Get the last part (video ID)
                        downloaded.add(video_id)

            self.logger.info(f"Loaded {len(downloaded)} downloaded video IDs from archive")
            return downloaded
        except Exception as e:
            self.logger.error(f"Failed to load download archive: {e}")
            return set()

    def find_missing_videos(self) -> List[str]:
        """
        Find videos in playlist that haven't been downloaded.

        Returns:
            List of video IDs that need downloading
        """
        cached_videos = self.load_playlist_cache()
        downloaded_videos = self.load_download_archive()

        if not cached_videos:
            self.logger.warning("No cached playlist found. Run refresh_cache() first.")
            return []

        missing = [vid for vid in cached_videos if vid not in downloaded_videos]
        self.logger.info(f"Found {len(missing)} missing videos (out of {len(cached_videos)} total)")
        return missing

    def save_download_queue(self, video_ids: List[str]) -> bool:
        """
        Save download queue to file.

        Args:
            video_ids: List of video IDs to queue

        Returns:
            True if successful
        """
        try:
            with open(self.queue_file, 'w') as f:
                f.write('\n'.join(video_ids) + '\n')
            self.logger.info(f"Saved {len(video_ids)} video IDs to download queue")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save download queue: {e}")
            return False

    def load_download_queue(self) -> List[str]:
        """
        Load download queue from file.

        Returns:
            List of video IDs to download
        """
        try:
            if not self.queue_file.exists():
                self.logger.info("Download queue not found")
                return []

            with open(self.queue_file, 'r') as f:
                video_ids = [line.strip() for line in f if line.strip()]
            self.logger.info(f"Loaded {len(video_ids)} video IDs from download queue")
            return video_ids
        except Exception as e:
            self.logger.error(f"Failed to load download queue: {e}")
            return []

    def remove_from_queue(self, video_id: str) -> bool:
        """
        Remove a video ID from the download queue.

        Args:
            video_id: Video ID to remove

        Returns:
            True if successful
        """
        try:
            queue = self.load_download_queue()
            if video_id in queue:
                queue.remove(video_id)
                self.save_download_queue(queue)
                self.logger.info(f"Removed {video_id} from download queue ({len(queue)} remaining)")
                return True
            else:
                self.logger.warning(f"Video {video_id} not found in queue")
                return False
        except Exception as e:
            self.logger.error(f"Failed to remove from queue: {e}")
            return False

    def get_next_video(self) -> Optional[str]:
        """
        Get the next video ID from the queue without removing it.

        Returns:
            Video ID or None if queue is empty
        """
        queue = self.load_download_queue()
        return queue[0] if queue else None

    def refresh_cache_and_queue(self) -> bool:
        """
        Refresh playlist cache and rebuild download queue.

        Returns:
            True if successful
        """
        self.logger.info("=" * 60)
        self.logger.info("Refreshing playlist cache and download queue")

        # Fetch playlist
        video_ids = self.fetch_playlist()
        if not video_ids:
            self.logger.error("Failed to fetch playlist")
            return False

        # Save cache
        if not self.save_playlist_cache(video_ids):
            return False

        # Find missing videos
        missing = self.find_missing_videos()

        # Save queue
        if not self.save_download_queue(missing):
            return False

        self.logger.info(f"Cache refresh complete: {len(missing)} videos queued for download")
        self.logger.info("=" * 60)
        return True

    def get_queue_status(self) -> dict:
        """
        Get current status of playlist and queue.

        Returns:
            Dictionary with status information
        """
        cached = self.load_playlist_cache()
        downloaded = self.load_download_archive()
        queue = self.load_download_queue()

        return {
            'total_videos': len(cached),
            'downloaded': len(downloaded),
            'pending': len(queue),
            'cache_exists': self.cache_file.exists(),
            'queue_exists': self.queue_file.exists(),
            'archive_exists': self.archive_file.exists()
        }


def main():
    """Test the playlist manager."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python playlist_manager.py <playlist_url>")
        sys.exit(1)

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    playlist_url = sys.argv[1]
    manager = PlaylistManager(playlist_url)

    # Refresh cache and queue
    if manager.refresh_cache_and_queue():
        # Show status
        status = manager.get_queue_status()
        print("\nPlaylist Status:")
        print(f"  Total videos: {status['total_videos']}")
        print(f"  Downloaded: {status['downloaded']}")
        print(f"  Pending: {status['pending']}")
        print(f"\nNext video to download: {manager.get_next_video()}")
    else:
        print("Failed to refresh cache")
        sys.exit(1)


if __name__ == "__main__":
    main()
