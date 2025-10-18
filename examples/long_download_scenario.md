# Example: Long Download Scenario

This example demonstrates how the system handles a download that takes longer than the check interval.

## Scenario Setup

- **Check Interval**: 60 seconds
- **Playlist**: 5 large 4K videos (2 GB each)
- **Download Speed**: 5 Mbps
- **Time per video**: ~45 seconds

## Timeline

```
┌────────────────────────────────────────────────────────────────┐
│ Time    Event                          Status        Lock      │
├────────────────────────────────────────────────────────────────┤
│ 00:00   Check #1 triggered            ✓ START       ACQUIRED  │
│         - Found 5 new videos                                    │
│         - Downloading video 1/5...                              │
│                                                                 │
│ 00:45   - Video 1/5 complete                        HELD       │
│         - Downloading video 2/5...                              │
│                                                                 │
│ 01:00   Check #2 triggered            ⚠ SKIPPED     HELD       │
│         └─> Previous download still running                     │
│                                                                 │
│ 01:30   - Video 2/5 complete                        HELD       │
│         - Downloading video 3/5...                              │
│                                                                 │
│ 02:00   Check #3 triggered            ⚠ SKIPPED     HELD       │
│         └─> Previous download still running                     │
│                                                                 │
│ 02:15   - Video 3/5 complete                        HELD       │
│         - Downloading video 4/5...                              │
│                                                                 │
│ 03:00   Check #4 triggered            ⚠ SKIPPED     HELD       │
│         └─> Previous download still running                     │
│         - Video 4/5 complete                        HELD       │
│         - Downloading video 5/5...                              │
│                                                                 │
│ 03:45   - Video 5/5 complete                        HELD       │
│         - Updating archive file                                 │
│         Check #1 COMPLETE (225 sec)                 RELEASED   │
│                                                                 │
│ 04:00   Check #5 triggered            ✓ START       ACQUIRED  │
│         - No new videos found                                   │
│         Check #5 COMPLETE (2 sec)                   RELEASED   │
│                                                                 │
│ 05:00   Check #6 triggered            ✓ START       ACQUIRED  │
│         - No new videos found                                   │
│         Check #6 COMPLETE (2 sec)                   RELEASED   │
└────────────────────────────────────────────────────────────────┘
```

## Log Output

```log
2025-10-18 10:00:00 - DownloadScheduler - INFO - Check #1 - 2025-10-18 10:00:00
2025-10-18 10:00:00 - PlaylistDownloader - INFO - Starting playlist check and download
2025-10-18 10:00:15 - PlaylistDownloader - INFO - [download] Destination: downloads/Video1.mp4
2025-10-18 10:00:45 - PlaylistDownloader - INFO - [download] 100% of 2.1GiB
2025-10-18 10:00:45 - PlaylistDownloader - INFO - [download] Destination: downloads/Video2.mp4

2025-10-18 10:01:00 - DownloadScheduler - WARNING - Check #2 - SKIPPED (previous download still in progress) - Total skipped: 1

2025-10-18 10:01:30 - PlaylistDownloader - INFO - [download] 100% of 2.0GiB
2025-10-18 10:01:30 - PlaylistDownloader - INFO - [download] Destination: downloads/Video3.mp4

2025-10-18 10:02:00 - DownloadScheduler - WARNING - Check #3 - SKIPPED (previous download still in progress) - Total skipped: 2

2025-10-18 10:02:15 - PlaylistDownloader - INFO - [download] 100% of 2.2GiB
2025-10-18 10:02:15 - PlaylistDownloader - INFO - [download] Destination: downloads/Video4.mp4

2025-10-18 10:03:00 - DownloadScheduler - WARNING - Check #4 - SKIPPED (previous download still in progress) - Total skipped: 3
2025-10-18 10:03:00 - PlaylistDownloader - INFO - [download] 100% of 2.1GiB
2025-10-18 10:03:00 - PlaylistDownloader - INFO - [download] Destination: downloads/Video5.mp4
2025-10-18 10:03:45 - PlaylistDownloader - INFO - [download] 100% of 2.0GiB
2025-10-18 10:03:45 - PlaylistDownloader - INFO - Successfully downloaded 5 new video(s)
2025-10-18 10:03:45 - DownloadScheduler - INFO - Check completed in 225.3 seconds

2025-10-18 10:04:00 - DownloadScheduler - INFO - Check #5 - 2025-10-18 10:04:00
2025-10-18 10:04:02 - PlaylistDownloader - INFO - No new videos found in playlist
2025-10-18 10:04:02 - DownloadScheduler - INFO - Check completed in 2.1 seconds

2025-10-18 10:05:00 - DownloadScheduler - INFO - Check #6 - 2025-10-18 10:05:00
2025-10-18 10:05:02 - PlaylistDownloader - INFO - No new videos found in playlist
2025-10-18 10:05:02 - DownloadScheduler - INFO - Check completed in 2.0 seconds
```

