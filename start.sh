#!/bin/bash
# Quick start script for YouTube Playlist Auto-Downloader

# Check if config is set up
if grep -q "YOUR_PLAYLIST_ID_HERE" config.json; then
    echo "Error: Please configure config.json first"
    echo "Edit config.json and set your YouTube playlist URL"
    exit 1
fi

# Load credentials for the Gemini summarizer + glance push, if present.
# Keys live in .env (gitignored, chmod 600) -- never in config.json.
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
    if [ -z "$GEMINI_API_KEY" ]; then
        echo "Warning: GEMINI_API_KEY is empty; summaries will be skipped."
    fi
    if [ -z "$SUPABASE_SERVICE_ROLE_KEY" ]; then
        echo "Warning: SUPABASE_SERVICE_ROLE_KEY is empty; glance push disabled."
    fi
fi

# Start the scheduler
echo "Starting YouTube Playlist Auto-Downloader..."
echo "Press Ctrl+C to stop"
echo ""

python3 scheduler.py
