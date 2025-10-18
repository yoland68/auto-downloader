# Concurrency and Download Overlap Handling

## The Problem

When monitoring a playlist every 60 seconds, what happens if a download from the previous check is still ongoing when the next check is scheduled?

### Example Scenario

```
Time 00:00 - Check #1 starts, finds 5 large videos (10 GB total)
Time 00:60 - Download still in progress (only 2 videos done)
            - Check #2 is triggered by scheduler
Time 01:20 - Download still in progress (4 videos done)
            - Check #3 is triggered by scheduler
Time 02:00 - Check #1 finally completes
```

Without proper handling, this could cause:
- **Concurrent downloads** of the same playlist
- **Race conditions** on the archive file
- **Duplicate downloads** (archive not updated yet)
- **Resource exhaustion** (multiple yt-dlp processes)
- **Corrupted archive file** (simultaneous writes)

## The Solution: Thread-Safe Locking

The scheduler uses a **non-blocking lock mechanism** to prevent concurrent downloads:

```python
from threading import Lock

self.download_lock = Lock()  # Mutual exclusion lock
self.is_downloading = False  # Status flag
self.skipped_checks = 0      # Statistics
```

### How It Works

1. **Lock Attempt**: Each scheduled check tries to acquire the lock
2. **Non-Blocking**: If lock is held, check is immediately skipped
3. **Protected Execution**: Only one download runs at a time
4. **Clean Release**: Lock always released (even on errors)

### Implementation

```python
def download_job(self):
    # Try to acquire lock WITHOUT blocking
    if not self.download_lock.acquire(blocking=False):
        # Previous download still running - skip this check
        self.skipped_checks += 1
        self.logger.warning(
            f"Check #{self.check_count} - SKIPPED (previous download still in progress)"
        )
        return

    try:
        self.is_downloading = True
        start_time = time.time()

        # Safe to download - we have the lock
        self.downloader.download()

        duration = time.time() - start_time
        self.logger.info(f"Check completed in {duration:.1f} seconds")

    finally:
        # ALWAYS release lock, even if error occurs
        self.is_downloading = False
        self.download_lock.release()
```

## Behavior Examples

### Example 1: Fast Downloads (Normal Case)

```
00:00 - Check #1 starts → Lock acquired
00:15 - Check #1 completes (15 seconds) → Lock released
00:60 - Check #2 starts → Lock acquired ✓
01:15 - Check #2 completes → Lock released
02:00 - Check #3 starts → Lock acquired ✓
```

**Result**: All checks run successfully. No skips.

### Example 2: Slow Download (Long Download)

```
00:00 - Check #1 starts → Lock acquired
00:60 - Check #2 tries → Lock HELD → SKIP ⚠
01:20 - Check #3 tries → Lock HELD → SKIP ⚠
01:50 - Check #1 completes (110 seconds) → Lock released
02:00 - Check #4 starts → Lock acquired ✓
```

**Result**: Checks #2 and #3 skipped. System remains stable.

**Log Output**:
```
2025-10-18 10:00:00 - Check #1 - 2025-10-18 10:00:00
2025-10-18 10:01:00 - Check #2 - SKIPPED (previous download still in progress) - Total skipped: 1
2025-10-18 10:01:50 - Check completed in 110.3 seconds
2025-10-18 10:02:00 - Check #3 - 2025-10-18 10:02:00
```

### Example 3: Very Large Playlist

```
00:00 - Check #1 starts (100 videos to download)
01:00 - Check #2 SKIPPED
02:00 - Check #3 SKIPPED
03:00 - Check #4 SKIPPED
...
20:00 - Check #1 completes (20 minutes)
20:00 - Check #21 starts → Lock acquired ✓
```

**Result**: 19 checks skipped, but system stable. Videos downloaded correctly.

## Advantages of This Approach

### 1. **Prevents Corruption**
- Only one process writes to archive file at a time
- No race conditions on file system
- Archive integrity guaranteed

### 2. **Resource Efficient**
- No redundant downloads
- Single yt-dlp process at a time
- Controlled resource usage

### 3. **Clear Logging**
- Explicit "SKIPPED" warnings in logs
- Track how many checks were skipped
- Duration tracking for performance monitoring

### 4. **Fail-Safe**
- Lock always released (try-finally block)
- Errors don't deadlock the system
- Recovery automatic on next check

### 5. **No Data Loss**
- Skipped checks don't matter - next successful check finds new videos
- yt-dlp checks entire playlist each time
- Archive prevents duplicates

## Monitoring

### Check Logs for Skipped Checks

```bash
grep "SKIPPED" downloader.log
```

Example output:
```
2025-10-18 10:01:00 - Check #2 - SKIPPED (previous download still in progress) - Total skipped: 1
2025-10-18 10:02:00 - Check #3 - SKIPPED (previous download still in progress) - Total skipped: 2
```

### View Check Duration

```bash
grep "Check completed" downloader.log
```

