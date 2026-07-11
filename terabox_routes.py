# terabox_routes.py
# Calls a running terabox-gateway instance over HTTP instead of importing
# it as a library (it's a standalone Flask app, not a pip package with a
# client class — that's what caused the ImportError).
#
# No new dependency needed beyond `requests`, which yt-dlp already pulls in.

from flask import Blueprint, request, jsonify
import requests
import os

terabox_bp = Blueprint("terabox", __name__)

# Public demo instance of saahiyo/terabox-gateway. Fine for testing, but
# it's shared/rate-limited by everyone using it. For production, deploy
# your own copy to Vercel (see below) and point this at your own URL.
GATEWAY_URL = os.environ.get("TERABOX_GATEWAY_URL", "https://tera-core.vercel.app")


@terabox_bp.route("/api/terabox", methods=["GET"])
def extract_terabox():
    """
    GET /api/terabox?url=<terabox_share_url>

    Returns:
    {
      "status": "success",
      "files": [
        {
          "filename": "...",
          "size": "...",
          "thumbnail": "...",
          "download_link": "...",
          "stream_link": null
        }
      ]
    }
    """
    share_url = request.args.get("url", "").strip()

    if not share_url:
        return jsonify({"status": "error", "message": "Missing 'url' parameter"}), 400

    if "terabox" not in share_url and "1024tera" not in share_url and "teraboxapp" not in share_url:
        return jsonify({"status": "error", "message": "URL does not look like a TeraBox link"}), 400

    try:
        resp = requests.get(
            f"{GATEWAY_URL}/api2",
            params={"url": share_url},
            timeout=20,
        )
        data = resp.json()

        # terabox-gateway's own response shape varies by version; handle
        # both a top-level "files" list and a single-file dict gracefully.
        raw_files = data.get("files") or ([data] if data.get("direct_link") else [])

        files = []
        for f in raw_files:
            files.append({
                "filename": f.get("filename") or f.get("file_name"),
                "size": f.get("size"),
                "thumbnail": f.get("thumbnail") or f.get("thumb"),
                "download_link": f.get("direct_link") or f.get("download_link"),
                "stream_link": f.get("stream_link"),
            })

        if not files or not files[0].get("download_link"):
            return jsonify({
                "status": "error",
                "message": data.get("message") or "No playable files found in this link"
            }), 404

        return jsonify({"status": "success", "files": files})

    except requests.exceptions.RequestException as e:
        print(f"[terabox] gateway request failed: {e}")
        return jsonify({
            "status": "error",
            "message": "Could not reach the TeraBox extraction service. Try again shortly."
        }), 502
    except ValueError:
        # response wasn't valid JSON
        print(f"[terabox] gateway returned non-JSON: {resp.text[:200]}")
        return jsonify({
            "status": "error",
            "message": "TeraBox service returned an unexpected response."
        }), 502
    except Exception as e:
        print(f"[terabox] extraction failed: {e}")
        return jsonify({
            "status": "error",
            "message": "Could not process this TeraBox link. It may be private, expired, or invalid."
        }), 502
        
