#!/usr/bin/env python3
"""
Subtitle Syncer for YouTube Playlist Auto-Downloader
Automatically syncs downloaded subtitle files to Google Drive sync folder.
"""

import os
import shutil
import logging
from pathlib import Path
from typing import Set, List, Tuple


class SubtitleSyncer:
    """Handles syncing of subtitle files to Google Drive folder."""

    def __init__(self, sync_folder: str, archive_file: str, download_path: str):
        """
        Initialize the SubtitleSyncer.

        Args:
            sync_folder: Path to Google Drive sync folder (e.g., ~/Documents/YT List Subtitles)
            archive_file: Path to sync archive file that tracks synced files
            download_path: Path to downloads directory
        """
        self.sync_folder = Path(sync_folder).expanduser().resolve()
        self.archive_file = Path(archive_file).resolve()
        self.download_path = Path(download_path).resolve()
        self.logger = logging.getLogger('SubtitleSyncer')

        # Ensure sync folder exists
        self.sync_folder.mkdir(parents=True, exist_ok=True)

        # Load sync archive
        self.synced_files = self._load_archive()

    def _load_archive(self) -> Set[str]:
        """Load the set of already synced files from archive."""
        if not self.archive_file.exists():
            return set()

        with open(self.archive_file, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())

    def _save_archive(self):
        """Save the current set of synced files to archive."""
        with open(self.archive_file, 'w', encoding='utf-8') as f:
            for filename in sorted(self.synced_files):
                f.write(f"{filename}\n")

    def _find_subtitle_files(self) -> List[Path]:
        """
        Find all subtitle (.vtt) files in the download directory.

        Returns:
            List of Path objects for subtitle files
        """
        subtitle_files = []

        if not self.download_path.exists():
            self.logger.warning(f"Download path does not exist: {self.download_path}")
            return subtitle_files

        # Search for .vtt files recursively
        for vtt_file in self.download_path.rglob("*.vtt"):
            if vtt_file.is_file():
                subtitle_files.append(vtt_file)

        return subtitle_files

    def _should_sync_file(self, source_file: Path, dest_file: Path) -> bool:
        """
        Determine if a file should be synced.

        Args:
            source_file: Source subtitle file path
            dest_file: Destination file path in sync folder

        Returns:
            True if file should be synced, False otherwise
        """
        # Check if already in archive
        if source_file.name in self.synced_files:
            # Verify destination file still exists
            if dest_file.exists():
                return False
            else:
                # Destination was deleted, resync
                self.logger.info(f"Destination file missing, will resync: {source_file.name}")
                self.synced_files.discard(source_file.name)

        return True

    def sync_subtitles(self) -> Tuple[int, int]:
        """
        Sync all subtitle files to Google Drive folder.

        Returns:
            Tuple of (synced_count, skipped_count)
        """
        subtitle_files = self._find_subtitle_files()

        if not subtitle_files:
            self.logger.info("No subtitle files found to sync")
            return (0, 0)

        synced_count = 0
        skipped_count = 0

        for source_file in subtitle_files:
            # Change extension from .vtt to .txt
            dest_filename = source_file.stem + '.txt'
            dest_file = self.sync_folder / dest_filename

            try:
                if self._should_sync_file(source_file, dest_file):
                    # Copy file to sync folder with .txt extension
                    shutil.copy2(source_file, dest_file)
                    self.logger.info(f"Synced subtitle: {source_file.name} -> {dest_filename}")

                    # Add to archive
                    self.synced_files.add(source_file.name)
                    synced_count += 1
                else:
                    self.logger.debug(f"Skipped (already synced): {source_file.name}")
                    skipped_count += 1

            except Exception as e:
                self.logger.error(f"Failed to sync {source_file.name}: {e}")
                continue

        # Save updated archive
        if synced_count > 0:
            self._save_archive()

        if synced_count > 0:
            self.logger.info(f"Sync complete: {synced_count} synced, {skipped_count} skipped")

        return (synced_count, skipped_count)

    def sync_new_subtitle(self, subtitle_path: Path) -> bool:
        """
        Sync a single newly downloaded subtitle file.

        Args:
            subtitle_path: Path to the subtitle file to sync

        Returns:
            True if synced successfully, False otherwise
        """
        if not subtitle_path.exists() or not subtitle_path.suffix == '.vtt':
            self.logger.warning(f"Invalid subtitle file: {subtitle_path}")
            return False

        # Change extension from .vtt to .txt
        dest_filename = subtitle_path.stem + '.txt'
        dest_file = self.sync_folder / dest_filename

        try:
            if self._should_sync_file(subtitle_path, dest_file):
                # Copy file to sync folder with .txt extension
                shutil.copy2(subtitle_path, dest_file)
                self.logger.info(f"Synced new subtitle: {subtitle_path.name} -> {dest_filename}")

                # Add to archive
                self.synced_files.add(subtitle_path.name)
                self._save_archive()

                return True
            else:
                self.logger.debug(f"Subtitle already synced: {subtitle_path.name}")
                return False

        except Exception as e:
            self.logger.error(f"Failed to sync {subtitle_path.name}: {e}")
            return False


def main():
    """Test function for manual sync operations."""
    import json

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load config
    with open('config.json', 'r') as f:
        config = json.load(f)

    # Check if Google Drive sync is enabled
    if 'google_drive_sync' not in config or not config['google_drive_sync'].get('enabled', False):
        print("Google Drive sync is not enabled in config.json")
        return

    # Initialize syncer
    sync_config = config['google_drive_sync']
    syncer = SubtitleSyncer(
        sync_folder=sync_config['sync_folder'],
        archive_file=sync_config['sync_archive'],
        download_path=config['download_path']
    )

    # Perform sync
    synced, skipped = syncer.sync_subtitles()
    print(f"Sync complete: {synced} files synced, {skipped} files skipped")


if __name__ == '__main__':
    main()
