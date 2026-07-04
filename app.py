from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import uuid
import threading
import time
import re
import shutil
import requests as req

app = Flask(__name__)
CORS(app, origins=[
    "http://theneofly.in",
    "https://theneofly.in",
    "https://www.theneofly.in"
])

DOWNLOAD_DIR = "/tmp/neofly_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# YouTube Data API key — set as environment variable on Render
YT_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

def cleanup_old_files():
    while True:
        time.sleep(300)
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > 600:
                try:
                    os.remove(fpath)
                except Exception:
                    pass

threading.Thread(target=cleanup_old_files, daemon=True).start()

SUPPORTED_PLATFORMS = {
    "facebook":    r"https?://(www\.)?(facebook\.com|fb\.watch|fb\.com)/.+",
    "instagram":   r"https?://(www\.)?instagram\.com/.+",
    "youtube":     r"https?://((www\.|m\.)?youtube\.com|youtu\.be)/.+",
    "twitter":     r"https?://((www\.|mobile\.)?twitter\.com|(www\.)?x\.com)/.+",
    "tiktok":      r"https?://((www\.|vm\.|vt\.)?tiktok\.com)/.+",
    "pinterest":   r"https?://(www\.)?pinterest\.(com|co\.uk|in)/.+",
    "reddit":      r"https?://((www\.|old\.)?reddit\.com)/.+",
    "vimeo":       r"https?://(www\.)?vimeo\.com/.+",
    "dailymotion": r"https?://(www\.)?dailymotion\.com/.+",
    "linkedin":    r"https?://(www\.)?linkedin\.com/.+",
    "snapchat":    r"https?://(www\.)?snapchat\.com/.+",
}

def is_valid_url(url):
    for pattern in SUPPORTED_PLATFORMS.values():
        if re.match(pattern, url, re.IGNORECASE):
            return True
    return False

def get_platform(url):
    url_lower = url.lower()
    if any(d in url_lower for d in ["facebook.com", "fb.watch", "fb.com"]):
        return "facebook"
    if "instagram.com" in url_lower: return "instagram"
    if "youtube.com" in url_lower or "youtu.be" in url_lower: return "youtube"
    if "twitter.com" in url_lower or "x.com" in url_lower: return "twitter"
    if "tiktok.com" in url_lower: return "tiktok"
    if "pinterest.com" in url_lower: return "pinterest"
    if "reddit.com" in url_lower: return "reddit"
    if "vimeo.com" in url_lower: return "vimeo"
    if "dailymotion.com" in url_lower: return "dailymotion"
    if "linkedin.com" in url_lower: return "linkedin"
    if "snapchat.com" in url_lower: return "snapchat"
    return "unknown"

def extract_youtube_id(url):
    """Extract YouTube video ID from any YouTube URL format."""
    patterns = [
        r"(?:v=|youtu\.be/|/embed/|/shorts/|/v/)([a-zA-Z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

def get_youtube_info_via_api(video_id):
    """
    Get YouTube video info using YouTube Data API v3.
    Returns title, thumbnail, duration, and stream URL via yt-dlp
    but only uses API for metadata to avoid IP blocks.
    """
    if not YT_API_KEY:
        return None, "YouTube API key not configured"

    try:
        api_url = "https://www.googleapis.com/youtube/v3/videos"
        params  = {
            "id":   video_id,
            "key":  YT_API_KEY,
            "part": "snippet,contentDetails,statistics",
        }
        r = req.get(api_url, params=params, timeout=10)
        data = r.json()

        if not data.get("items"):
            return None, "Video not found or is private"

        item    = data["items"][0]
        snippet = item["snippet"]
        details = item["contentDetails"]

        # Parse ISO 8601 duration (PT4M13S → 253 seconds)
        dur_str  = details.get("duration", "PT0S")
        dur_match = re.findall(r'(\d+)([HMS])', dur_str)
        seconds  = 0
        for val, unit in dur_match:
            if unit == 'H': seconds += int(val) * 3600
            elif unit == 'M': seconds += int(val) * 60
            elif unit == 'S': seconds += int(val)

        # Get best thumbnail
        thumbs = snippet.get("thumbnails", {})
        thumb  = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {}).get("url", "")

        return {
            "video_id":  video_id,
            "title":     snippet.get("title", "Video"),
            "thumbnail": thumb,
            "duration":  seconds,
            "uploader":  snippet.get("channelTitle", ""),
            "platform":  "youtube",
        }, None

    except Exception as e:
        return None, str(e)

