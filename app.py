from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import uuid
import threading
import time
import re
import shutil

app = Flask(__name__)
CORS(app, origins=[
    "http://theneofly.in",
    "https://theneofly.in",
    "https://www.theneofly.in"
])

DOWNLOAD_DIR = "/tmp/neofly_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def cleanup_old_files():
    while True:
        time.sleep(300)
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > 600:
                os.remove(fpath)

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
    if "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
        return "facebook"
    if "instagram.com" in url_lower:
        return "instagram"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    if "tiktok.com" in url_lower:
        return "tiktok"
    if "pinterest.com" in url_lower:
        return "pinterest"
    if "reddit.com" in url_lower:
        return "reddit"
    if "vimeo.com" in url_lower:
        return "vimeo"
    if "dailymotion.com" in url_lower:
        return "dailymotion"
    if "linkedin.com" in url_lower:
        return "linkedin"
    if "snapchat.com" in url_lower:
        return "snapchat"
    return "unknown"

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

def get_youtube_opts(with_cookies=True):
    opts = {
        "extractor_args": {
            "youtube": {
                "player_client": ["tv_embedded", "web_creator", "android"],
                "skip": ["hls", "dash"],
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (ChromiumStylePlatform) Cobalt/Version",
        },
    }
    if with_cookies:
        cookies = get_youtube_cookies()
        if cookies:
            opts["cookiefile"] = cookies
    return opts

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "NeoFly Downloader API",
        "version": "3.0.0",
        "supported_platforms": list(SUPPORTED_PLATFORMS.keys())
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
    yt_lines = [l for l in content.splitlines() if 'youtube' in l.lower()]
    try:
        shutil.copy2(path, "/tmp/youtube_cookies.txt")
        copy_ok = True
    except Exception:
        copy_ok = False
    return jsonify({
        "status": "ok",
        "file_size": size,
        "total_lines": len(content.splitlines()),
        "youtube_lines": len(yt_lines),
        "copy_to_tmp": copy_ok,
    })

@app.route("/debug-youtube", methods=["POST"])
def debug_youtube():
    data = request.get_json()
    url  = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400
    ydl_opts = {"quiet": False, "no_warnings": False, "skip_download": True}
    ydl_opts.update(get_youtube_opts())
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return jsonify({"status": "success", "title": info.get("title"), "cookies_used": "cookiefile" in ydl_opts})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e), "cookies_used": "cookiefile" in ydl_opts})

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
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}

    if platform == "youtube":
        ydl_opts.update(get_youtube_opts())
    elif platform == "tiktok":
        ydl_opts["extractor_args"] = {"tiktok": {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        seen_heights = set()
        quality_options = []
        if info.get("formats"):
            for f in info["formats"]:
                height = f.get("height")
                vcodec = f.get("vcodec")
                if not vcodec or vcodec == "none":
                    continue
                if not height or not isinstance(height, (int, float)):
                    continue
                height = int(height)
                if height in seen_heights:
                    continue
                seen_heights.add(height)
                quality_options.append({
                    "format_id": str(height),
                    "label": f"{height}p",
                    "ext": "mp4",
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "has_audio": True,
                })

        quality_options.sort(key=lambda x: int(x["label"].replace("p", "")), reverse=True)
        quality_options.insert(0, {
            "format_id": "best",
            "label": "Best Quality",
            "ext": "mp4",
            "filesize": None,
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
        if "sign in" in msg or "bot" in msg:
            return jsonify({"error": "YouTube cookies expired. Please re-upload cookies.txt to Render."}), 403
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
    url = data.get("url", "").strip()
    format_id = data.get("format_id", "best")
    if not url or not is_valid_url(url):
        return jsonify({"error": "Invalid or unsupported URL"}), 400

    platform  = get_platform(url)
    file_id   = str(uuid.uuid4())
    out_tmpl  = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": out_tmpl,
        "merge_output_format": "mp4",
    }

    if platform == "youtube":
        ydl_opts.update(get_youtube_opts())
    elif platform == "tiktok":
        ydl_opts["extractor_args"] = {"tiktok": {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}}

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
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")

        downloaded = None
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(file_id):
                downloaded = os.path.join(DOWNLOAD_DIR, f)
                break

        if not downloaded or not os.path.exists(downloaded):
            return jsonify({"error": "Download failed. File not found."}), 500

        safe_title   = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:60]
        ext          = downloaded.rsplit(".", 1)[-1]
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
        return jsonify({"error": "Download failed. Make sure the video is public."}), 400
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
