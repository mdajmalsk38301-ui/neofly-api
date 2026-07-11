from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import uuid
import threading
import time
import re
import shutil
from terabox_routes import terabox_bp

app = Flask(__name__)
CORS(app, origins=[
    "http://theneofly.in",
    "https://theneofly.in",
    "https://www.theneofly.in"
])

app.register_blueprint(terabox_bp)

DOWNLOAD_DIR = "/tmp/neofly_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ── Auto cleanup files older than 10 mins ─────────────
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

# ── Supported platforms (YouTube removed) ─────────────
SUPPORTED_PLATFORMS = {
    "facebook":    r"https?://(www\.)?(facebook\.com|fb\.watch|fb\.com)/.+",
    "instagram":   r"https?://(www\.)?instagram\.com/.+",
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
    # Block YouTube explicitly with a clear message
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    for pattern in SUPPORTED_PLATFORMS.values():
        if re.match(pattern, url, re.IGNORECASE):
            return True
    return False

def get_platform(url):
    url_lower = url.lower()
    if any(d in url_lower for d in ["facebook.com", "fb.watch", "fb.com"]):
        return "facebook"
    if "instagram.com" in url_lower: return "instagram"
    if "twitter.com" in url_lower or "x.com" in url_lower: return "twitter"
    if "tiktok.com" in url_lower: return "tiktok"
    if "pinterest.com" in url_lower: return "pinterest"
    if "reddit.com" in url_lower: return "reddit"
    if "vimeo.com" in url_lower: return "vimeo"
    if "dailymotion.com" in url_lower: return "dailymotion"
    if "linkedin.com" in url_lower: return "linkedin"
    if "snapchat.com" in url_lower: return "snapchat"
    return "unknown"

def get_ydl_opts(platform, skip_download=True):
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

def build_formats(info):
    seen_heights    = set()
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
    return quality_options


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status":              "NeoFly Downloader API",
        "version":             "6.0.0",
        "supported_platforms": list(SUPPORTED_PLATFORMS.keys()) + ["terabox"],
        "yt_dlp_version":      yt_dlp.version.__version__,
    })


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    # YouTube — friendly error with redirect
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return jsonify({
            "error": "YouTube downloads are currently unavailable on our server. Please use cobalt.tools or yt1s.com for YouTube videos."
        }), 400

    valid = is_valid_url(url)
    if not valid or valid == "youtube":
        supported = ", ".join(p.capitalize() for p in SUPPORTED_PLATFORMS.keys())
        return jsonify({"error": f"Unsupported platform. We support: {supported}"}), 400

    platform = get_platform(url)
    ydl_opts = get_ydl_opts(platform, skip_download=True)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        return jsonify({
            "title":     info.get("title", "Video"),
            "thumbnail": info.get("thumbnail"),
            "duration":  info.get("duration"),
            "platform":  platform,
            "uploader":  info.get("uploader") or info.get("channel"),
            "formats":   build_formats(info),
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

    # YouTube — friendly error
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return jsonify({
            "error": "YouTube downloads are currently unavailable. Please use cobalt.tools or yt1s.com."
        }), 400

    if not url or not is_valid_url(url):
        return jsonify({"error": "Invalid or unsupported URL"}), 400

    platform = get_platform(url)
    file_id  = str(uuid.uuid4())
    out_tmpl = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    ydl_opts = get_ydl_opts(platform, skip_download=False)
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
            info  = ydl.extract_info(url, download=True)
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
        return jsonify({"error": "Download failed. Make sure the video is public."}), 400
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
        