Example output:
```
2025-10-18 10:00:45 - Check completed in 45.2 seconds
2025-10-18 10:02:15 - Check completed in 75.8 seconds
2025-10-18 10:03:20 - Check completed in 125.3 seconds  ← Long download
```

### Summary Statistics on Shutdown

When you stop the scheduler (Ctrl+C), you'll see:
```
Scheduler stopped.
Total checks performed: 156
Checks skipped due to long downloads: 12
```

## When Skips Happen

Checks are skipped when:

1. **Large Videos**: Downloading 4K videos or long content
2. **Many Videos**: Playlist has many new videos at once
3. **Slow Network**: Limited bandwidth or network issues
4. **System Resources**: Heavy CPU/disk usage from other processes

## Is Skipping Checks a Problem?

**No!** Skipped checks are **perfectly fine** because:

1. **Complete Coverage**: Each check examines the entire playlist
2. **Archive Protection**: Already-downloaded videos are tracked
3. **Next Check**: Will catch any videos missed during skipped checks
4. **No Duplicates**: Archive prevents re-downloading

### Example

```
Playlist: [Video A, Video B, Video C, Video D]

10:00 - Check #1 starts, downloads Video A (takes 3 minutes)
10:01 - Check #2 SKIPPED
10:02 - Check #3 SKIPPED
10:03 - Check #1 completes
        Archive: [Video A]

10:03 - Check #4 runs
        Finds: Video B, C, D (all new)
        Downloads: B, C, D
        Archive: [Video A, B, C, D]
```

**Result**: All videos downloaded, no duplicates, no data loss.

## Tuning Check Interval

If you see many skipped checks, consider adjusting the interval:

### Option 1: Increase Check Interval

Edit `config.json`:
```json
{
  "check_interval_seconds": 300  // Check every 5 minutes instead of 1
}
```

**Pros**: Fewer skipped checks
**Cons**: Slower detection of new videos

### Option 2: Keep Short Interval

```json
{
  "check_interval_seconds": 60  // Keep at 1 minute
}
```

**Pros**: Fast detection of new videos
**Cons**: May skip checks during large downloads
**Note**: This is fine! No data loss occurs.

## Technical Details

### Thread Safety

The `threading.Lock` provides:
- **Mutual Exclusion**: Only one thread holds lock at a time
- **Memory Barriers**: Ensures visibility across threads
- **Re-entrant Safety**: Same thread can't deadlock itself

### Non-Blocking Acquisition

```python
acquire(blocking=False)
```

- Returns `True` if lock acquired
- Returns `False` if lock already held
- Never blocks or waits
- Immediate decision

### Alternative: Blocking Acquisition (Not Used)

```python
acquire(blocking=True)  # Would wait indefinitely
```

We **don't use this** because:
- Would queue up multiple checks
- Waste resources waiting
- No benefit (yt-dlp checks full playlist anyway)

## Edge Cases Handled

### 1. Error During Download

```python
try:
    self.downloader.download()
except Exception as e:
    self.logger.error(f"Error: {e}")
finally:
    self.download_lock.release()  # Lock ALWAYS released
```

### 2. Shutdown During Download

```python
def _signal_handler(self, signum, frame):
    self.running = False
    # Note: Current download completes naturally
    # Lock released in finally block
```

### 3. Multiple Schedulers (Same Config)

If you run multiple scheduler instances with the same config:
- **File-level race conditions** still possible
- **Solution**: Use different archive files per instance
- **Better**: One scheduler per playlist

Example:
```bash
# Terminal 1
python3 scheduler.py --config playlist1.json

# Terminal 2
python3 scheduler.py --config playlist2.json
```

## Best Practices

### 1. Monitor Logs

Check for excessive skipping:
```bash
tail -f downloader.log | grep SKIPPED
```

If seeing many skips, increase `check_interval_seconds`.

### 2. Right-Size Interval

**For small playlists** (< 10 videos, < 1 GB):
```json
{"check_interval_seconds": 60}  // 1 minute is fine
```

**For large playlists** (100+ videos, > 10 GB):
```json
{"check_interval_seconds": 300}  // 5 minutes more appropriate
```

### 3. Network Considerations

**Fast connection** (100+ Mbps):
- Downloads complete quickly
- Short interval (60s) works well

**Slow connection** (< 10 Mbps):
- Downloads take longer
- Longer interval (300-600s) recommended

### 4. Disk Space

Monitor available space:
```bash
df -h /path/to/downloads
```

If downloads fail due to space, they'll be retried on next successful check.

## Summary

The concurrency handling ensures:

✓ **Safe**: No concurrent downloads
✓ **Stable**: No deadlocks or resource exhaustion
✓ **Reliable**: No data corruption or duplicate downloads
✓ **Transparent**: Clear logging of skipped checks
✓ **Automatic**: No manual intervention needed
✓ **Fail-Safe**: Errors don't break the system

**Bottom Line**: You can safely set a short check interval (60 seconds) knowing that the system will handle long downloads gracefully by skipping checks as needed.
