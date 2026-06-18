"""
Flask application — main entry point for the Pick Note Print Service.

Provides a web-based dashboard and REST API for configuring the service,
managing the print worker, and monitoring print jobs.

Usage:
    python app.py

Dashboard:  http://localhost:5555
"""

import logging
import os

from flask import Flask, jsonify, render_template, request

import config
import printer
import service_manager
from frappe_client import FrappeClient
from print_worker import PrintWorker

# --------------------------------------------------------------------------- #
#  Background mode detection
# --------------------------------------------------------------------------- #
IS_BACKGROUND = os.environ.get("PICK_NOTE_SERVICE_MODE") == "background"

# --------------------------------------------------------------------------- #
#  Logging
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Suppress noisy werkzeug request logs in background mode
if IS_BACKGROUND:
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

# --------------------------------------------------------------------------- #
#  Flask app
# --------------------------------------------------------------------------- #
app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# --------------------------------------------------------------------------- #
#  Global state — the print worker is created on demand via the UI
# --------------------------------------------------------------------------- #
_worker: PrintWorker | None = None
_frappe_client: FrappeClient | None = None


def _mask_secret(secret: str) -> str:
    """Return the secret with only the last 4 characters visible."""
    if not secret or len(secret) <= 4:
        return "****"
    return "*" * (len(secret) - 4) + secret[-4:]


# --------------------------------------------------------------------------- #
#  Routes — Dashboard
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    """Serve the single-page dashboard."""
    return render_template("index.html")


# --------------------------------------------------------------------------- #
#  Routes — Configuration
# --------------------------------------------------------------------------- #

@app.route("/api/config", methods=["GET"])
def api_get_config():
    """Return the current configuration (with masked API token)."""
    cfg = config.get_config()
    cfg["api_token"] = _mask_secret(cfg.get("api_token", ""))
    return jsonify(cfg)


