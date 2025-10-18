# Quick Start Guide

## 1. Setup (One Time)

```bash
# Run the setup script
./setup.sh
```

## 2. Configure

Edit [config.json](config.json) and set your playlist URL:

```json
{
  "playlist_url": "https://www.youtube.com/playlist?list=YOUR_ACTUAL_PLAYLIST_ID"
}
```

## 3. Run

### Option A: Simple Start
```bash
./start.sh
```

### Option B: Manual Start
```bash
# One-time download
python3 downloader.py

# Continuous monitoring (checks every 60 seconds)
python3 scheduler.py
```

### Option C: Background Service
```bash
# Run in background
nohup python3 scheduler.py > output.log 2>&1 &

# Check if running
ps aux | grep scheduler.py

# Stop it (replace PID with actual process ID)
kill <PID>
```

## 4. Monitor

```bash
# Watch logs in real-time
tail -f downloader.log

# Check what's been downloaded
cat .download_archive.txt
```

## Configuration Tips

### Change Check Interval

Edit [config.json](config.json):
```json
{
  "check_interval_seconds": 300  // Check every 5 minutes instead of 1
}
```

### Download Audio Only

```json
{
  "yt_dlp_options": {
    "format": "bestaudio[ext=m4a]/bestaudio",
    "merge_output_format": "m4a"
  }
}
```

### Change Download Location

```json
{
  "download_path": "/path/to/your/downloads"
}
```

## Troubleshooting

### "yt-dlp not found"
```bash
pip3 install yt-dlp
```

### "Permission denied"
```bash
chmod +x *.sh *.py
```

### Check logs
```bash
cat downloader.log
```

---

For complete documentation, see [README.md](README.md)
