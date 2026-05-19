#!/usr/bin/env python3
"""
Video transcript helper for YouTube and Bilibili.

Usage:
  python scripts/summarize.py --url "https://www.bilibili.com/video/BV..." --include-transcript
  python scripts/summarize.py --url "https://youtube.com/watch?v=VIDEO_ID" --include-transcript
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile
import re
import locale
import shutil
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Default config
DEFAULT_MIN_DURATION = 300  # 5 minutes (filter Shorts)
DEFAULT_HOURS_LOOKBACK = 24
DEFAULT_MAX_VIDEOS_PER_CHANNEL = 5
DEFAULT_OUTPUT = str(Path(tempfile.gettempdir()) / "video_summary.json")
DEFAULT_ASR_MODEL = "base"

def decode_process_output(data: bytes) -> str:
    """Decode subprocess bytes robustly on Windows and Unix."""
    encodings = ["utf-8", locale.getpreferredencoding(False), "gb18030", "utf-8-sig"]
    seen = set()
    for encoding in encodings:
        if not encoding or encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def ytdlp_env() -> Dict[str, str]:
    """Force yt-dlp subprocesses to emit UTF-8 on Windows consoles."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def is_bilibili_url(url: str) -> bool:
    """Return True for bilibili.com and b23.tv URLs."""
    host = urlparse(url).netloc.lower()
    return "bilibili.com" in host or host.endswith("b23.tv")


def is_youtube_url(url: str) -> bool:
    """Return True for common YouTube URL hosts."""
    host = urlparse(url).netloc.lower()
    return "youtube.com" in host or host.endswith("youtu.be")