def get_youtube_stream_url(video_id):
    """
    Get actual stream URLs using yt-dlp with android client.
    This is separate from metadata so we can retry independently.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "quiet":         True,
        "no_warnings":   True,
        "skip_download": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios"],
            }
        },
        "http_headers": {
            "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
        },
    }
    # Add cookies if available
    cookies = get_youtube_cookies()
    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        seen_heights  = set()
        quality_options = []
        if info.get("formats"):
            for f in info["formats"]:
                height = f.get("height")
                vcodec = f.get("vcodec")
                if not vcodec or vcodec == "none": continue
                if not height or not isinstance(height, (int, float)): continue
                height = int(height)
                if height in seen_heights: continue
                seen_heights.add(height)
                quality_options.append({
                    "format_id": str(height),
                    "label":     f"{height}p",
                    "ext":       "mp4",
                    "filesize":  f.get("filesize") or f.get("filesize_approx"),
                    "has_audio": True,
                })

        quality_options.sort(key=lambda x: int(x["label"].replace("p", "")), reverse=True)
        quality_options.insert(0, {
            "format_id": "best",
            "label":     "Best Quality",
            "ext":       "mp4",
            "filesize":  None,
            "has_audio": True,
        })
        return quality_options, None
    except Exception as e:
        return None, str(e)

def get_youtube_cookies():
    secret_path = "/etc/secrets/cookies.txt"
    tmp_path    = "/tmp/youtube_cookies.txt"
    if not os.path.exists(secret_path) or os.path.getsize(secret_path) == 0:
        return None
    try:
        shutil.copy2(secret_path, tmp_path)
        return tmp_path
    except Exception:
        return None

def get_ydl_opts_for_platform(platform, skip_download=True):
    opts = {
        "quiet":         True,
        "no_warnings":   True,
        "skip_download": skip_download,
    }
    if platform == "tiktok":
        opts["extractor_args"] = {
            "tiktok": {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}
        }
    return opts


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status":              "NeoFly Downloader API",
        "version":             "5.0.0",
        "supported_platforms": list(SUPPORTED_PLATFORMS.keys()),
        "yt_dlp_version":      yt_dlp.version.__version__,
        "youtube_api":         "enabled" if YT_API_KEY else "disabled",
    })


@app.route("/check-cookies", methods=["GET"])
def check_cookies():
    path = "/etc/secrets/cookies.txt"
    if not os.path.exists(path):
        return jsonify({"status": "missing"})
    size = os.path.getsize(path)
    if size == 0:
        return jsonify({"status": "empty"})
    with open(path, 'r') as f:
        content = f.read()
    lines     = content.splitlines()
    yt_lines  = [l for l in lines if 'youtube' in l.lower()]
    key_cookies = ["SID", "HSID", "SSID", "SAPISID", "LOGIN_INFO"]
    found_keys  = [k for k in key_cookies if any(k in l for l in lines)]
    try:
        shutil.copy2(path, "/tmp/youtube_cookies.txt")
        copy_ok = True
    except Exception:
        copy_ok = False
    return jsonify({
        "status":        "ok",
        "file_size":     size,
        "total_lines":   len(lines),
        "youtube_lines": len(yt_lines),
        "key_cookies":   found_keys,
        "copy_to_tmp":   copy_ok,
        "valid":         len(found_keys) >= 3 and copy_ok,
    })


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request body"}), 400
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400
    if not is_valid_url(url):
        supported = ", ".join(p.capitalize() for p in SUPPORTED_PLATFORMS.keys())
        return jsonify({"error": f"Unsupported platform. We support: {supported}"}), 400

    platform = get_platform(url)

    # ── YouTube — use Data API for metadata, yt-dlp for formats ──
    if platform == "youtube":
        video_id = extract_youtube_id(url)
        if not video_id:
            return jsonify({"error": "Could not extract YouTube video ID from URL"}), 400

        # Get metadata from YouTube Data API
        meta, err = get_youtube_info_via_api(video_id)
        if err and not meta:
            # Fallback to yt-dlp if API fails
            meta = {"title": "YouTube Video", "thumbnail": "", "duration": 0, "uploader": "", "platform": "youtube"}

        # Get stream formats via yt-dlp
        formats, err2 = get_youtube_stream_url(video_id)
        if err2 or not formats:
            # Provide default quality options if yt-dlp fails
            formats = [
                {"format_id": "best", "label": "Best Quality", "ext": "mp4", "filesize": None, "has_audio": True},
                {"format_id": "720",  "label": "720p",         "ext": "mp4", "filesize": None, "has_audio": True},
                {"format_id": "480",  "label": "480p",         "ext": "mp4", "filesize": None, "has_audio": True},
            ]

        return jsonify({
            "title":     meta.get("title", "YouTube Video"),
            "thumbnail": meta.get("thumbnail", ""),
            "duration":  meta.get("duration", 0),
            "platform":  "youtube",
            "uploader":  meta.get("uploader", ""),
            "formats":   formats,
        })

    # ── Other platforms — use yt-dlp directly ────────────────────
    ydl_opts = get_ydl_opts_for_platform(platform, skip_download=True)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        seen_heights  = set()
        quality_options = []
        if info.get("formats"):
            for f in info["formats"]:
                height = f.get("height")
                vcodec = f.get("vcodec")
                if not vcodec or vcodec == "none": continue
                if not height or not isinstance(height, (int, float)): continue
                height = int(height)
                if height in seen_heights: continue
                seen_heights.add(height)
                quality_options.append({
                    "format_id": str(height),
                    "label":     f"{height}p",
                    "ext":       "mp4",
                    "filesize":  f.get("filesize") or f.get("filesize_approx"),
                    "has_audio": True,
                })

        quality_options.sort(key=lambda x: int(x["label"].replace("p", "")), reverse=True)
        quality_options.insert(0, {
            "format_id": "best",
            "label":     "Best Quality",
            "ext":       "mp4",
            "filesize":  None,
            "has_audio": True,
        })

        return jsonify({
            "title":     info.get("title", "Video"),
            "thumbnail": info.get("thumbnail"),
            "duration":  info.get("duration"),
            "platform":  platform,
            "uploader":  info.get("uploader") or info.get("channel"),
            "formats":   quality_options,
        })

    except yt_dlp.utils.DownloadError as e:
        msg = str(e).lower()
        if "private" in msg or "login" in msg:
            return jsonify({"error": "This video is private or requires login."}), 403
        if "copyright" in msg:
            return jsonify({"error": "Video unavailable due to copyright."}), 403
        return jsonify({"error": "Could not fetch video. Make sure the URL is correct and public."}), 400
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route("/api/download", methods=["POST"])
def download_video():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request body"}), 400
    url       = data.get("url", "").strip()
    format_id = data.get("format_id", "best")
    if not url or not is_valid_url(url):
        return jsonify({"error": "Invalid or unsupported URL"}), 400

    platform = get_platform(url)
    file_id  = str(uuid.uuid4())
    out_tmpl = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    # YouTube download
    if platform == "youtube":
        video_id = extract_youtube_id(url)
        if not video_id:
            return jsonify({"error": "Could not extract YouTube video ID"}), 400
        dl_url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            "quiet":               True,
            "no_warnings":         True,
            "outtmpl":             out_tmpl,
            "merge_output_format": "mp4",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios"],
                }
            },
            "http_headers": {
                "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
            },
            "sleep_interval":     2,
            "max_sleep_interval": 5,
        }
        cookies = get_youtube_cookies()
        if cookies:
            ydl_opts["cookiefile"] = cookies
    else:
        dl_url   = url
        ydl_opts = get_ydl_opts_for_platform(platform, skip_download=False)
        ydl_opts["outtmpl"]            = out_tmpl
        ydl_opts["merge_output_format"] = "mp4"

    # Format selection
    if format_id == "best" or not format_id:
        ydl_opts["format"] = "bestvideo+bestaudio/best"
    else:
        try:
            height = int(format_id)
            ydl_opts["format"] = (
                f"bestvideo[height<={height}]+bestaudio"
                f"/best[height<={height}]"
                f"/bestvideo+bestaudio/best"
            )
        except ValueError:
            ydl_opts["format"] = "bestvideo+bestaudio/best"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info  = ydl.extract_info(dl_url, download=True)
            title = info.get("title", "video")

        downloaded = None
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(file_id):
                downloaded = os.path.join(DOWNLOAD_DIR, f)
                break

        if not downloaded or not os.path.exists(downloaded):
            return jsonify({"error": "Download failed. File not found after processing."}), 500

        safe_title    = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:60]
        ext           = downloaded.rsplit(".", 1)[-1]
        download_name = f"{safe_title}.{ext}"

        return send_file(
            downloaded,
            as_attachment=True,
            download_name=download_name,
            mimetype="video/mp4"
        )

        except yt_dlp.utils.DownloadError as e:
        msg = str(e).lower()
        if "private" in msg or "login" in msg:
            return jsonify({"error": "This video is private or requires login."}), 403
        # Change this line to return the exact yt-dlp error string
        return jsonify({"error": f"Download failed: {str(e)}"}), 400
    

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
