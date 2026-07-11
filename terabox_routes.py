# terabox_routes.py
# Add this to your existing neofly-api Flask app (app.py).
# Requires: pip install terabox-gateway
#
# In requirements.txt add:
#   terabox-gateway

from flask import Blueprint, request, jsonify
from terabox_gateway import TeraboxClient
import os

terabox_bp = Blueprint("terabox", __name__)

# Optional: some private/limited-access links need a cookie.
# Public share links usually work without one.
TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE", None)

_client = TeraboxClient(cookie=TERABOX_COOKIE) if TERABOX_COOKIE else TeraboxClient()


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
          "stream_link": "..."   # m3u8/HLS if available, else null
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
        result = _client.get_file_info(share_url)

        files = []
        for f in result.get("files", []):
            files.append({
                "filename": f.get("filename"),
                "size": f.get("size"),
                "thumbnail": f.get("thumbnail"),
                "download_link": f.get("download_link"),
                "stream_link": f.get("hls_link") or None,
            })

        if not files:
            return jsonify({"status": "error", "message": "No playable files found in this link"}), 404

        return jsonify({"status": "success", "files": files})

    except Exception as e:
        # Common failure modes: expired share link, token/cookie rejected by
        # TeraBox, or their API shape changed. Log e server-side and keep
        # the client message generic.
        print(f"[terabox] extraction failed: {e}")
        return jsonify({
            "status": "error",
            "message": "Could not process this TeraBox link. It may be private, expired, or TeraBox changed something on their end."
        }), 502


# In your main app.py, register this blueprint:
#
#   from terabox_routes import terabox_bp
#   app.register_blueprint(terabox_bp)