def extract_youtube_id(url: str) -> Optional[str]:
    """Extract a YouTube video id from watch, short, embed, or share URLs."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host.endswith("youtu.be"):
        return parsed.path.strip("/").split("/")[0] or None

    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if query_id:
        return query_id

    match = re.search(r"/(?:shorts|embed|live)/([^/?#]+)", parsed.path)
    if match:
        return match.group(1)

    return None


def run_ytdlp_json(url: str, timeout: int = 60) -> Optional[Dict[str, Any]]:
    """Fetch video metadata with yt-dlp."""
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--no-warnings",
                "--skip-download",
                "-J",
                url,
            ],
            capture_output=True,
            env=ytdlp_env(),
            timeout=timeout,
        )

        if result.returncode != 0:
            stderr = decode_process_output(result.stderr)
            print(f"[WARN] yt-dlp metadata error: {stderr[:300]}", file=sys.stderr)
            return None

        return json.loads(decode_process_output(result.stdout))
    except FileNotFoundError:
        print("[WARN] yt-dlp not found. Install dependencies first.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] yt-dlp metadata exception: {e}", file=sys.stderr)
        return None


def format_duration(seconds: Optional[int]) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    if not seconds:
        return "Unknown"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def normalize_video_details(info: Dict[str, Any], source_url: str) -> Dict[str, Any]:
    """Normalize yt-dlp metadata across YouTube and Bilibili."""
    duration = info.get("duration") or 0
    webpage_url = info.get("webpage_url") or source_url
    channel = info.get("channel") or info.get("uploader") or info.get("artist") or "Unknown"

    return {
        "video_id": info.get("id") or extract_youtube_id(source_url) or source_url,
        "title": info.get("title") or "Unknown",
        "url": webpage_url,
        "channel": channel,
        "duration_seconds": duration,
        "duration": format_duration(duration),
        "description": (info.get("description") or "")[:1000],
        "published": info.get("upload_date") or info.get("timestamp") or "",
        "view_count": info.get("view_count", 0),
        "like_count": info.get("like_count", 0),
        "extractor": info.get("extractor_key") or info.get("extractor") or "",
    }


def extract_bvid(url_or_text: str) -> Optional[str]:
    """Extract a Bilibili BV id from a URL or raw text."""
    match = re.search(r"(BV[0-9A-Za-z]+)", url_or_text)
    return match.group(1) if match else None


def get_channel_videos(channel_id: str, hours: int, max_videos: int) -> List[Dict]:
    """Get recent videos from a YouTube channel using yt-dlp"""
    videos = []
    
    # Build channel URL
    if channel_id.startswith("UC") and len(channel_id) == 24:
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
    elif channel_id.startswith("http"):
        url = channel_id.rstrip("/") + "/videos"
    else:
        url = f"https://www.youtube.com/@{channel_id}/videos"
    
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--flat-playlist",
                "--no-warnings",
                "-J",
                "--playlist-end", str(max_videos * 2),
                url,
            ],
            capture_output=True,
            env=ytdlp_env(),
            timeout=45,
        )
        
        if result.returncode != 0:
            stderr = decode_process_output(result.stderr)
            print(f"[WARN] yt-dlp error for {channel_id}: {stderr[:100]}", file=sys.stderr)
            return []
        
        data = json.loads(decode_process_output(result.stdout))
        entries = data.get("entries", [])
        
        for entry in entries:
            if not entry:
                continue
            
            video_id = entry.get("id")
            if not video_id:
                continue
            
            # Filter Shorts by duration
            if entry.get("duration") and entry.get("duration") < DEFAULT_MIN_DURATION:
                continue
            
            videos.append({
                "id": video_id,
                "title": entry.get("title", "Unknown"),
                "channel": entry.get("channel", entry.get("uploader", "Unknown")),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "duration_hint": entry.get("duration"),
            })
            
            if len(videos) >= max_videos:
                break
        
    except Exception as e:
        print(f"[WARN] Error fetching channel {channel_id}: {e}", file=sys.stderr)
    
    return videos


def get_video_details(video_id: str) -> Optional[Dict]:
    """Get detailed video metadata using yt-dlp"""
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--no-warnings",
                "-j",
                "--no-download",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            env=ytdlp_env(),
            timeout=20,
        )
        
        if result.returncode != 0:
            return None
        
        data = json.loads(decode_process_output(result.stdout))
        duration = data.get("duration", 0)
        
        return {
            "duration_seconds": duration,
            "duration": f"{duration // 60}:{duration % 60:02d}",
            "description": data.get("description", "")[:1000],
            "published": data.get("upload_date", ""),
            "view_count": data.get("view_count", 0),
            "like_count": data.get("like_count", 0),
        }
        
    except Exception:
        return None


def get_transcript(video_id: str) -> Optional[str]:
    """Get video transcript using multiple methods to avoid rate limiting"""
    # Method 1: innertube ANDROID client + Cloudflare proxy (bypasses rate limits)
    transcript = _get_transcript_innertube_proxy(video_id)
    if transcript:
        return transcript
    
    # Method 2: youtube-transcript-api (fallback, may be rate limited)
    transcript = _get_transcript_ytapi(video_id)
    if transcript:
        return transcript
    
    return None


# Cloudflare Workers proxy for downloading caption XML (bypasses 429 rate limits)
CF_PROXY_URL = 'https://your-cloudflare-proxy.workers.dev/?url='  # Optional: Cloudflare Workers proxy to bypass rate limits


def _parse_caption_xml(xml_text: str) -> List[str]:
    """Parse YouTube caption XML (supports multiple formats)"""
    import xml.etree.ElementTree as ET
    import html as html_mod
    
    try:
        root = ET.fromstring(xml_text)
        texts = []
        
        # Try <p> tags first (format 3 and format 2)
        for p in root.findall('.//p'):
            # Check for <s> child tags (format 3: word-level)
            words = []
            for s in p.findall('s'):
                if s.text:
                    words.append(html_mod.unescape(s.text.strip()))
            if words:
                texts.append(' '.join(words))
            elif p.text:  # format 2: direct text
                texts.append(html_mod.unescape(p.text.strip()))
        
        # If no <p> found, try <text> tags (format 1)
        if not texts:
            for elem in root.findall('.//text'):
                if elem.text:
                    texts.append(html_mod.unescape(elem.text.strip()))
        
        return texts
    except Exception:
        return []


def _download_caption(url: str) -> Optional[str]:
    """Download caption content, try proxy first then direct"""
    import urllib.parse
    import requests
    
    # 1. Through Cloudflare proxy
    try:
        proxied = CF_PROXY_URL + urllib.parse.quote(url, safe='')
        r = requests.get(proxied, timeout=15)
        if r.status_code == 200 and r.text.strip():
            return r.text
    except Exception:
        pass
    
    # 2. Direct connection fallback
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.text.strip():
            return r.text
    except Exception:
        pass
    
    return None


def _get_transcript_innertube_proxy(video_id: str) -> Optional[str]:
    """Method 1: innertube ANDROID client + CF proxy to download captions"""
    try:
        import innertube
        
        client = innertube.InnerTube('ANDROID')
        data = client.player(video_id=video_id)
        
        if 'captions' not in data:
            return None
        
        caps = data['captions']['playerCaptionsTracklistRenderer']['captionTracks']
        if not caps:
            return None
        
        # Priority: en > zh-Hans > zh > first available
        cap_url = None
        for prefer in ['en', 'zh-Hans', 'zh']:
            for c in caps:
                if c.get('languageCode') == prefer:
                    cap_url = c['baseUrl']
                    break
            if cap_url:
                break
        if not cap_url:
            cap_url = caps[0]['baseUrl']
        
        xml_text = _download_caption(cap_url)
        if not xml_text:
            return None
        
        texts = _parse_caption_xml(xml_text)
        if not texts:
            return None
        
        result = ' '.join(texts).strip()
        return result if len(result) > 50 else None
        
    except Exception:
        return None


def _get_transcript_ytapi(video_id: str) -> Optional[str]:
    """Method 2 (fallback): youtube-transcript-api direct connection"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=["zh-Hans", "zh-Hant", "en"])
        transcript = " ".join([item["text"] for item in fetched])
        return transcript if len(transcript) > 50 else None
        
    except Exception:
        return None


