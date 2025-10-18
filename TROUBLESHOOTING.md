# Troubleshooting Guide

## Common Issues and Solutions

### 1. "Requested format is not available" Error

**Symptoms:**
```
ERROR: [youtube] xxxxxxx: Requested format is not available
WARNING: nsig extraction failed: Some formats may be missing
WARNING: YouTube is forcing SABR streaming for this client
```

**Cause:**
YouTube frequently changes its streaming infrastructure. Some specific format combinations may not be available for all videos.

**Solution:**
Use a more flexible format selector in your [config.json](config.json):

**Recommended (most compatible):**
```json
{
  "yt_dlp_options": {
    "format": "bestvideo*+bestaudio/best"
  }
}
```

**Alternative options:**

For specific quality (e.g., max 1080p):
```json
{
  "yt_dlp_options": {
    "format": "bestvideo*[height<=1080]+bestaudio/best[height<=1080]"
  }
}
```

For preferring MP4 but accepting any format:
```json
{
  "yt_dlp_options": {
    "format": "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"
  }
}
```

### 2. "nsig extraction failed" Warnings

**Symptoms:**
```
WARNING: [youtube] nsig extraction failed: Some formats may be missing
```

**Impact:**
This is a **warning only** - downloads will still work. Some formats may be unavailable, but yt-dlp will use available formats.

**Cause:**
YouTube's signature (nsig) extraction changes frequently. yt-dlp needs regular updates to keep up.

**Solution:**
1. **Update yt-dlp** regularly:
   ```bash
   pip install -U yt-dlp
   # or
   brew upgrade yt-dlp  # macOS with Homebrew
   ```

2. **Use flexible format strings** (as shown above)

3. **If warnings bother you**, set in config:
   ```json
   {
     "yt_dlp_options": {
       "no_warnings": true
     }
   }
   ```
   Note: This hides ALL warnings, not just nsig warnings.

### 3. Downloads Timing Out

**Symptoms:**
- Downloads hang or timeout
- Very slow download speeds
- Connection errors

**Solutions:**

**Increase timeout in downloader.py** (for very large files):
Currently, there's no explicit timeout. If needed, downloads will continue until complete.

**Check your network:**
```bash
# Test download speed manually
yt-dlp --test
```

**Use lower quality** for faster downloads:
```json
{
  "yt_dlp_options": {
    "format": "bestvideo*[height<=720]+bestaudio/best[height<=720]"
  }
}
```

### 4. Subtitle Download Issues

**Symptoms:**
- Subtitles not downloading
- "No subtitles found" errors

**Solutions:**

**Check if video has subtitles:**
```bash
yt-dlp --list-subs <video-url>
```

**Try all available subtitles:**
```json
{
  "yt_dlp_options": {
    "write_subs": true,
    "sub_lang": "all"
  }
}
```

**Try auto-generated subtitles:**
```json
{
  "yt_dlp_options": {
    "write_subs": true,
    "write_auto_subs": true,
    "sub_lang": "en"
  }
}
```

**Note:** Add `"write_auto_subs": true` to downloader.py if needed (currently not implemented).

### 5. Disk Space Issues

**Symptoms:**
```
ERROR: unable to write data
OSError: [Errno 28] No space left on device
```

**Solutions:**

**Check available space:**
```bash
df -h ./downloads
```

**Clean up old downloads:**
```bash
# Be careful with this!
rm -rf ./downloads/*
# This will NOT re-download videos unless you also delete .download_archive.txt
```

**Change download location** to larger disk:
```json
{
  "download_path": "/path/to/larger/disk/downloads"
}
```

### 6. "yt-dlp not found" Error

**Symptoms:**
```
ERROR: yt-dlp not found. Please install it first.
```

**Solutions:**

**Check if installed:**
```bash
which yt-dlp
yt-dlp --version
```

**Install yt-dlp:**
```bash
# Using pip
pip install yt-dlp

# Using homebrew (macOS)
brew install yt-dlp

# Using system package manager (Linux)
sudo apt install yt-dlp  # Debian/Ubuntu
sudo dnf install yt-dlp  # Fedora
```

### 7. Permission Denied Errors

**Symptoms:**
```
PermissionError: [Errno 13] Permission denied
```

**Solutions:**

**Make scripts executable:**
```bash
chmod +x downloader.py scheduler.py setup.sh start.sh
```

**Check download directory permissions:**
```bash
ls -la downloads/
chmod 755 downloads/
```

**Don't run as root** unless necessary. Create downloads in user-owned directory.

### 8. Archive File Corruption

**Symptoms:**
- Videos re-downloading even though already downloaded
- Duplicate entries in archive

**Solutions:**

