# Next Steps & Feature Proposals

---

## 1. Speaker Diarization Pipeline with LLM-Refined Transcript & AI Summary

**Goal:** After a video is downloaded, automatically run a speaker diarization pipeline to identify who is speaking when, produce a speaker-labeled transcript, refine it through an LLM, and generate an AI summary. Optionally integrate with ComfyUI for a visual/node-based workflow.

---

### What needs to happen

1. Extract audio from the downloaded `.mp4`
2. Run diarization to segment audio by speaker
3. Run speech-to-text (ASR) to produce a raw transcript, aligned to diarization segments
4. Pass the speaker-labeled transcript to an LLM for cleaning/refinement and summarization
5. Write outputs (refined transcript, summary) alongside the video file

---

### Option A — `pyannote.audio` + `whisper` (fully local)

**Stack:** `pyannote/speaker-diarization-3.1` (HuggingFace), `openai-whisper` or `faster-whisper`

```
audio.mp4
  └─► ffmpeg extract ──► pyannote diarization ──► speaker segments
                     └─► whisper transcription ──► word-level timestamps
                                                         │
                                               align segments + speakers
                                                         │
                                               LLM refine + summarize
                                                         │
                                          transcript.txt / summary.txt
```

**Pros:** Fully local, no API cost, works offline.  
**Cons:** Requires HuggingFace token + model license acceptance, GPU strongly recommended, setup is non-trivial.

**Key packages:** `pyannote.audio`, `faster-whisper`, `torch`

---

### Option B — `whisperX` (alignment-first, easiest local path)

`whisperX` performs ASR, word-level forced alignment, and speaker diarization in a single library call.

```python
import whisperx

model = whisperx.load_model("large-v2", device="cuda")
result = model.transcribe("audio.mp4")
result = whisperx.align(result["segments"], ...)
diarize_model = whisperx.DiarizationPipeline(use_auth_token=HF_TOKEN)
diarize_segments = diarize_model("audio.mp4")
result = whisperx.assign_word_speakers(diarize_segments, result)
```

**Pros:** Single library, actively maintained, best accuracy/speed tradeoff.  
**Cons:** Still needs HuggingFace token + GPU for large files.

---

### Option C — AssemblyAI API (easiest managed path)

AssemblyAI provides ASR + diarization as a single API call with no local GPU required.

```python
import assemblyai as aai
aai.settings.api_key = "..."
config = aai.TranscriptionConfig(speaker_labels=True)
transcript = aai.Transcriber().transcribe("audio.mp4", config)
for utt in transcript.utterances:
    print(f"Speaker {utt.speaker}: {utt.text}")
```

**Pros:** Zero local setup, high accuracy, handles long audio well.  
**Cons:** Per-minute cost, audio leaves local machine.

---

### Option D — ComfyUI Integration (visual pipeline orchestration)

Use ComfyUI as the workflow engine, with custom nodes wrapping the diarization and LLM steps. This fits naturally if ComfyUI is already in use for other media processing.

**Approach:**
- Create a `LoadAudioFromVideo` custom node (ffmpeg wrapper)
- Create a `DiarizationNode` wrapping `whisperX` or pyannote
- Create a `LLMRefineTranscript` node calling Claude/Gemini/local LLM
- Create a `SaveTranscriptFiles` node writing outputs to the download folder

Each downloaded video triggers the ComfyUI workflow via its REST API (`POST /prompt`).

**Pros:** Visual, reusable, composable with image/video nodes already in ComfyUI.  
**Cons:** Significant custom node development; ComfyUI not designed for audio-primary workflows.

---

### LLM Refinement & Summary Step (applies to all options)

Once you have a raw speaker-labeled transcript, pass it to an LLM:

```python
prompt = f"""
You are given a raw speaker-diarized transcript. 
1. Clean filler words and fix ASR errors.
2. Preserve speaker labels (SPEAKER_00, SPEAKER_01, etc.) or rename them if identifiable.
3. Output a clean transcript followed by a 3–5 sentence summary.

Transcript:
{raw_transcript}
"""
```

Model choices: `claude-sonnet-4-6` (via Anthropic SDK), Gemini 1.5 Pro (large context), local `ollama` (Llama 3 / Mistral).

**Output files to write alongside each video:**
- `<video_id>_transcript.txt` — refined speaker-labeled transcript
- `<video_id>_summary.txt` — AI summary
- Optionally inject summary into the `.info.json` metadata file

---

### Integration point in this repo

Hook into `downloader.py` post-download, or add a new `post_processor.py` module called from `scheduler.py` after each successful download.

---

---

## 2. Gemini API AI Summary

**Goal:** After download, send video content (or transcript/description) to Gemini API and get back an AI-generated summary, stored with the video.

---

### Option A — Gemini on transcript / description text (cheapest)

Use the already-downloaded `.description` and/or subtitle `.vtt` file as input. No video upload needed.

```python
import google.generativeai as genai

genai.configure(api_key="GEMINI_API_KEY")
model = genai.GenerativeModel("gemini-1.5-pro")

with open(f"{video_id}.en.vtt") as f:
    subtitles = f.read()
with open(f"{video_id}.description") as f:
    description = f.read()

response = model.generate_content(
    f"Summarize this video based on its subtitles and description.\n\n"
    f"Description:\n{description}\n\nSubtitles:\n{subtitles}"
)
summary = response.text
```

**Pros:** Fast, cheap, no video upload, works with existing downloaded files.  
**Cons:** Quality limited by auto-subtitle accuracy; no visual context.

---

### Option B — Gemini native video understanding (best quality)