def _extract_plain_text_from_subtitle_file(path: Path) -> str:
    """Extract readable subtitle text from vtt, srt, ass, json, or plain text."""
    content = path.read_text(encoding="utf-8", errors="ignore")
    suffix = path.suffix.lower()

    if suffix == ".json":
        try:
            data = json.loads(content)
            body = data.get("body", []) if isinstance(data, dict) else []
            texts = []
            for item in body:
                if isinstance(item, dict):
                    text = item.get("content") or item.get("text") or ""
                    if text:
                        texts.append(str(text).strip())
            if texts:
                return " ".join(texts)
        except Exception:
            pass

    lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith(("WEBVTT", "NOTE", "STYLE")):
            continue
        if "-->" in line:
            continue
        if line.isdigit():
            continue
        if suffix == ".ass" and (line.startswith("[") or line.startswith("Format:")):
            continue
        if suffix == ".ass" and line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            if len(parts) == 10:
                line = parts[-1]
        line = re.sub(r"<[^>]+>", "", line)
        line = line.replace("\\N", " ").replace("\\n", " ")
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)

    return " ".join(lines)


def get_subtitle_with_ytdlp(url: str) -> Optional[str]:
    """Download available manual/auto subtitles with yt-dlp and return plain text."""
    with tempfile.TemporaryDirectory(prefix="video-summary-") as tmp:
        output_tmpl = str(Path(tmp) / "subtitle.%(ext)s")
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "zh-Hans,zh-CN,zh,zh-Hant,en.*",
            "--sub-format",
            "json3/vtt/srt/ass/best",
            "-o",
            output_tmpl,
            url,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                env=ytdlp_env(),
                timeout=90,
            )
        except FileNotFoundError:
            print("[WARN] yt-dlp not found. Install dependencies first.", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[WARN] Subtitle download exception: {e}", file=sys.stderr)
            return None

        if result.returncode != 0:
            stderr = decode_process_output(result.stderr)
            print(f"[WARN] Subtitle download error: {stderr[:300]}", file=sys.stderr)

        subtitle_files = sorted(
            [p for p in Path(tmp).glob("subtitle.*") if p.is_file()],
            key=lambda p: (
                0 if any(lang in p.name.lower() for lang in ["zh", "chs", "hans"]) else 1,
                p.suffix.lower() not in [".json", ".vtt", ".srt", ".ass"],
                p.name,
            ),
        )

        for file_path in subtitle_files:
            transcript = _extract_plain_text_from_subtitle_file(file_path)
            if len(transcript) > 50:
                return transcript

    return None


def download_audio(url: str, output_dir: Optional[str] = None) -> Optional[Path]:
    """Download the best available audio stream with yt-dlp."""
    temp_created = False
    if output_dir:
        work_dir = Path(output_dir)
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="video-summary-audio-"))
        temp_created = True

    work_dir.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in work_dir.iterdir() if p.is_file()}
    output_tmpl = str(work_dir / "audio-%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "-f",
        "bestaudio/best",
        "-o",
        output_tmpl,
        url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            env=ytdlp_env(),
            timeout=900,
        )
    except FileNotFoundError:
        print("[WARN] yt-dlp not found. Install dependencies first.", file=sys.stderr)
        if temp_created:
            shutil.rmtree(work_dir, ignore_errors=True)
        return None
    except Exception as e:
        print(f"[WARN] Audio download exception: {e}", file=sys.stderr)
        if temp_created:
            shutil.rmtree(work_dir, ignore_errors=True)
        return None

    if result.returncode != 0:
        stderr = decode_process_output(result.stderr)
        print(f"[WARN] Audio download error: {stderr[:300]}", file=sys.stderr)
        if temp_created:
            shutil.rmtree(work_dir, ignore_errors=True)
        return None

    audio_files = [
        p for p in work_dir.iterdir()
        if p.is_file()
        and p.name not in existing
        and not p.name.endswith((".part", ".ytdl"))
    ]
    if not audio_files:
        audio_files = [
            p for p in work_dir.glob("audio-*")
            if p.is_file() and not p.name.endswith((".part", ".ytdl"))
        ]

    if not audio_files:
        print("[WARN] Audio download finished but no audio file was found.", file=sys.stderr)
        if temp_created:
            shutil.rmtree(work_dir, ignore_errors=True)
        return None

    audio_path = max(audio_files, key=lambda p: p.stat().st_size)
    print(f"  [OK] Audio downloaded: {audio_path}")
    return audio_path