**Check archive file:**
```bash
cat .download_archive.txt | sort | uniq -d
# If duplicates found, clean them:
sort .download_archive.txt | uniq > .download_archive.txt.clean
mv .download_archive.txt.clean .download_archive.txt
```

**Rebuild archive from existing downloads:**
```bash
# Backup old archive
cp .download_archive.txt .download_archive.txt.bak

# Get video IDs from filenames
ls -1 downloads/*/*.mp4 | grep -oP '\[([a-zA-Z0-9_-]+)\]' | tr -d '[]' | sed 's/^/youtube /' > .download_archive.txt
```

### 9. Playlist Not Being Detected

**Symptoms:**
- Only one video downloads
- "This playlist doesn't exist" errors

**Solutions:**

**Check playlist URL format:**
```json
{
  "playlist_url": "https://www.youtube.com/playlist?list=PLxxxxxxxxxx"
}
```

**NOT this:**
```json
{
  "playlist_url": "https://www.youtube.com/watch?v=xxxxx&list=PLxxx"
}
```

**Test playlist URL manually:**
```bash
yt-dlp --flat-playlist <your-playlist-url>
```

### 10. Embedded Subtitles Not Working

**Symptoms:**
- Subtitle files downloaded but not embedded
- Video has no subtitle tracks

**Cause:**
Embedding subtitles requires video re-encoding, which requires ffmpeg.

**Solution:**

**Install ffmpeg:**
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg
```

**Verify ffmpeg:**
```bash
ffmpeg -version
```

**Alternative:** Don't embed, just download:
```json
{
  "yt_dlp_options": {
    "write_subs": true,
    "sub_lang": "en",
    "embed_subs": false
  }
}
```

### 11. High CPU Usage

**Symptoms:**
- System slow during downloads
- High CPU temperature

**Cause:**
- Video transcoding (format conversion)
- Subtitle embedding
- Multiple concurrent downloads (if using multiple instances)

**Solutions:**

**Avoid transcoding** - use native formats:
```json
{
  "yt_dlp_options": {
    "format": "bestvideo*+bestaudio/best",
    "merge_output_format": "mkv"  // Native container, no re-encoding
  }
}
```

**Don't embed subtitles** (saves encoding):
```json
{
  "yt_dlp_options": {
    "embed_subs": false
  }
}
```

**Increase check interval** (less frequent checks):
```json
{
  "check_interval_seconds": 300
}
```

## Getting Help

### Check Logs First

```bash
# View recent errors
grep ERROR downloader.log

# View warnings
grep WARNING downloader.log

# View last 50 lines
tail -50 downloader.log
```

### Test Manually

Before reporting issues, test the exact yt-dlp command:

```bash
# Extract command from logs (look for "Command:" in debug output)
# Or build it manually:
yt-dlp \
  --download-archive .download_archive.txt \
  --paths ./downloads \
  --format "bestvideo*+bestaudio/best" \
  --output "%(playlist_title)s/%(upload_date)s - %(title)s [%(id)s].%(ext)s" \
  --write-thumbnail \
  --write-description \
  --write-info-json \
  --write-subs \
  --sub-lang en \
  --embed-subs \
  --ignore-errors \
  --merge-output-format mp4 \
  "<your-playlist-url>"
```

### Update Everything

Often, issues are resolved by updating:

```bash
# Update yt-dlp
pip install -U yt-dlp

# Update Python packages
pip install -U -r requirements.txt

# Update system packages
brew upgrade  # macOS
sudo apt update && sudo apt upgrade  # Ubuntu/Debian
```

### Report Issues

If problems persist:

1. **For yt-dlp issues**: https://github.com/yt-dlp/yt-dlp/issues
2. **For this project**: Include:
   - Error messages from logs
   - Your config.json (remove sensitive info)
   - yt-dlp version: `yt-dlp --version`
   - Python version: `python3 --version`
   - Operating system
   - Output of manual yt-dlp test command

## Performance Tips

### Optimize for Speed

```json
{
  "yt_dlp_options": {
    "format": "best",  // Single stream, no merging
    "write_thumbnail": false,
    "write_description": false,
    "write_info_json": false,
    "write_subs": false
  }
}
```

### Optimize for Quality

```json
{
  "yt_dlp_options": {
    "format": "bestvideo*+bestaudio/best",
    "write_thumbnail": true,
    "write_description": true,
    "write_info_json": true,
    "write_subs": true,
    "sub_lang": "all",
    "embed_subs": false  // Faster than embedding
  }
}
```

### Balance Speed and Quality

```json
{
  "yt_dlp_options": {
    "format": "bestvideo*[height<=1080]+bestaudio/best[height<=1080]",
    "write_thumbnail": true,
    "write_subs": true,
    "sub_lang": "en",
    "embed_subs": true
  }
}
```
