#!/bin/bash
# Quick start script for YouTube Playlist Auto-Downloader

# Check if config is set up
if grep -q "YOUR_PLAYLIST_ID_HERE" config.json; then
    echo "Error: Please configure config.json first"
    echo "Edit config.json and set your YouTube playlist URL"
    exit 1
fi

# Start the scheduler
echo "Starting YouTube Playlist Auto-Downloader..."
echo "Press Ctrl+C to stop"
echo ""

python3 scheduler.py