def transcribe_audio(audio_path: Path, model_name: str = DEFAULT_ASR_MODEL, language: Optional[str] = "zh") -> Optional[str]:
    """Transcribe an audio file with faster-whisper."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "[WARN] faster-whisper is not installed. Run: python -m pip install -r "
            "C:\\Users\\Roxy\\.codex\\skills\\bilibili-video-summary\\requirements.txt",
            file=sys.stderr,
        )
        return None

    try:
        print(f"[INFO] Transcribing audio with faster-whisper model: {model_name}")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            str(audio_path),
            language=language or None,
            vad_filter=True,
        )
        texts = []
        for segment in segments:
            text = (segment.text or "").strip()
            if text:
                texts.append(text)
        transcript = " ".join(texts).strip()
        return transcript if len(transcript) > 50 else None
    except Exception as e:
        print(f"[WARN] Audio transcription exception: {e}", file=sys.stderr)
        return None


def transcribe_url_audio(
    url: str,
    model_name: str = DEFAULT_ASR_MODEL,
    audio_output_dir: Optional[str] = None,
    language: Optional[str] = "zh",
) -> Optional[str]:
    """Download a video's audio, transcribe it, and clean up temporary audio."""
    audio_path = download_audio(url, audio_output_dir)
    if not audio_path:
        return None
    try:
        return transcribe_audio(audio_path, model_name=model_name, language=language)
    finally:
        if not audio_output_dir:
            shutil.rmtree(audio_path.parent, ignore_errors=True)