@app.route("/api/config", methods=["POST"])
def api_save_config():
    """
    Save configuration from the request JSON body.

    Expects a JSON object with the config keys.  If ``api_token``
    looks like a mask (all asterisks), the previously stored token
    is preserved so the user doesn't accidentally overwrite it.
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No JSON body provided."}), 400

        # Preserve existing token when the UI sends back a masked value
        incoming_token = data.get("api_token", "")
        if not incoming_token or incoming_token.startswith("****"):
            existing = config.get_config()
            data["api_token"] = existing.get("api_token", "")

        saved = config.save_config(data)
        saved["api_token"] = _mask_secret(saved.get("api_token", ""))
        return jsonify({"status": "ok", "config": saved})

    except Exception as exc:
        logger.exception("Failed to save config.")
        return jsonify({"error": str(exc)}), 500


# --------------------------------------------------------------------------- #
#  Routes — Connection test
# --------------------------------------------------------------------------- #

@app.route("/api/test-connection", methods=["POST"])
def api_test_connection():
    """
    Test the Frappe connection with credentials from the request body.

    Expects JSON: { frappe_url, api_token }
    """
    try:
        data = request.get_json(force=True)
        url = data.get("frappe_url", "").strip().rstrip("/")
        token = data.get("api_token", "").strip()

        if not all([url, token]):
            return jsonify({"error": "URL and API Token are required."}), 400

        # If the token is masked, fall back to the stored one
        if token.startswith("****"):
            existing = config.get_config()
            token = existing.get("api_token", "")

        client = FrappeClient(url, token)
        result = client.test_connection()
        return jsonify({"status": "ok", **result})

    except (ConnectionError, RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        logger.exception("Connection test failed.")
        return jsonify({"error": str(exc)}), 500


# --------------------------------------------------------------------------- #
#  Routes — Printers
# --------------------------------------------------------------------------- #

@app.route("/api/printers", methods=["GET"])
def api_list_printers():
    """List locally available printers."""
    try:
        printers = printer.list_printers()
        return jsonify({"printers": printers})
    except Exception as exc:
        logger.exception("Failed to list printers.")
        return jsonify({"error": str(exc)}), 500






# --------------------------------------------------------------------------- #
#  Routes — Service control
# --------------------------------------------------------------------------- #

@app.route("/api/service/start", methods=["POST"])
def api_service_start():
    """Start the print worker and install the background service."""
    global _worker, _frappe_client

    try:
        cfg = config.get_config()

        if not config.is_configured():
            return jsonify({
                "error": "Service is not fully configured. "
                         "Please set Frappe URL, API credentials, and printer."
            }), 400

        # Mark auto-start so the worker starts on boot
        config.save_config({**cfg, "auto_start_worker": True})

        # Install OS-level background service (systemd / Task Scheduler)
        svc_installed = False
        svc_msg = ""
        try:
            result = service_manager.install_service()
            svc_installed = True
            svc_msg = result.get("message", "")
        except Exception as svc_exc:
            logger.warning("Background service install failed: %s", svc_exc)
            svc_msg = "Could not install auto-start service."

        if svc_installed and not IS_BACKGROUND:
            # We're running from run.py (foreground mode).
            # Schedule a delayed handoff: shut down this process so the
            # background service can take over on port 5555.
            import threading

            def _handoff():
                import time
                time.sleep(3)  # give the HTTP response time to reach the browser
                logger.info("Handing off to background service...")

                # Stop the in-process worker (background service will auto-start its own)
                if _worker and _worker.is_running():
                    _worker.stop()

                # Start the background service, then exit
                service_manager.start_background_service()
                time.sleep(1)
                os._exit(0)

            threading.Thread(target=_handoff, daemon=True).start()

            return jsonify({
                "status": "ok",
                "message": f"Background service installed. {svc_msg} "
                           "This setup window will close in a few seconds.",
            })

        # Fallback: if we're already running as the background service,
        # just start the worker in-process.
        if not (_worker and _worker.is_running()):
            _frappe_client = FrappeClient(cfg["frappe_url"], cfg["api_token"])
            _worker = PrintWorker(cfg, _frappe_client, printer)
            _worker.start()

        return jsonify({
            "status": "ok",
            "message": f"Print worker started. {svc_msg}",
        })

    except Exception as exc:
        logger.exception("Failed to start print worker.")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/service/stop", methods=["POST"])
def api_service_stop():
    """Stop the print worker and remove the background service."""
    global _worker

    try:
        if _worker and _worker.is_running():
            _worker.stop()

        # Disable auto-start
        cfg = config.get_config()
        config.save_config({**cfg, "auto_start_worker": False})

        # Remove OS-level background service
        svc_msg = ""
        try:
            result = service_manager.uninstall_service()
            svc_msg = f" {result.get('message', '')}"
        except Exception as svc_exc:
            logger.warning("Background service uninstall failed: %s", svc_exc)

        return jsonify({
            "status": "ok",
            "message": f"Print worker stopped.{svc_msg}",
        })

    except Exception as exc:
        logger.exception("Failed to stop print worker.")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/service/info", methods=["GET"])
def api_service_info():
    """Return OS-level background service status."""
    return jsonify(service_manager.get_service_status())


# --------------------------------------------------------------------------- #
#  Routes — Status and logs
# --------------------------------------------------------------------------- #

@app.route("/api/status", methods=["GET"])
def api_get_status():
    """Return the current worker status."""
    if _worker:
        return jsonify(_worker.get_status())
    return jsonify({
        "running": False,
        "last_poll": None,
        "last_error": None,
        "jobs_processed": 0,
    })


@app.route("/api/logs", methods=["GET"])
def api_get_logs():
    """Return recent print job logs."""
    if _worker:
        return jsonify({"logs": _worker.get_logs()})
    return jsonify({"logs": []})


# --------------------------------------------------------------------------- #
#  Routes — Test print
# --------------------------------------------------------------------------- #

@app.route("/api/test-print", methods=["POST"])
def api_test_print():
    """Send a test print to the configured printer."""
    try:
        cfg = config.get_config()
        pname = cfg.get("printer_name", "")
        ptype = cfg.get("printer_type", "windows")
        paddr = cfg.get("printer_address", "")

        if not pname and ptype not in ("network", "serial"):
            return jsonify({"error": "No printer selected."}), 400

        printer.send_test_print(pname, ptype, paddr)
        return jsonify({"status": "ok", "message": "Test print sent successfully."})

    except (RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Test print failed.")
        return jsonify({"error": str(exc)}), 500


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #

def _auto_start_worker() -> None:
    """Auto-start the print worker if configured (e.g. on boot)."""
    global _worker, _frappe_client

    cfg = config.get_config()
    if not cfg.get("auto_start_worker"):
        return
    if not config.is_configured():
        logger.warning("auto_start_worker is True but config is incomplete.")
        return

    try:
        _frappe_client = FrappeClient(cfg["frappe_url"], cfg["api_token"])
        _worker = PrintWorker(cfg, _frappe_client, printer)
        _worker.start()
        logger.info("Print worker auto-started from saved configuration.")
    except Exception as exc:
        logger.exception("Failed to auto-start print worker: %s", exc)


if __name__ == "__main__":
    # Load configuration at startup
    config.load_config()

    # Auto-start the print worker if previously enabled
    _auto_start_worker()

    logger.info("Pick Note Print Service starting on http://0.0.0.0:5555")
    app.run(host="0.0.0.0", port=5555, debug=False)
