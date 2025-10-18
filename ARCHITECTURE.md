# System Architecture

## Overview

The YouTube Playlist Auto-Downloader is a Python-based system that continuously monitors a YouTube playlist and automatically downloads new videos.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     USER CONFIGURATION                       │
│                       (config.json)                          │
│  - Playlist URL                                              │
│  - Download path                                             │
│  - Check interval                                            │
│  - yt-dlp options                                            │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      SCHEDULER (scheduler.py)                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  1. Load configuration                                 │ │
│  │  2. Initialize downloader                              │ │
│  │  3. Schedule job every N seconds (default: 60)         │ │
│  │  4. Run job immediately on start                       │ │
│  │  5. Handle graceful shutdown (Ctrl+C)                  │ │
│  └───────────────────────┬────────────────────────────────┘ │
└────────────────────────────┼─────────────────────────────────┘
                          │
                          │ Every 60 seconds
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  DOWNLOADER (downloader.py)                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  1. Build yt-dlp command with options                  │ │
│  │  2. Include --download-archive flag                    │ │
│  │  3. Execute yt-dlp as subprocess                       │ │
│  │  4. Stream and parse output                            │ │
│  │  5. Log activity and errors                            │ │
│  └───────────────────────┬────────────────────────────────┘ │
└────────────────────────────┼─────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     yt-dlp (External Tool)                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  1. Fetch playlist metadata from YouTube              │ │
│  │  2. Compare video IDs with archive file               │ │
│  │  3. Download only new videos                          │ │
│  │  4. Record downloaded IDs to archive                  │ │
│  │  5. Save video files and metadata                     │ │
│  └───────────────────────┬────────────────────────────────┘ │
└────────────────────────────┼─────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                        FILE SYSTEM                           │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │   downloads/    │  │ .download_   │  │ downloader.log │ │
│  │                 │  │  archive.txt │  │                │ │
│  │ - video.mp4     │  │              │  │ Activity logs  │ │
│  │ - thumbnail.jpg │  │ video_id_1   │  │ Error logs     │ │
│  │ - description   │  │ video_id_2   │  │ Download info  │ │
│  │ - info.json     │  │ video_id_3   │  │                │ │
│  └─────────────────┘  └──────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Configuration Layer (config.json)

**Purpose**: Centralized configuration for the entire system

**Key Settings**:
- `playlist_url`: YouTube playlist to monitor
- `download_path`: Where to save videos
- `archive_file`: Tracks downloaded videos
- `check_interval_seconds`: How often to check for updates
- `yt_dlp_options`: Quality, format, metadata options

### 2. Scheduler (scheduler.py)

**Purpose**: Manages continuous monitoring and periodic execution

**Responsibilities**:
- Load configuration on startup
- Create PlaylistDownloader instance
- Schedule downloads at regular intervals (default: every 60 seconds)
- Run initial check immediately
- Handle graceful shutdown (SIGINT, SIGTERM)
- Track number of checks performed

**Key Features**:
- Uses `schedule` library for job scheduling
- Signal handlers for clean shutdown
- Comprehensive logging
- Error recovery (continues running after errors)

### 3. Downloader (downloader.py)

**Purpose**: Core download logic and yt-dlp integration

**Responsibilities**:
- Load and validate configuration
- Setup logging system
- Create download directories
- Build yt-dlp command with all options
- Execute yt-dlp as subprocess
- Stream and parse yt-dlp output
- Track new downloads
- Log all activity

**Key Features**:
- Archive-based tracking (no duplicate downloads)
- Real-time output streaming
- Error handling and reporting
- Optional metadata saving (thumbnails, descriptions, JSON)

### 4. Archive System (.download_archive.txt)

**Purpose**: Prevent duplicate downloads

**How it Works**:
- yt-dlp checks this file before downloading each video
- If video ID is in the file, skip it
- After successful download, append video ID to file
- One line per video: `youtube <video_id>`

**Benefits**:
- Efficient (only new videos are processed)
- Reliable (survives script restarts)
- Portable (can be backed up and restored)

### 5. Logging System (downloader.log)

**Purpose**: Track all system activity

**Logs Include**:
- Timestamp of each check
- Videos being downloaded
- Download progress
- Errors and warnings
- Summary statistics

**Output Destinations**:
- Console (stdout)
- Log file (persistent)

## Data Flow

1. **Startup**:
   ```
   User runs scheduler.py
   → Load config.json
   → Initialize logging
   → Create download directories
   → Run immediate check
   → Start scheduled loop
   ```

2. **Each Check Cycle** (every 60 seconds):
   ```
   Timer triggers
   → scheduler.py calls downloader.download()
   → Build yt-dlp command
   → Execute: yt-dlp --download-archive .download_archive.txt <playlist_url>
   → yt-dlp fetches playlist from YouTube
   → yt-dlp compares playlist with archive
   → yt-dlp downloads new videos only
   → Update .download_archive.txt
   → Log results
   → Wait for next cycle
   ```

3. **Download Process**:
   ```
   New video detected
   → Download video stream
   → Download audio stream (if separate)
   → Merge video + audio
   → Save to downloads/ directory
   → Save thumbnail (optional)
   → Save description (optional)
   → Save metadata JSON (optional)
   → Write video ID to archive
   → Log success
   ```

## Error Handling

### Network Errors
- yt-dlp retries automatically
- `ignore_errors: true` continues with next video
- Logged but doesn't stop scheduler

### Download Errors
- Individual video failures don't stop the playlist
- Errors logged with details
- Next check cycle will retry failed videos

### Configuration Errors
- Validated on startup
- Clear error messages
- Prevents execution with invalid config

### System Signals
- SIGINT (Ctrl+C): Graceful shutdown
- SIGTERM: Graceful shutdown
- Completes current download before exiting

## Scalability Considerations

### Performance
- Lightweight: Only runs when checking/downloading
- Efficient: Archive prevents re-processing
- Resource-friendly: Single Python process

### Storage
- Downloads grow with playlist size
- Archive file is tiny (one line per video)
- Logs rotate (can be configured)

### Multiple Playlists
- Run multiple instances with different config files
- Each instance is independent
- Example: `python3 scheduler.py --config playlist1.json`

## Security Considerations

### Safe Operations
- Read-only access to YouTube (no credentials needed)
- Writes only to configured directories
- No external dependencies except yt-dlp

### Best Practices
- Keep yt-dlp updated for security fixes
- Use restricted user account when running as service
- Set appropriate file permissions on download directory

## Maintenance

### Regular Tasks
- Monitor log file size
- Update yt-dlp: `pip install -U yt-dlp`
- Update Python dependencies: `pip install -U -r requirements.txt`
- Backup .download_archive.txt

### Troubleshooting
1. Check logs: `tail -f downloader.log`
2. Test manually: `python3 downloader.py`
3. Verify yt-dlp: `yt-dlp --version`
4. Check disk space: `df -h`

## Extension Points

### Custom Processing
Add post-download hooks in downloader.py:
```python
def process_downloaded_video(video_path):
    # Custom logic here
    pass
```

### Notifications
Add notification service integration:
```python
def notify_new_download(video_title):
    # Send email, Slack message, etc.
    pass
```

### Advanced Filtering
Modify yt-dlp options in config.json:
```json
{
  "yt_dlp_options": {
    "match_filter": "duration < 600"  // Only videos under 10 minutes
  }
}
```
