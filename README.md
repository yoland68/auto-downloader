# YouTube Playlist Auto-Downloader

Automatically download videos from a YouTube playlist using `yt-dlp`. The system continuously monitors the playlist for new videos and downloads them automatically.

## Features

- **Automatic Monitoring**: Checks for new videos every 60 seconds (configurable)
- **Smart Tracking**: Never downloads the same video twice using archive tracking
- **Concurrency Protection**: Thread-safe locking prevents overlapping downloads
- **Flexible Configuration**: Customize video quality, format, and download location
- **Comprehensive Logging**: Track all downloads and errors
- **Graceful Shutdown**: Properly handles Ctrl+C and system signals
- **Error Recovery**: Continues running even if individual downloads fail
- **Metadata Saving**: Optionally save thumbnails, descriptions, and video info
- **Subtitle Support**: Download both manual and auto-generated subtitles
- **Google Drive Sync**: Automatically sync subtitles to Google Drive (macOS)

## Prerequisites

- Python 3.7 or higher
- `yt-dlp` installed on your system

## Installation

1. **Clone or download this repository**

2. **Install yt-dlp** (if not already installed):
   ```bash
   # Using pip
   pip install yt-dlp

   # Using homebrew (macOS)
   brew install yt-dlp
   ```

3. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure your playlist**:
   Edit `config.json` and replace `YOUR_PLAYLIST_ID_HERE` with your actual playlist URL:
   ```json
   {
     "playlist_url": "https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxx"
   }
   ```

## Configuration

Edit `config.json` to customize the behavior:

```json
{
  "playlist_url": "https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID",
  "download_path": "./downloads",
  "archive_file": ".download_archive.txt",
  "log_file": "downloader.log",
  "check_interval_seconds": 60,
  "yt_dlp_options": {
    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "output_template": "%(playlist_title)s/%(upload_date)s - %(title)s [%(id)s].%(ext)s",
    "write_thumbnail": true,
    "write_description": true,
    "write_info_json": true,
    "write_subs": true,
    "write_auto_subs": true,
    "sub_lang": "en",
    "embed_subs": true,
    "no_warnings": false,
    "ignore_errors": true,
    "merge_output_format": "mp4"
  }
}
```

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `playlist_url` | YouTube playlist URL to monitor | Required |
| `download_path` | Directory where videos will be saved | `./downloads` |
| `archive_file` | File to track downloaded videos | `.download_archive.txt` |
| `log_file` | Log file location | `downloader.log` |
| `check_interval_seconds` | How often to check for new videos | `60` |

### yt-dlp Options

| Option | Description |
|--------|-------------|
| `format` | Video quality/format preference |
| `output_template` | Filename template for downloaded videos |
| `write_thumbnail` | Save video thumbnail |
| `write_description` | Save video description |
| `write_info_json` | Save video metadata as JSON |
| `write_subs` | Download manual subtitles |
| `write_auto_subs` | Download auto-generated subtitles |
| `sub_lang` | Subtitle language (e.g., "en", "en,es", "all") |
| `embed_subs` | Embed subtitles into video file |
| `ignore_errors` | Continue on download errors |
| `merge_output_format` | Final output format |

### Google Drive Sync Options

The system can automatically sync downloaded subtitle files to a Google Drive folder (requires Google Drive desktop app on macOS):

| Option | Description | Default |
|--------|-------------|---------|
| `enabled` | Enable/disable Google Drive sync | `true` |
| `sync_folder` | Path to Google Drive sync folder | `~/Documents/YT List Subtitles` |
| `sync_archive` | File to track synced subtitles | `.subtitle_sync_archive.txt` |
| `preserve_structure` | Keep folder structure (not currently implemented) | `false` |

**Example configuration:**
```json
{
  "google_drive_sync": {
    "enabled": true,
    "sync_folder": "~/Documents/YT List Subtitles",
    "sync_archive": ".subtitle_sync_archive.txt",
    "preserve_structure": false
  }
}
```

**How it works:**
- After each download, subtitle (.vtt) files are automatically copied to the specified sync folder
- Google Drive desktop app syncs the folder to the cloud
- Archive tracking prevents re-copying files that are already synced
- Sync happens immediately after download completion
- If sync fails, download is still considered successful (graceful error handling)

## Usage

### One-time Download

Download all videos from the playlist once:

```bash
python downloader.py
```

### Continuous Monitoring (Recommended)

Start the scheduler to continuously monitor and download new videos:

```bash
python scheduler.py
```

The scheduler will:
1. Run an initial check immediately
2. Check for new videos every 60 seconds (or your configured interval)
3. Download any new videos found
4. Log all activity to the console and log file

**To stop the scheduler**: Press `Ctrl+C`

### Using a Custom Config File

```bash
python scheduler.py --config my_custom_config.json
```

## Running as a Background Service

### Using nohup (Linux/macOS)

```bash
nohup python scheduler.py &
```

To stop:
```bash
# Find the process ID
ps aux | grep scheduler.py

# Kill the process
kill <PID>
```

### Using screen (Linux/macOS)

```bash
# Start a screen session
screen -S playlist-downloader

# Run the scheduler
python scheduler.py

# Detach: Press Ctrl+A then D

# Reattach later
screen -r playlist-downloader
```

### Using systemd (Linux)

Create `/etc/systemd/system/playlist-downloader.service`:

```ini
[Unit]
Description=YouTube Playlist Auto-Downloader
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/aududownloader
ExecStart=/usr/bin/python3 /path/to/aududownloader/scheduler.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable playlist-downloader
sudo systemctl start playlist-downloader
sudo systemctl status playlist-downloader
```