def get_bilibili_official_subtitle(url: str, info: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Fetch Bilibili official/AI subtitles through public web APIs."""
    import requests

    bvid = extract_bvid(url)
    cid = (info or {}).get("cid")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": url,
    }

    try:
        if not bvid:
            view_url = (info or {}).get("webpage_url") or url
            bvid = extract_bvid(view_url)
        if not bvid:
            return None

        if not cid:
            view_resp = requests.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
                headers=headers,
                timeout=20,
            )
            view_data = view_resp.json()
            if view_data.get("code") != 0:
                return None
            cid = view_data.get("data", {}).get("cid")
        if not cid:
            return None

        player_resp = requests.get(
            "https://api.bilibili.com/x/player/v2",
            params={"bvid": bvid, "cid": cid},
            headers=headers,
            timeout=20,
        )
        player_data = player_resp.json()
        subtitles = player_data.get("data", {}).get("subtitle", {}).get("subtitles", [])
        if not subtitles:
            aid = (info or {}).get("aid")
            if not aid:
                view_resp = requests.get(
                    "https://api.bilibili.com/x/web-interface/view",
                    params={"bvid": bvid},
                    headers=headers,
                    timeout=20,
                )
                view_data = view_resp.json()
                aid = view_data.get("data", {}).get("aid")
            if aid:
                dm_view_resp = requests.get(
                    "https://api.bilibili.com/x/v2/dm/view",
                    params={"aid": aid, "oid": cid, "type": 1},
                    headers=headers,
                    timeout=20,
                )
                dm_view_data = dm_view_resp.json()
                subtitles = dm_view_data.get("data", {}).get("subtitle", {}).get("subtitles", [])
        if not subtitles:
            return None

        def subtitle_rank(item: Dict[str, Any]) -> tuple:
            lan = (item.get("lan") or "").lower()
            ai_type = item.get("ai_type")
            return (
                0 if lan in ("zh-cn", "zh-hans", "zh") else 1,
                0 if ai_type == 0 else 1,
                item.get("id") or 0,
            )

        for sub in sorted(subtitles, key=subtitle_rank):
            subtitle_url = sub.get("subtitle_url") or ""
            if not subtitle_url:
                continue
            if subtitle_url.startswith("//"):
                subtitle_url = "https:" + subtitle_url
            elif subtitle_url.startswith("/"):
                subtitle_url = "https://www.bilibili.com" + subtitle_url

            sub_resp = requests.get(subtitle_url, headers=headers, timeout=20)
            if sub_resp.status_code != 200:
                continue
            sub_data = sub_resp.json()
            texts = []
            for item in sub_data.get("body", []):
                content = item.get("content") if isinstance(item, dict) else None
                if content:
                    texts.append(str(content).strip())
            transcript = " ".join(texts).strip()
            if len(transcript) > 50:
                return transcript
    except Exception as e:
        print(f"[WARN] Bilibili official subtitle exception: {e}", file=sys.stderr)

    return None


def process_url(
    url: str,
    include_transcript: bool = False,
    transcribe_audio: bool = False,
    asr_model: str = DEFAULT_ASR_MODEL,
    audio_output_dir: Optional[str] = None,
    asr_language: Optional[str] = "zh",
) -> Dict:
    """Process a single video URL from YouTube or Bilibili."""
    print(f"[INFO] Processing URL: {url}")

    if is_youtube_url(url):
        video_id = extract_youtube_id(url)
        if video_id:
            return process_video(
                video_id,
                include_transcript=include_transcript,
                transcribe_audio=transcribe_audio,
                asr_model=asr_model,
                audio_output_dir=audio_output_dir,
                asr_language=asr_language,
            )

    info = run_ytdlp_json(url)
    if not info:
        return {
            "video_id": url,
            "title": "Unknown",
            "url": url,
            "source": "bilibili" if is_bilibili_url(url) else "generic",
            "error": "Failed to fetch video details"
        }

    details = normalize_video_details(info, url)
    source = "bilibili" if is_bilibili_url(details["url"]) or is_bilibili_url(url) else "generic"
    transcript = None
    transcript_source = "none"
    if source == "bilibili":
        transcript = get_bilibili_official_subtitle(details["url"], info)
        if transcript:
            transcript_source = "subtitle_api"
        if not transcript:
            transcript = get_subtitle_with_ytdlp(details["url"])
            if transcript:
                transcript_source = "yt_dlp_subtitle"
    else:
        transcript = get_subtitle_with_ytdlp(details["url"])
        if transcript:
            transcript_source = "yt_dlp_subtitle"

    if not transcript and transcribe_audio:
        transcript = transcribe_url_audio(
            details["url"],
            model_name=asr_model,
            audio_output_dir=audio_output_dir,
            language=asr_language,
        )
        if transcript:
            transcript_source = "audio_asr"

    has_transcript = transcript is not None

    result = {
        "video_id": details["video_id"],
        "title": details["title"],
        "url": details["url"],
        "source": source,
        "channel": details["channel"],
        "duration": details["duration"],
        "published": details["published"],
        "has_transcript": has_transcript,
        "metadata": {
            "view_count": details.get("view_count", 0),
            "like_count": details.get("like_count", 0),
            "extractor": details.get("extractor", ""),
            "transcript_source": transcript_source,
        }
    }

    if has_transcript:
        print(f"  [OK] Transcript: {len(transcript)} chars")
        if include_transcript:
            result["transcript"] = transcript
    else:
        print("  [WARN] No subtitle/transcript available")

    return result


def process_video(
    video_id: str,
    title: str = None,
    channel: str = None,
    include_transcript: bool = False,
    transcribe_audio: bool = False,
    asr_model: str = DEFAULT_ASR_MODEL,
    audio_output_dir: Optional[str] = None,
    asr_language: Optional[str] = "zh",
) -> Dict:
    """Process a single YouTube video: get details and transcript."""
    print(f"[INFO] Processing: {video_id}")
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Get video details
    details = get_video_details(video_id)
    if not details:
        return {
            "video_id": video_id,
            "title": title or "Unknown",
            "url": video_url,
            "error": "Failed to fetch video details"
        }
    
    # Get transcript
    transcript = get_transcript(video_id)
    transcript_source = "subtitle_api" if transcript else "none"
    if not transcript and transcribe_audio:
        transcript = transcribe_url_audio(
            video_url,
            model_name=asr_model,
            audio_output_dir=audio_output_dir,
            language=asr_language,
        )
        if transcript:
            transcript_source = "audio_asr"
    has_transcript = transcript is not None
    
    result = {
        "video_id": video_id,
        "title": title or "Unknown",
        "url": video_url,
        "source": "youtube",
        "channel": channel or "Unknown",
        "duration": details["duration"],
        "published": details["published"],
        "has_transcript": has_transcript,
        "metadata": {
            "view_count": details.get("view_count", 0),
            "like_count": details.get("like_count", 0),
            "transcript_source": transcript_source,
        }
    }
    
    if has_transcript:
        print(f"  [OK] Transcript: {len(transcript)} chars")
        if include_transcript:
            result["transcript"] = transcript
    else:
        print("  [WARN] No transcript available")
    
    return result


def main():
    parser = argparse.ArgumentParser(description="YouTube and Bilibili Video Summarizer")
    parser.add_argument("--url", help="Single video URL (YouTube, Bilibili, or b23.tv)")
    parser.add_argument("--channel", help="Channel ID or handle")
    parser.add_argument("--config", help="Config file path (JSON)")
    parser.add_argument("--daily", action="store_true", help="Daily batch mode (requires --config)")
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS_LOOKBACK, help="Hours to look back")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output JSON file")
    parser.add_argument("--include-transcript", action="store_true", help="Include extracted transcript text in JSON output")
    parser.add_argument("--transcribe-audio", action="store_true", help="If subtitles are unavailable, download audio and transcribe it with faster-whisper")
    parser.add_argument("--asr-model", default=DEFAULT_ASR_MODEL, help="faster-whisper model name for audio transcription, for example base or small")
    parser.add_argument("--asr-language", default="zh", help="Language hint for faster-whisper; use empty string for auto-detect")
    parser.add_argument("--audio-output-dir", help="Optional directory to keep downloaded audio files; temporary audio is deleted by default")
    
    args = parser.parse_args()
    
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": [],
        "stats": {
            "total_videos": 0,
            "with_transcript": 0,
            "without_transcript": 0
        }
    }
    
    # Mode 1: Single video
    if args.url:
        result = process_url(
            args.url,
            include_transcript=args.include_transcript,
            transcribe_audio=args.transcribe_audio,
            asr_model=args.asr_model,
            audio_output_dir=args.audio_output_dir,
            asr_language=args.asr_language,
        )
        results["items"].append(result)
        results["stats"]["total_videos"] = 1
        if result.get("has_transcript"):
            results["stats"]["with_transcript"] = 1
        else:
            results["stats"]["without_transcript"] = 1
    
    # Mode 2: Channel scan
    elif args.channel:
        videos = get_channel_videos(args.channel, args.hours, DEFAULT_MAX_VIDEOS_PER_CHANNEL)
        print(f"[INFO] Found {len(videos)} videos from channel")
        
        for video in videos:
            result = process_video(
                video["id"],
                video["title"],
                video["channel"],
                include_transcript=args.include_transcript,
                transcribe_audio=args.transcribe_audio,
                asr_model=args.asr_model,
                audio_output_dir=args.audio_output_dir,
                asr_language=args.asr_language,
            )
            results["items"].append(result)
            results["stats"]["total_videos"] += 1
            if result.get("has_transcript"):
                results["stats"]["with_transcript"] += 1
            else:
                results["stats"]["without_transcript"] += 1
    
    # Mode 3: Daily batch (config file)
    elif args.daily and args.config:
        with open(args.config, "r") as f:
            config = json.load(f)
        
        channels = config.get("channels", [])
        hours = config.get("hours_lookback", args.hours)
        max_videos = config.get("max_videos_per_channel", DEFAULT_MAX_VIDEOS_PER_CHANNEL)
        
        print(f"[INFO] Processing {len(channels)} channels")
        
        for ch in channels:
            channel_id = ch.get("id") or ch.get("url")
            channel_name = ch.get("name", "Unknown")
            
            print(f"\n[INFO] Channel: {channel_name}")
            videos = get_channel_videos(channel_id, hours, max_videos)
            print(f"  Found {len(videos)} videos")
            
            for video in videos:
                result = process_video(
                    video["id"],
                    video["title"],
                    channel_name,
                    include_transcript=args.include_transcript,
                    transcribe_audio=args.transcribe_audio,
                    asr_model=args.asr_model,
                    audio_output_dir=args.audio_output_dir,
                    asr_language=args.asr_language,
                )
                results["items"].append(result)
                results["stats"]["total_videos"] += 1
                if result.get("has_transcript"):
                    results["stats"]["with_transcript"] += 1
                else:
                    results["stats"]["without_transcript"] += 1
    
    else:
        parser.print_help()
        sys.exit(1)
    
    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n[OK] Output written to: {output_path}")
    print(f"[INFO] Stats: {results['stats']}")


if __name__ == "__main__":
    main()
