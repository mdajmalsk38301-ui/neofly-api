from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp
import os
import uuid
import threading
import time
import re

app = Flask(__name__)
CORS(app, origins=["https://theneofly.in", "http://localhost", "*"])

DOWNLOAD_DIR = "/tmp/neofly_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Auto-cleanup files older than 10 minutes
def cleanup_old_files():
    while True:
        time.sleep(300)
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > 600:
                os.remove(fpath)

threading.Thread(target=cleanup_old_files, daemon=True).start()


def is_valid_url(url):
    fb_pattern = r"(https?://)?(www\.)?(facebook\.com|fb\.watch|fb\.com)/.*"
    ig_pattern = r"(https?://)?(www\.)?instagram\.com/(p|reel|tv)/.*"
    return re.match(fb_pattern, url) or re.match(ig_pattern, url)


def get_platform(url):
    if "facebook.com" in url or "fb.watch" in url or "fb.com" in url:
        return "facebook"
    elif "instagram.com" in url:
        return "instagram"
    return "unknown"


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "NeoFly Downloader API", "version": "1.0.0"})


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL is required"}), 400

    if not is_valid_url(url):
        return jsonify({"error": "Only Facebook and Instagram URLs are supported"}), 400

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "cookiefile": "/etc/secrets/cookies.txt" if os.path.exists("/etc/secrets/cookies.txt") else None,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        platform = get_platform(url)

        formats = []
        seen = set()
        if info.get("formats"):
            for f in info["formats"]:
                height = f.get("height")
                ext = f.get("ext", "mp4")
                vcodec = f.get("vcodec", "none")
                acodec = f.get("acodec", "none")

                if vcodec == "none":
                    continue
                if not height:
                    continue

                label = f"{height}p"
                key = (label, ext)
                if key in seen:
                    continue
                seen.add(key)

                formats.append({
                    "format_id": f["format_id"],
                    "label": label,
                    "ext": ext,
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "has_audio": acodec != "none",
                })

        formats.sort(key=lambda x: int(x["label"].replace("p", "")), reverse=True)

        # If no separate formats, offer a single best quality
        if not formats:
            formats = [{"format_id": "best", "label": "Best Quality", "ext": "mp4", "filesize": None, "has_audio": True}]

        return jsonify({
            "title": info.get("title", "Video"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "platform": platform,
            "uploader": info.get("uploader") or info.get("channel"),
            "formats": formats,
        })

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "login" in msg.lower() or "private" in msg.lower():
            return jsonify({"error": "This video is private or requires login. Only public videos are supported."}), 403
        return jsonify({"error": "Could not fetch video info. Make sure the URL is public and valid."}), 400
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@app.route("/api/download", methods=["POST"])
def download_video():
    data = request.get_json()
    url = data.get("url", "").strip()
    format_id = data.get("format_id", "best")

    if not url or not is_valid_url(url):
        return jsonify({"error": "Invalid or missing URL"}), 400

    file_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": output_template,
        "cookiefile": "/etc/secrets/cookies.txt" if os.path.exists("/etc/secrets/cookies.txt") else None,
    }

    if format_id and format_id != "best":
        # Merge video+audio if needed
        ydl_opts["format"] = f"{format_id}+bestaudio/best[height<={format_id.replace('p','')}]/best"
    else:
        ydl_opts["format"] = "bestvideo+bestaudio/best"

    ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")

        # Find the downloaded file
        downloaded = None
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(file_id):
                downloaded = os.path.join(DOWNLOAD_DIR, f)
                break

        if not downloaded or not os.path.exists(downloaded):
            return jsonify({"error": "Download failed. File not found."}), 500

        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:60]
        ext = downloaded.rsplit(".", 1)[-1]
        download_name = f"{safe_title}.{ext}"

        return send_file(
            downloaded,
            as_attachment=True,
            download_name=download_name,
            mimetype="video/mp4"
        )

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "login" in msg.lower() or "private" in msg.lower():
            return jsonify({"error": "This video is private or requires login."}), 403
        return jsonify({"error": "Download failed. Make sure the video is public."}), 400
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
