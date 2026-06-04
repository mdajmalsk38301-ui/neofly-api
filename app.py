from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import uuid
import threading
import time
import re

app = Flask(__name__)
CORS(app, origins=["https://theneofly.in",
    "https://www.theneofly.in"])

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


def is_valid_url(url):
    fb_pattern = r"(https?://)?(www\.)?(facebook\.com|fb\.watch|fb\.com)/.*"
    ig_pattern = r"(https?://)?(www\.)?instagram\.com/(p|reel|tv|videos)/.*"
    return re.match(fb_pattern, url) or re.match(ig_pattern, url)


def get_platform(url):
    if "facebook.com" in url or "fb.watch" in url or "fb.com" in url:
        return "facebook"
    elif "instagram.com" in url:
        return "instagram"
    return "unknown"


def get_cookies():
    path = "/etc/secrets/cookies.txt"
    return path if os.path.exists(path) else None


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "NeoFly Downloader API", "version": "2.1.0"})


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
    }
    cookies = get_cookies()
    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        platform = get_platform(url)

        # Build quality options based on available video heights
        # We always merge with best audio on download, so just show unique heights
        seen_heights = set()
        quality_options = []

        if info.get("formats"):
            for f in info["formats"]:
                height = f.get("height")
                vcodec = f.get("vcodec")

                # Must have video stream
                if not vcodec or vcodec == "none":
                    continue
                if not height or not isinstance(height, (int, float)):
                    continue

                height = int(height)
                if height in seen_heights:
                    continue
                seen_heights.add(height)

                # Store height as format_id — download will pick best video at this height + best audio
                quality_options.append({
                    "format_id": str(height),
                    "label": f"{height}p",
                    "ext": "mp4",
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "has_audio": True,  # Always true — we merge audio on download
                })

        quality_options.sort(key=lambda x: int(x["label"].replace("p", "")), reverse=True)

        # Always put Best Quality first
        quality_options.insert(0, {
            "format_id": "best",
            "label": "Best Quality",
            "ext": "mp4",
            "filesize": None,
            "has_audio": True,
        })

        return jsonify({
            "title": info.get("title", "Video"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "platform": platform,
            "uploader": info.get("uploader") or info.get("channel"),
            "formats": quality_options,
        })

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "login" in msg.lower() or "private" in msg.lower():
            return jsonify({"error": "This video is private or requires login."}), 403
        return jsonify({"error": "Could not fetch video. Make sure the URL is public."}), 400
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


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
        "merge_output_format": "mp4",
    }

    cookies = get_cookies()
    if cookies:
        ydl_opts["cookiefile"] = cookies

    # format_id is now a height number (e.g. "720") or "best"
    # Always merge best video at that height with best audio
    if format_id == "best" or not format_id:
        ydl_opts["format"] = "bestvideo+bestaudio/best"
    else:
        try:
            height = int(format_id)
            # Pick best video stream at or below this height, always merge with best audio
            ydl_opts["format"] = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/bestvideo+bestaudio/best"
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
        return jsonify({"error": f"Server error: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
