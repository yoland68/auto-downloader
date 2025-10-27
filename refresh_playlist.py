#!/usr/bin/env python3
"""
Refresh Playlist Cache
Manually refresh the playlist cache and rebuild the download queue.
Useful for forcing a playlist update without waiting for the scheduler.
"""

import sys
import logging
from pathlib import Path
from downloader import PlaylistDownloader


def main():
    """Refresh playlist cache and show status."""
    print("=" * 70)
    print("Playlist Cache Refresh Utility")
    print("=" * 70)
    print()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Check for custom config
    config_path = "config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    if not Path(config_path).exists():
        print(f"Error: Configuration file '{config_path}' not found.")
        sys.exit(1)

    try:
        # Initialize downloader
        downloader = PlaylistDownloader(config_path)

        if not downloader.playlist_manager:
            print("Error: Playlist manager not initialized.")
            sys.exit(1)

        # Show current status before refresh
        print("Current Status:")
        status = downloader.playlist_manager.get_queue_status()
        if status['cache_exists']:
            print(f"  Cached videos: {status['total_videos']}")
            print(f"  Downloaded: {status['downloaded']}")
            print(f"  In queue: {status['pending']}")
        else:
            print("  No cache found (first run)")
        print()

        # Refresh cache and queue
        print("Refreshing playlist cache...")
        if downloader.playlist_manager.refresh_cache_and_queue():
            print()
            print("✓ Cache refresh successful!")
            print()

            # Show updated status
            status = downloader.playlist_manager.get_queue_status()
            print("Updated Status:")
            print(f"  Total videos in playlist: {status['total_videos']}")
            print(f"  Already downloaded: {status['downloaded']}")
            print(f"  Pending downloads: {status['pending']}")
            print()

            # Show next few videos in queue
            queue = downloader.playlist_manager.load_download_queue()
            if queue:
                print(f"Next videos to download (showing up to 5):")
                for i, video_id in enumerate(queue[:5], 1):
                    print(f"  {i}. {video_id}")
                if len(queue) > 5:
                    print(f"  ... and {len(queue) - 5} more")
            else:
                print("All videos have been downloaded! Queue is empty.")

            print()
            print("=" * 70)
            sys.exit(0)
        else:
            print()
            print("✗ Failed to refresh cache. Check the logs for details.")
            print()
            print("=" * 70)
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