## Analysis

### What Happened

1. **Check #1** (00:00): Started downloading 5 videos
   - Lock acquired
   - Downloaded all 5 videos
   - Took 225 seconds (3 minutes 45 seconds)

2. **Check #2** (01:00): **SKIPPED**
   - Tried to acquire lock
   - Lock was held by Check #1
   - Immediately returned without waiting

3. **Check #3** (02:00): **SKIPPED**
   - Same as Check #2

4. **Check #4** (03:00): **SKIPPED**
   - Same as Check #2

5. **Check #5** (04:00): Started normally
   - Lock available (Check #1 completed at 03:45)
   - Lock acquired successfully
   - No new videos (all downloaded in Check #1)
   - Completed in 2 seconds

### Why This is Safe

1. **No Duplicates**: Check #1 downloaded all 5 videos and updated the archive
2. **No Corruption**: Only one process wrote to `.download_archive.txt`
3. **No Data Loss**: Checks #2, #3, #4 didn't need to run (no new videos)
4. **Resource Efficient**: Only one yt-dlp process at a time

### Statistics

- **Total checks attempted**: 6
- **Checks completed**: 3 (Check #1, #5, #6)
- **Checks skipped**: 3 (Check #2, #3, #4)
- **Videos downloaded**: 5 (all in Check #1)
- **Total download time**: 225 seconds
- **Longest wait**: 225 seconds (from Check #1 start to completion)

## Comparison: Without Lock Protection

If the system didn't have lock protection, here's what could happen:

```
❌ BAD: Without Lock Protection

00:00 - Check #1 starts downloading
01:00 - Check #2 ALSO starts downloading (same videos!)
02:00 - Check #3 ALSO starts downloading (same videos!)

Result:
- 3 concurrent yt-dlp processes
- Same videos downloaded 3 times
- Archive file corrupted (race condition)
- Wasted bandwidth and disk space
- Possible system overload
```

## Comparison: With Lock Protection (Our Implementation)

```
✓ GOOD: With Lock Protection

00:00 - Check #1 starts downloading (lock acquired)
01:00 - Check #2 skipped (lock held)
02:00 - Check #3 skipped (lock held)
03:45 - Check #1 completes (lock released)
04:00 - Check #5 starts (lock acquired)

Result:
✓ Only one yt-dlp process at a time
✓ Each video downloaded exactly once
✓ Archive file integrity maintained
✓ Efficient resource usage
✓ Clear, understandable logs
```

## When to Adjust Settings

### If You See Many Skips

```json
{
  "check_interval_seconds": 300  // Increase to 5 minutes
}
```

**Effect**: Fewer skipped checks, but slower to detect new videos

### If Downloads Are Always Fast

```json
{
  "check_interval_seconds": 30  // Decrease to 30 seconds
}
```

**Effect**: Faster detection of new videos, minimal skips

### For Large Playlists

```json
{
  "check_interval_seconds": 600  // 10 minutes
}
```

**Effect**: More time for long downloads to complete

## Key Takeaway

**Skipped checks are perfectly fine!** They mean the system is working correctly to prevent concurrent downloads. No data is lost, and new videos will be detected on the next successful check.