Gemini 1.5 Pro / 2.0 Flash support direct video file input via the File API.

```python
import google.generativeai as genai

genai.configure(api_key="GEMINI_API_KEY")
video_file = genai.upload_file(path="video.mp4", mime_type="video/mp4")

# Wait for processing
while video_file.state.name == "PROCESSING":
    video_file = genai.get_file(video_file.name)

model = genai.GenerativeModel("gemini-1.5-pro")
response = model.generate_content([
    video_file,
    "Provide a detailed summary of this video. Include key topics, speakers if identifiable, and main takeaways."
])
summary = response.text
```

**Pros:** Understands visual content, timestamps, on-screen text; best summary quality.  
**Cons:** Uploads video to Google, costs scale with video length, slower.

---

### Option C — Gemini on `.info.json` structured metadata

The `write_info_json` option already saves rich metadata (title, description, chapters, tags, upload date). Feed this structured data to Gemini for a context-aware summary without touching audio/video.

```python
import json
with open(f"{video_id}.info.json") as f:
    info = json.load(f)

prompt = f"""
Video title: {info['title']}
Channel: {info['uploader']}
Description: {info['description']}
Chapters: {info.get('chapters', [])}
Tags: {info.get('tags', [])}

Generate a concise summary and list of key topics.
"""
```

**Pros:** Zero extra downloads, structured input, very cheap.  
**Cons:** Summary is only as good as the description the uploader wrote.

---

### Config additions

```json
"gemini": {
  "enabled": true,
  "api_key_env": "GEMINI_API_KEY",
  "model": "gemini-1.5-pro",
  "input_source": "subtitles+description",
  "output_file_suffix": "_gemini_summary.txt"
}
```

---

---

## 3. Inject Video Description into File Metadata

**Goal:** Take the video description (already saved as a `.description` file by yt-dlp) and write it into the video file's embedded metadata so it travels with the file.

---

### Option A — `ffmpeg` metadata injection (simplest, most portable)

Write a `ffmpeg` post-processing step that embeds the description as the `comment` (or `description`) tag in the MP4 container.

```python
import subprocess

def inject_description_to_metadata(video_path: str, description: str):
    tmp_path = video_path.replace(".mp4", "_meta.mp4")
    subprocess.run([
        "ffmpeg", "-i", video_path,
        "-metadata", f"comment={description}",
        "-metadata", f"description={description}",
        "-codec", "copy",          # stream copy — no re-encode
        tmp_path
    ], check=True)
    os.replace(tmp_path, video_path)
```

**Container tag mapping:**
| Container | Tag name      | Visible in |
|-----------|--------------|------------|
| MP4/M4V   | `description` / `comment` | Finder, VLC, Infuse |
| MKV       | `DESCRIPTION` | VLC, Plex |
| MP3       | `comment`     | iTunes, foobar2000 |

**Pros:** No extra dependencies beyond ffmpeg (already a yt-dlp dependency), lossless stream copy.  
**Cons:** Creates a temporary file; descriptions with special characters need escaping.

---

### Option B — `mutagen` Python library (pure Python, no ffmpeg subprocess)

```python
from mutagen.mp4 import MP4

def inject_description_mutagen(video_path: str, description: str):
    tags = MP4(video_path)
    tags["\xa9cmt"] = [description]   # comment atom
    tags["desc"] = [description]       # iTunes description atom
    tags.save()
```

**Pros:** No subprocess, modifies in-place, handles edge cases well.  
**Cons:** `mutagen` MP4 support is read/write but not all players read `desc` tag.

---

### Option C — yt-dlp `--parse-metadata` / `--embed-metadata` (zero extra code)

yt-dlp can map fields to metadata tags natively during download, avoiding any post-processing step.

Add to `yt_dlp_options` in `config.json`:

```json
"embed_metadata": true,
"parse_metadata": [
  "description:(?s)(?P<meta_comment>.+)"
]
```

This maps the full description into the `comment` metadata field at download time.

**Pros:** No code changes, handled entirely by yt-dlp, no temp files.  
**Cons:** Limited control over which tags are written; long descriptions may be truncated by some containers.

---

### Option D — Inject into `.info.json` and Plex/Jellyfin NFO sidecar

For media server users, write a `.nfo` XML sidecar that Plex/Jellyfin/Kodi reads:

```python
from xml.etree.ElementTree import Element, SubElement, tostring
import pathlib

def write_nfo(video_path: str, info: dict):
    root = Element("movie")
    SubElement(root, "title").text = info["title"]
    SubElement(root, "plot").text = info["description"]
    SubElement(root, "year").text = info["upload_date"][:4]
    SubElement(root, "studio").text = info["uploader"]
    nfo_path = pathlib.Path(video_path).with_suffix(".nfo")
    nfo_path.write_bytes(tostring(root, encoding="utf-8", xml_declaration=True))
```

**Pros:** Works with all major media servers without touching the video file.  
**Cons:** Separate sidecar file; not embedded in the video container.

---

### Recommended combination

Use **Option C** (yt-dlp native) as the zero-effort baseline, and add **Option A** (ffmpeg) as an optional post-processor for cases where the native approach falls short or more control is needed over tag placement.

---

## Integration Overview

All three features slot naturally into a `post_processor.py` module:

```
download complete (downloader.py)
        │
        ▼
post_processor.py
  ├── inject_description_metadata()   ← Feature 3
  ├── run_diarization_pipeline()      ← Feature 1
  └── run_gemini_summary()            ← Feature 2
        │
        ▼
  outputs written alongside video file
```

Each feature is independently toggleable via `config.json` flags.
