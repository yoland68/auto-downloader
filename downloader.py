#!/usr/bin/env python3
"""
YouTube Playlist Auto-Downloader
This module handles downloading videos from a YouTube playlist using yt-dlp.
"""

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

from subtitle_syncer import SubtitleSyncer


class PlaylistDownloader:
    """Manages downloading videos from YouTube playlists."""

    def __init__(self, config_path: str = "config.json"):
        """
        Initialize the downloader with configuration.

        Args:
            config_path: Path to the configuration file
        """
        self.config_path = config_path
        self.config = self._load_config()
        self._setup_logging()
        self._setup_directories()
        self._setup_subtitle_sync()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Error: Configuration file '{self.config_path}' not found.")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in configuration file: {e}")
            sys.exit(1)

    def _setup_logging(self):
        """Configure logging system."""
        log_file = self.config.get('log_file', 'downloader.log')

        # Create logger
        self.logger = logging.getLogger('PlaylistDownloader')
        self.logger.setLevel(logging.INFO)

        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def _setup_directories(self):
        """Create necessary directories if they don't exist."""
        download_path = Path(self.config.get('download_path', './downloads'))
        download_path.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Download directory: {download_path.absolute()}")

    def _setup_subtitle_sync(self):
        """Setup Google Drive subtitle syncing if enabled."""
        self.subtitle_syncer = None
        sync_config = self.config.get('google_drive_sync', {})

        if sync_config.get('enabled', False):
            try:
                self.subtitle_syncer = SubtitleSyncer(
                    sync_folder=sync_config['sync_folder'],
                    archive_file=sync_config.get('sync_archive', '.subtitle_sync_archive.txt'),
                    download_path=self.config.get('download_path', './downloads')
                )
                self.logger.info(f"Google Drive sync enabled: {sync_config['sync_folder']}")
            except Exception as e:
                self.logger.warning(f"Failed to setup Google Drive sync: {e}")
                self.subtitle_syncer = None
        else:
            self.logger.info("Google Drive sync is disabled")

    def _build_yt_dlp_command(self) -> list:
        """
        Build the yt-dlp command with all options.

        Returns:
            List of command arguments
        """
        playlist_url = self.config.get('playlist_url')
        if not playlist_url or playlist_url == "https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID_HERE":
            self.logger.error("Please set a valid playlist_url in config.json")
            raise ValueError("Invalid playlist URL in configuration")

        download_path = self.config.get('download_path', './downloads')
        archive_file = self.config.get('archive_file', '.download_archive.txt')
        options = self.config.get('yt_dlp_options', {})

        # Base command
        cmd = [
            'yt-dlp',
            '--download-archive', archive_file,
            '--paths', download_path,
        ]

        # Add cookies-from-browser: allow override via config (yt_dlp_options)
        # Config keys supported:
        #   cookies_from_browser: string name of browser (e.g., 'chrome')
        #   cookies_path: optional path to browser profile or cookies dir/file
        # If not provided, default to Chrome on macOS user profile directory.
        # Format: --cookies-from-browser BROWSER:PATH (single colon-separated arg)
        cookies_browser = options.get('cookies_from_browser')
        cookies_path = options.get('cookies_path') or options.get('cookies_from_browser_path')
        if cookies_browser:
            if cookies_path:
                cmd.extend(['--cookies-from-browser', f'{cookies_browser}:{cookies_path}'])
            else:
                cmd.extend(['--cookies-from-browser', cookies_browser])
        else:
            # Default: use Chrome on macOS user's Library path
            default_chrome_path = str(Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome')
            cmd.extend(['--cookies-from-browser', f'chrome:{default_chrome_path}'])

        # Add format
        if 'format' in options:
            cmd.extend(['--format', options['format']])

        # Add output template
        if 'output_template' in options:
            cmd.extend(['--output', options['output_template']])

        # Add metadata options
        if options.get('write_thumbnail'):
            cmd.append('--write-thumbnail')
        if options.get('write_description'):
            cmd.append('--write-description')
        if options.get('write_info_json'):
            cmd.append('--write-info-json')

        # Add subtitle options
        if options.get('write_subs'):
            cmd.append('--write-subs')
        if options.get('write_auto_subs'):
            cmd.append('--write-auto-subs')
        if 'sub_lang' in options:
            cmd.extend(['--sub-lang', options['sub_lang']])
        if options.get('embed_subs'):
            cmd.append('--embed-subs')

        # Add error handling options
        if options.get('ignore_errors'):
            cmd.append('--ignore-errors')
        if options.get('no_warnings'):
            cmd.append('--no-warnings')

        # Add merge format
        if 'merge_output_format' in options:
            cmd.extend(['--merge-output-format', options['merge_output_format']])

        # Add skip download option (for subtitle-only downloads)
        if options.get('skip_download'):
            cmd.append('--skip-download')

        # Add playlist URL
        cmd.append(playlist_url)

        return cmd

    def _download_srt_for_video(self, video_id: str) -> bool:
        """
        Download SRT subtitle for a specific video.

        Args:
            video_id: YouTube video ID

        Returns:
            True if successful, False otherwise
        """
        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            self.logger.info(f"Downloading SRT subtitle for video: {video_id}")

            download_path = self.config.get('download_path', './downloads')
            options = self.config.get('yt_dlp_options', {})

            # Build SRT download command
            cmd = [
                'yt-dlp',
                '--skip-download',
                '--write-subs',
                '--write-auto-subs',
                '--sub-langs', 'en',
                '--convert-subs', 'srt',
                '--paths', download_path,
            ]

            # Add cookies-from-browser (same as main download)
            cookies_browser = options.get('cookies_from_browser')
            cookies_path = options.get('cookies_path') or options.get('cookies_from_browser_path')
            if cookies_browser:
                if cookies_path:
                    cmd.extend(['--cookies-from-browser', f'{cookies_browser}:{cookies_path}'])
                else:
                    cmd.extend(['--cookies-from-browser', cookies_browser])
            else:
                # Default: use Chrome on macOS user's Library path
                default_chrome_path = str(Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome')
                cmd.extend(['--cookies-from-browser', f'chrome:{default_chrome_path}'])

            # Add output template (same as main download)
            if 'output_template' in options:
                cmd.extend(['--output', options['output_template']])

            # Add video URL
            cmd.append(video_url)

            # Execute yt-dlp for SRT download
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                self.logger.info(f"Successfully downloaded SRT subtitle for {video_id}")
                return True
            else:
                self.logger.warning(f"Failed to download SRT for {video_id}: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            self.logger.error(f"SRT download timeout for {video_id}")
            return False
        except Exception as e:
            self.logger.error(f"Error downloading SRT for {video_id}: {e}")
            return False

    def download(self) -> bool:
        """
        Execute the download process.

        Returns:
            True if successful, False otherwise
        """
        try:
            self.logger.info("=" * 60)
            self.logger.info("Starting playlist check and download")
            self.logger.info(f"Playlist: {self.config.get('playlist_url')}")

            cmd = self._build_yt_dlp_command()
            self.logger.info(f"Command: {' '.join(cmd)}")

            # Execute yt-dlp
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )

            # Stream output and track downloaded video IDs
            new_downloads = 0
            downloaded_video_ids = []
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    # Log important lines
                    if '[download]' in line and 'Destination:' in line:
                        self.logger.info(line)
                        new_downloads += 1

                        # Extract video ID from the destination line
                        # Format: [download] Destination: downloads/WL-test/20170405 - Title [VIDEO_ID].ext
                        video_id_match = re.search(r'\[([A-Za-z0-9_-]{11})\]\.', line)
                        if video_id_match:
                            video_id = video_id_match.group(1)
                            downloaded_video_ids.append(video_id)
                            self.logger.debug(f"Extracted video ID: {video_id}")
                    elif 'has already been recorded' in line:
                        # Video already downloaded
                        pass
                    elif 'ERROR' in line or 'WARNING' in line:
                        self.logger.warning(line)
                    elif '[download] 100%' in line:
                        self.logger.info(line)

            # Wait for completion
            return_code = process.wait()

            if return_code == 0:
                if new_downloads > 0:
                    self.logger.info(f"Successfully downloaded {new_downloads} new video(s)")

                    # Download SRT subtitles for each newly downloaded video
                    if downloaded_video_ids:
                        self.logger.info(f"Downloading SRT subtitles for {len(downloaded_video_ids)} video(s)...")
                        srt_success_count = 0
                        for video_id in downloaded_video_ids:
                            if self._download_srt_for_video(video_id):
                                srt_success_count += 1
                        self.logger.info(f"Downloaded {srt_success_count}/{len(downloaded_video_ids)} SRT subtitle(s)")

                    # Sync subtitles to Google Drive if enabled
                    if self.subtitle_syncer:
                        try:
                            self.logger.info("Syncing subtitles to Google Drive...")
                            synced, skipped = self.subtitle_syncer.sync_subtitles()
                            if synced > 0:
                                self.logger.info(f"Synced {synced} subtitle(s) to Google Drive")
                        except Exception as e:
                            self.logger.error(f"Failed to sync subtitles: {e}")
                else:
                    self.logger.info("No new videos found in playlist")
                return True
            else:
                self.logger.error(f"yt-dlp exited with code {return_code}")
                return False

        except ValueError as e:
            self.logger.error(f"Configuration error: {e}")
            return False
        except FileNotFoundError:
            self.logger.error("yt-dlp not found. Please install it first.")
            self.logger.error("Install with: pip install yt-dlp")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during download: {e}", exc_info=True)
            return False

    def get_playlist_info(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the playlist without downloading.

        Returns:
            Dictionary with playlist info or None if failed
        """
        try:
            playlist_url = self.config.get('playlist_url')
            # Build base cmd for info lookup and include cookies handling like the downloader
            options = self.config.get('yt_dlp_options', {})
            cmd = [
                'yt-dlp',
                '--dump-json',
                '--flat-playlist',
            ]

            cookies_browser = options.get('cookies_from_browser')
            cookies_path = options.get('cookies_path') or options.get('cookies_from_browser_path')
            if cookies_browser:
                if cookies_path:
                    cmd.extend(['--cookies-from-browser', f'{cookies_browser}:{cookies_path}'])
                else:
                    cmd.extend(['--cookies-from-browser', cookies_browser])
            else:
                default_chrome_path = str(Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome')
                cmd.extend(['--cookies-from-browser', f'chrome:{default_chrome_path}'])

            cmd.append(playlist_url)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                # Parse the first line (playlist info)
                lines = result.stdout.strip().split('\n')
                if lines:
                    return json.loads(lines[0])
            return None

        except Exception as e:
            self.logger.error(f"Failed to get playlist info: {e}")
            return None


def main():
    """Main entry point for the downloader."""
    print("YouTube Playlist Auto-Downloader")
    print("=" * 60)

    downloader = PlaylistDownloader()
    success = downloader.download()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
