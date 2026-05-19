---
name: bilibili-video-summary
description: Create local Markdown summaries for Bilibili, b23.tv, and YouTube videos by extracting metadata and subtitles/transcripts first, then having Codex write the summary and detailed notes. Use when the user asks to summarize, outline, extract key points from, or prepare notes for Bilibili/B-site/BV videos, b23.tv short links, or YouTube videos, especially when they want a local .md document.
---

# Bilibili Video Summary

Use this skill when the user gives a Bilibili, b23.tv, or YouTube video URL and asks for a summary, notes, outline, timeline, key points, or a local Markdown document. By default, create a local Markdown file unless the user explicitly asks for chat-only output.

## Workflow

1. Run the helper script to extract metadata and subtitles/transcripts to JSON.
2. Read the JSON output.
3. If `items[0].has_transcript` is true, use `items[0].transcript` to write the requested summary yourself.
4. If `items[0].has_transcript` is false for a Bilibili video, use the browser subtitle fallback before audio transcription:
   - Open the video page in the browser.
   - Start playback if needed.
   - Open the player subtitle menu, usually labelled `Subtitle`, `CC`, or Chinese `Zi Mu`.
   - Select a Chinese subtitle track when available, especially `Chinese AI` or `Zhongwen AI`.
   - Confirm that the player shows a message equivalent to "subtitles switched to Chinese".
   - Extract visible subtitle text from the page while the video plays, deduplicate repeated lines, and use the collected text as the transcript.
   - Mark the transcript source as `browser subtitle fallback` in the local Markdown file.
5. If the API, yt-dlp, and browser subtitle fallback all fail, use audio transcription with `--transcribe-audio`.
6. Save a local `.md` file by default. Include source URL, title, channel, duration, transcript source, summary, and detailed notes.
7. If audio transcription also fails, state that the video has no accessible subtitles and audio transcription failed. Do not pretend to have watched the video.

## Commands

Prefer Python directly because this skill is used on Windows as well as Unix-like systems:

```powershell
python scripts\summarize.py --url "https://www.bilibili.com/video/BV..." --include-transcript --output "$env:TEMP\video_summary.json"
```

For b23.tv links:

```powershell
python scripts\summarize.py --url "https://b23.tv/..." --include-transcript --output "$env:TEMP\video_summary.json"
```

For YouTube:

```powershell
python scripts\summarize.py --url "https://www.youtube.com/watch?v=..." --include-transcript --output "$env:TEMP\video_summary.json"
```

When subtitles are unavailable and a real transcript is still needed, run the audio transcription fallback:

```powershell
python scripts\summarize.py --url "https://www.bilibili.com/video/BV..." --include-transcript --transcribe-audio --asr-model base --output "$env:TEMP\video_summary.json"
```

Use `--asr-model small` for better Chinese transcription when speed and model download size are acceptable.

## Browser Subtitle Fallback

Use this only when the JSON output says `has_transcript: false` and the URL is a Bilibili page.

The goal is to recover subtitles that Bilibili exposes only in the player UI. Do not use this path when API subtitles are already available.

Suggested procedure:

1. Open the Bilibili URL in the browser automation tool.
2. Click play and wait until the player controls are visible.
3. Open the subtitle menu. It may appear as `Subtitle`, `CC`, or Chinese UI text for subtitles.
4. Select Chinese or Chinese AI subtitles if available. The UI may show entries similar to `Chinese`, `Chinese AI`, `Zhongwen`, or `Zhongwen AI`.
5. Verify subtitles appear over the video.
6. Collect subtitle text while playing:
   - Prefer DOM text extraction if the subtitle text is present in the page.
   - If DOM extraction does not expose the subtitle, use browser screenshots at short intervals and OCR only the subtitle region if an OCR tool is available.
   - Deduplicate consecutive repeated captions.
   - Stop when the video ends or enough transcript has been collected for the requested summary.
7. In the Markdown file, include `Transcript source: browser subtitle fallback`.

If the subtitle menu has no Chinese or AI subtitle track, stop and report that no accessible subtitle is available.

## Audio Transcription Fallback

Use this only after subtitle extraction and browser subtitle fallback have failed, or when the user explicitly asks to transcribe audio.

The helper script downloads the best available audio with `yt-dlp` and transcribes it locally with `faster-whisper`.

Recommended command:

```powershell
python scripts\summarize.py --url "<video-url>" --include-transcript --transcribe-audio --asr-model base --output "$env:TEMP\video_summary.json"
```

Notes:

- The first ASR run may download the Whisper model and can be slow.
- `base` is faster and smaller. `small` usually gives better Chinese results but is slower.
- The default language hint is `zh`. Use `--asr-language ""` only when the video is multilingual and automatic language detection is preferred.
- Temporary audio is deleted by default. Use `--audio-output-dir "<dir>"` only when the audio file should be kept for debugging.
- In the Markdown file, include `Transcript source: audio_asr`.

## Dependencies

Install once if needed:

```powershell
python -m pip install -r requirements.txt
```

The script needs `yt-dlp` on PATH. The Python package install normally provides the `yt-dlp` command.

Audio transcription also needs `faster-whisper`; it is included in `requirements.txt`.

## JSON Output

The output JSON has:

- `items[0].title`
- `items[0].url`
- `items[0].source`
- `items[0].channel`
- `items[0].duration`
- `items[0].has_transcript`
- `items[0].transcript` when `--include-transcript` is used and subtitles are available
- `items[0].metadata`
- `items[0].metadata.transcript_source`, such as `subtitle_api`, `yt_dlp_subtitle`, `browser subtitle fallback`, `audio_asr`, or `none`

## Markdown Output Style

Write in Chinese by default. In the generated Markdown, do not use English section titles or field labels. Use Chinese headings and field labels throughout, and convert raw source keys like `subtitle_api` or `audio_asr` into human-readable Chinese.

Structure the output with local-language section titles for video info, summary, detailed content, and reusable points.

In the info block, use local-language labels for source, link, BV ID, title, channel, duration, publish date, transcript source, and note.

For technical videos, explicitly extract:

- Problem statement
- Inputs and outputs
- Key method or mechanism
- Metrics or evaluation criteria
- Baselines or comparison points
- Open questions to verify from the transcript

## Limits

Bilibili videos without public subtitles can still be summarized through audio transcription, but ASR quality depends on audio clarity, language, background music, and model size. If subtitles and ASR both fail, ask the user for a subtitle file or transcript.