### Using launchd (macOS)

Create `~/Library/LaunchAgents/com.user.playlist-downloader.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.playlist-downloader</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/your-username/Code/aududownloader/scheduler.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/your-username/Code/aududownloader</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/your-username/Code/aududownloader/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/your-username/Code/aududownloader/stderr.log</string>
</dict>
</plist>
```

Then:
```bash
launchctl load ~/Library/LaunchAgents/com.user.playlist-downloader.plist
launchctl start com.user.playlist-downloader
```

## Project Structure

```
aududownloader/
├── config.json                    # Configuration file
├── config_subs_only.json          # Subtitle-only config
├── downloader.py                  # Core download logic
├── scheduler.py                   # Scheduling and monitoring
├── subtitle_syncer.py             # Google Drive sync module
├── requirements.txt               # Python dependencies
├── README.md                      # This file
├── .download_archive.txt          # Tracks downloaded videos (auto-generated)
├── .subtitle_sync_archive.txt     # Tracks synced subtitles (auto-generated)
├── downloader.log                 # Activity log (auto-generated)
└── downloads/                     # Downloaded videos (auto-generated)
```

## How It Works

1. **Archive Tracking**: The system uses yt-dlp's `--download-archive` feature to maintain a list of downloaded video IDs in `.download_archive.txt`. This prevents re-downloading videos.

2. **Periodic Checks**: The scheduler checks the playlist every minute (configurable) by running yt-dlp with the playlist URL.

3. **Smart Downloads**: yt-dlp automatically compares the playlist against the archive file and only downloads new videos.

4. **Concurrency Protection**: A thread-safe lock ensures only one download runs at a time. If a download takes longer than 60 seconds, subsequent checks are safely skipped until the current download completes. See [CONCURRENCY.md](CONCURRENCY.md) for details.

5. **Logging**: All activity is logged to both the console and a log file for monitoring and debugging.

## Monitoring

### View Logs in Real-time

```bash
tail -f downloader.log
```

### Check Archive File

The `.download_archive.txt` file contains one line per downloaded video:

```
youtube PLxxxxxx-Video1ID
youtube PLxxxxxx-Video2ID
```

### Check Download Statistics

The log file contains detailed information about:
- When checks were performed
- Which videos were downloaded
- Any errors or warnings
- Download progress

## Troubleshooting

### "yt-dlp not found" Error

Make sure yt-dlp is installed:
```bash
which yt-dlp
# Should output: /usr/local/bin/yt-dlp or similar
```

If not installed:
```bash
pip install yt-dlp
```

### "Invalid playlist URL" Error

Make sure your `config.json` has a valid YouTube playlist URL:
```json
{
  "playlist_url": "https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxx"
}
```

### Videos Not Downloading

1. Check the log file for errors: `cat downloader.log`
2. Verify the playlist is public or you have access
3. Test manually: `yt-dlp <your-playlist-url>`
4. Check your internet connection

### Permission Errors

Make sure the scripts are executable:
```bash
chmod +x downloader.py scheduler.py
```

### Seeing "SKIPPED" Messages in Logs

This is **normal** when downloads take longer than your check interval. The system safely skips checks when a download is still in progress to prevent overlapping downloads and archive corruption. See [CONCURRENCY.md](CONCURRENCY.md) for a detailed explanation.

If you see many skipped checks, consider increasing `check_interval_seconds` in your config:
```json
{
  "check_interval_seconds": 300  // Check every 5 minutes instead of 1
}
```

## Advanced Usage

### Download Only Audio

Modify `config.json`:
```json
{
  "yt_dlp_options": {
    "format": "bestaudio[ext=m4a]/bestaudio",
    "merge_output_format": "m4a"
  }
}
```

### Download Specific Quality

```json
{
  "yt_dlp_options": {
    "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
  }
}
```

### Custom Filename Template

```json
{
  "yt_dlp_options": {
    "output_template": "%(title)s-%(id)s.%(ext)s"
  }
}
```

Available template variables:
- `%(title)s` - Video title
- `%(id)s` - Video ID
- `%(ext)s` - File extension
- `%(upload_date)s` - Upload date (YYYYMMDD)
- `%(uploader)s` - Channel name
- `%(playlist_title)s` - Playlist name
- `%(playlist_index)s` - Video position in playlist

### Subtitle Options

**Download and embed English subtitles including auto-generated** (default configuration):
```json
{
  "yt_dlp_options": {
    "write_subs": true,
    "write_auto_subs": true,
    "sub_lang": "en",
    "embed_subs": true
  }
}
```

**Download multiple subtitle languages including auto-generated**:
```json
{
  "yt_dlp_options": {
    "write_subs": true,
    "write_auto_subs": true,
    "sub_lang": "en,es,fr",
    "embed_subs": true
  }
}
```

**Download all available subtitles including auto-generated**:
```json
{
  "yt_dlp_options": {
    "write_subs": true,
    "write_auto_subs": true,
    "sub_lang": "all",
    "embed_subs": false
  }
}
```
Note: When using "all" languages, set `embed_subs` to `false` to save subtitles as separate files.

**Download only auto-generated subtitles** (no manual subtitles):
```json
{
  "yt_dlp_options": {
    "write_subs": false,
    "write_auto_subs": true,
    "sub_lang": "en",
    "embed_subs": true
  }
}
```

**Disable all subtitles**:
```json
{
  "yt_dlp_options": {
    "write_subs": false,
    "write_auto_subs": false
  }
}
```

## License

This project is provided as-is for personal use.

## Credits

Built with:
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Video downloader
- [schedule](https://github.com/dbader/schedule) - Python job scheduling
