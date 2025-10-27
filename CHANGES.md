# Rate Limiting & Queue System - Change Summary

## Overview
The system has been enhanced to prevent YouTube blocking by implementing rate limiting and queue-based downloads. Instead of downloading all videos at once, it now downloads one video per hour (configurable).

## What Changed

### 1. Playlist Caching
- **New behavior**: Playlist is fetched ONCE and saved to `.playlist_cache.txt`
- **Old behavior**: Playlist was fetched on every check (every 60 seconds)
- **Benefit**: Reduces YouTube API calls by 99%

### 2. Download Queue
- **New behavior**: Missing videos are identified once and saved to `.download_queue.txt`
- **Old behavior**: All missing videos were downloaded immediately
- **Benefit**: Downloads are controlled and rate-limited

### 3. Single Video Downloads
- **New behavior**: Downloads ONE video per check (with rate limiting)
- **Old behavior**: Downloaded ALL new videos at once
- **Benefit**: Prevents YouTube from detecting bulk downloads

### 4. Rate Limiting
- **New behavior**: Downloads one video per hour (default, configurable)
- **Old behavior**: No rate limiting - downloaded as fast as possible
- **Benefit**: Stays under YouTube's rate limit thresholds

## New Configuration Options

Add these to your `config.json`:

```json
{
  "download_interval_hours": 1,
  "playlist_cache_file": ".playlist_cache.txt",
  "download_queue_file": ".download_queue.txt"
}
```

### Configuration Details

| Option | Description | Default | Notes |
|--------|-------------|---------|-------|
| `download_interval_hours` | Hours between video downloads | `1` | Set to `0` to disable rate limiting |
| `playlist_cache_file` | Where to cache playlist video IDs | `.playlist_cache.txt` | Auto-generated |
| `download_queue_file` | Queue of pending downloads | `.download_queue.txt` | Auto-generated |

## New Files

### Created Automatically
- `.playlist_cache.txt` - Cached list of all videos in the playlist
- `.download_queue.txt` - Queue of videos waiting to be downloaded

### New Scripts
- `playlist_manager.py` - Handles playlist caching and queue management
- `refresh_playlist.py` - Utility to manually refresh the playlist cache

## New Workflow

### First Run
1. Run `python3 refresh_playlist.py` to fetch and cache the playlist
2. System identifies missing videos and builds download queue
3. Run `python3 scheduler.py` to start downloading

### Ongoing Operation
1. Scheduler checks every 60 seconds (configurable)
2. If rate limit allows (1 hour has passed), downloads next video from queue
3. Removes video from queue after successful download
4. When queue is empty, automatically checks for new videos in playlist

### Manual Refresh
Run `python3 refresh_playlist.py` at any time to:
- Re-fetch the complete playlist
- Rebuild the download queue
- See how many videos are pending

## Backward Compatibility

- Existing `.download_archive.txt` file is still used and respected
- All existing configuration options still work
- Set `download_interval_hours: 0` to restore old behavior (not recommended)

## Example Usage

### Check Status
```bash
python3 refresh_playlist.py
```

Output:
```
Current Status:
  Total videos in playlist: 112
  Already downloaded: 3
  Pending downloads: 109

Next videos to download (showing up to 5):
  1. Sywq2Ua4GXw
  2. KYs3M_qB6hs
  3. tZJwzt_AlVI
  ...
```

### Start Scheduled Downloads
```bash
python3 scheduler.py
```

With rate limiting enabled (default), you'll see:
```
Rate limiting: 1 video every 1 hour(s)
Queue file: .download_queue.txt
Cache file: .playlist_cache.txt

Check #1 - Downloading video Sywq2Ua4GXw (109 remaining in queue)
...
Check #2 - SKIPPED (rate limit)
Rate limit: Next download available in 00:59:45
```

## Performance Impact

### Before (Old System)
- Playlist fetch: Every 60 seconds
- YouTube API calls: 1,440 per day (minimum)
- Download pattern: Bulk downloads (all at once)
- Risk of blocking: HIGH

### After (New System)
- Playlist fetch: Once, then only when queue is empty
- YouTube API calls: ~1-2 per day
- Download pattern: 1 video per hour
- Risk of blocking: VERY LOW

## Troubleshooting

### Queue is empty but videos are missing
Run `python3 refresh_playlist.py` to rebuild the queue

### Want to download faster
Edit `config.json` and reduce `download_interval_hours`:
- `0.5` = 30 minutes between downloads
- `0.25` = 15 minutes between downloads
- `0` = no rate limiting (not recommended)

### Want to skip rate limiting once
1. Stop the scheduler (Ctrl+C)
2. Set `download_interval_hours: 0` temporarily
3. Run one check manually: `python3 downloader.py`
4. Restore `download_interval_hours: 1`
5. Restart scheduler

## Migration Guide

If you're upgrading from the old system:

1. **Stop the scheduler** if it's running (Ctrl+C)

2. **Update config.json** - add these three lines:
   ```json
   "download_interval_hours": 1,
   "playlist_cache_file": ".playlist_cache.txt",
   "download_queue_file": ".download_queue.txt",
   ```

3. **Initialize the cache and queue**:
   ```bash
   python3 refresh_playlist.py
   ```

4. **Start the new system**:
   ```bash
   python3 scheduler.py
   ```

5. **Verify it's working** - you should see:
   ```
   Rate limiting: 1 video every 1 hour(s)
   Queue file: .download_queue.txt
   Cache file: .playlist_cache.txt
   ```

Your existing `.download_archive.txt` will be preserved and the system will not re-download any videos you already have.
