"""
Background polling worker for the Pick Note Print Service.

Uses APScheduler's BackgroundScheduler to periodically poll the Frappe
site for unprinted Pick Notes, render them to plain text, and dispatch
them to the configured thermal printer.
"""

import logging
import re
import threading
from datetime import datetime, timezone
from html import unescape
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Maximum number of log entries retained in memory
MAX_LOG_ENTRIES = 50


class PrintWorker:
    """
    Polls Frappe for unprinted Pick Notes and sends them to a thermal printer.

    Attributes:
        config:         Application configuration dict.
        frappe_client:  An instance of ``FrappeClient``.
        printer:        The ``printer`` module (provides ``send_to_printer``).
    """

    def __init__(self, config: dict, frappe_client: Any, printer_module: Any) -> None:
        self.config = config
        self.frappe_client = frappe_client
        self.printer = printer_module

        self._scheduler: Optional[BackgroundScheduler] = None
        self._running = False

        # Status tracking
        self._last_poll: Optional[str] = None
        self._last_error: Optional[str] = None
        self._jobs_processed: int = 0

        # Thread-safe log storage
        self._logs: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """
        Start the background scheduler.

        Creates a new ``BackgroundScheduler`` with an interval trigger
        based on ``poll_interval_seconds`` from the config.
        """
        if self._running:
            logger.warning("PrintWorker is already running.")
            return

        interval = self.config.get("poll_interval_seconds", 30)
        self._scheduler = BackgroundScheduler(daemon=True)
        self._scheduler.add_job(
            func=self._poll_and_print,
            trigger=IntervalTrigger(seconds=interval),
            id="pick_note_poll",
            name="Poll and Print Pick Notes",
            replace_existing=True,
            max_instances=1,          # Prevent overlapping runs
            misfire_grace_time=60,    # Allow up to 60 s late execution
        )
        self._scheduler.start()
        self._running = True
        self._add_log("service", "info", "Print worker started", f"Polling every {interval}s")
        logger.info("PrintWorker started — polling every %d seconds.", interval)

    def stop(self) -> None:
        """Shut down the background scheduler gracefully."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

        self._running = False
        self._add_log("service", "info", "Print worker stopped", "")
        logger.info("PrintWorker stopped.")

    def is_running(self) -> bool:
        """Return whether the scheduler is currently active."""
        return self._running

    def get_status(self) -> dict[str, Any]:
        """
        Return a snapshot of the worker's current state.

        Returns:
            dict with keys: running, last_poll, last_error, jobs_processed.
        """
        return {
            "running": self._running,
            "last_poll": self._last_poll,
            "last_error": self._last_error,
            "jobs_processed": self._jobs_processed,
        }

    def get_logs(self) -> list[dict[str, Any]]:
        """Return the most recent log entries (thread-safe copy)."""
        with self._lock:
            return list(self._logs)

    # ------------------------------------------------------------------ #
    #  Logging helper
    # ------------------------------------------------------------------ #

    def _add_log(
        self,
        pick_note: str,
        status: str,
        message: str,
        detail: str = "",
    ) -> None:
        """
        Append a log entry (thread-safe, capped at MAX_LOG_ENTRIES).

        Args:
            pick_note: The Pick Note name or a service-level identifier.
            status:    "success", "error", or "info".
            message:   Short human-readable message.
            detail:    Optional additional detail.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pick_note": pick_note,
            "status": status,
            "message": message,
            "detail": detail,
        }
        with self._lock:
            self._logs.append(entry)
            # Trim to keep only the last MAX_LOG_ENTRIES
            if len(self._logs) > MAX_LOG_ENTRIES:
                self._logs = self._logs[-MAX_LOG_ENTRIES:]

    # ------------------------------------------------------------------ #
    #  Main polling job
    # ------------------------------------------------------------------ #

    def _poll_and_print(self) -> None:
        """
        The core scheduled job.

        1. Fetch unprinted Pick Notes from Frappe.
        2. For each note (FIFO order):
           a. Get the rendered print output.
           b. Convert HTML → plain text for the thermal printer.
           c. Send to the printer.
           d. Mark as printed on the Frappe site.
        3. Update the last-poll timestamp.
        """
        printer_name = self.config.get("printer_name", "")
        printer_type = self.config.get("printer_type", "windows")
        printer_address = self.config.get("printer_address", "")

        now = datetime.now(timezone.utc).isoformat()
        self._last_poll = now

        try:
            pick_notes = self.frappe_client.get_unprinted_pick_notes(
                limit=5
            )
        except Exception as exc:
            error_msg = f"Failed to fetch Pick Notes: {exc}"
            self._last_error = error_msg
            self._add_log("poll", "error", error_msg)
            logger.error(error_msg)
            return

        if not pick_notes:
            logger.debug("No unprinted Pick Notes found.")
            return

        logger.info("Found %d unprinted Pick Note(s).", len(pick_notes))

        for note in pick_notes:
            name = note.get("name", "unknown")
            try:
                # Step 1: Fetch the full Pick Note document data
                doc = self.frappe_client.get_pick_note_data(name)

                # Step 2: Enrich with data from related documents
                # — Operator full name (from User doctype)
                owner = doc.get("owner", "")
                doc["_operator_name"] = (
                    self.frappe_client.get_value("User", owner, "full_name") or owner
                )

                # — Target warehouse for IBT transfers
                if doc.get("pick_note_type") == "IBT" and doc.get("ibt_request"):
                    doc["_target_warehouse"] = (
                        self.frappe_client.get_value(
                            "IBT Request", doc["ibt_request"], "target_warehouse"
                        ) or ""
                    )

                # Step 3: Build ESC/POS receipt bytes from document data
                raw_bytes = build_receipt(doc, self.config)

                # Step 4: Send to printer
                self.printer.send_to_printer(
                    printer_name, printer_type, printer_address, raw_bytes
                )

                # Step 4: Mark as printed on the Frappe site
                self.frappe_client.mark_printed(name)

                self._jobs_processed += 1
                self._add_log(name, "success", "Printed successfully")
                logger.info("Printed and marked: %s", name)

            except Exception as exc:
                error_msg = f"Error processing {name}: {exc}"
                self._last_error = error_msg
                self._add_log(name, "error", str(exc))
                logger.error(error_msg)
                # Continue to the next Pick Note — retry this one on the next cycle


# --------------------------------------------------------------------------- #
#  ESC/POS Receipt Builder
# --------------------------------------------------------------------------- #

# ESC/POS command constants
ESC_INIT = b'\x1b\x40'              # Initialize printer
ESC_CENTER = b'\x1b\x61\x01'        # Center alignment
ESC_LEFT = b'\x1b\x61\x00'          # Left alignment
ESC_BOLD_ON = b'\x1b\x45\x01'       # Bold on
ESC_BOLD_OFF = b'\x1b\x45\x00'      # Bold off
ESC_DOUBLE_ON = b'\x1b\x21\x30'     # Double width + height
ESC_DOUBLE_OFF = b'\x1b\x21\x00'    # Normal size
ESC_CUT_PARTIAL = b'\x1d\x56\x41\x03'  # Partial cut with feed
ESC_CUT_FULL = b'\x1d\x56\x00'      # Full cut
LF = b'\x0a'                         # Line feed


def build_receipt(doc: dict, config: dict) -> bytes:
    """
    Build an ESC/POS receipt from Pick Note document data.

    The layout mirrors the Frappe Jinja raw-printing template, including
    warehouse header, document details, itemised table, signature lines,
    and a disclaimer footer.

    Args:
        doc:    The full Pick Note document dict from Frappe (enriched with
                ``_operator_name`` and optionally ``_target_warehouse``).
        config: The application configuration dict with layout settings.

    Returns:
        bytes: Raw ESC/POS data ready to send to the thermal printer.
    """
    W = config.get("paper_width", 42)
    auto_cut = config.get("auto_cut", True)
    feed_lines = config.get("feed_lines", 3)

    p: list[bytes] = []
    sep = ("-" * W).encode("utf-8")
    underline = ("_" * min(40, W)).encode("utf-8")

    def _text(s: str) -> None:
        """Append a UTF-8 encoded string + line-feed."""
        p.append(s.encode("utf-8", errors="replace"))
        p.append(LF)

    def _field(label: str, value: str) -> None:
        """Append a padded 'Label       : Value' line."""
        _text(f"{label:<12s}: {value}")

    # ---- Initialize printer ----
    p.append(ESC_INIT)

    # ---- Header (centered) ----
    p.append(ESC_CENTER)
    p.append(ESC_BOLD_ON)
    _text("PICK NOTE")
    p.append(ESC_BOLD_OFF)
    _text(doc.get("name", ""))
    p.append(LF)

    # ---- Ordered By (left-aligned) ----
    p.append(ESC_LEFT)
    _text("Ordered By:")
    warehouse = doc.get("warehouse", "")
    _text(warehouse)

    # ---- Separator ----
    p.append(sep)
    p.append(LF)

    # ---- Document details ----
    creation = doc.get("creation", "")
    date_str = ""
    time_str = ""
    if creation:
        try:
            from datetime import datetime as _dt
            dt = _dt.fromisoformat(creation.split(".")[0])
            date_str = dt.strftime("%d/%m/%Y")
            time_str = dt.strftime("%H:%M:%S")
        except Exception:
            date_str = creation[:10]
            time_str = creation[11:19] if len(creation) > 18 else ""

    pick_type = doc.get("pick_note_type") or "Sales Order"
    operator = doc.get("_operator_name", doc.get("owner", ""))

    _field("Document No", doc.get("name", ""))
    _field("Date", date_str)
    _field("Time", time_str)
    _field("Type", pick_type)
    _field("Operator", operator)

    # ---- Type-specific fields ----
    if pick_type == "IBT":
        _field("IBT Req", doc.get("ibt_request", ""))
        _field("Source Wh", warehouse)
        target_wh = doc.get("_target_warehouse", "")
        if target_wh:
            _field("Target Wh", target_wh)
    else:
        _field("Sales Order", doc.get("sales_order", ""))
        customer = doc.get("customer", "")
        if customer:
            _field("Customer", customer)

    p.append(LF)

    # ---- Items header ----
    p.append(sep)
    p.append(LF)
    p.append(ESC_BOLD_ON)
    _text("Quantity Product")
    p.append(ESC_BOLD_OFF)
    p.append(sep)
    p.append(LF)
    p.append(LF)

    # ---- Items ----
    items = doc.get("items", [])
    for row in items:
        item_code = row.get("item_code") or ""
        item_name = (row.get("item_name") or "")[:W]

        _text(item_code)
        if item_name:
            _text(item_name)

        bin_loc = row.get("bin_location") or "No Bin"
        _field("Bin Loc", bin_loc)

        _field("Pick Qty", str(row.get("pick_qty", 0)))
        _text("Qty Picked  : ______________________")
        p.append(sep)
        p.append(LF)

    # ---- Total ----
    p.append(LF)
    _field("Total Lines", str(len(items)))
    p.append(LF)

    # ---- Additional information ----
    _text("Additional Information:")
    p.append(underline)
    p.append(LF)
    p.append(underline)
    p.append(LF)
    p.append(LF)

    # ---- Signatures ----
    _text("Picked By:")
    p.append(underline)
    p.append(LF)
    p.append(LF)

    _text("Checked / Loaded By:")
    p.append(underline)
    p.append(LF)
    p.append(LF)

    # ---- Disclaimer (centered) ----
    p.append(ESC_CENTER)
    _text("This is not a valid receipt.")
    _text("Goods must be taken to the customer at")
    _text("their own risk once issued.")
    p.append(LF)
    _text("*** END OF PICK NOTE ***")

    # ---- Feed lines before cut ----
    for _ in range(feed_lines):
        p.append(LF)

    # ---- Auto-cut ----
    if auto_cut:
        p.append(ESC_CUT_PARTIAL)

    return b"".join(p)


# --------------------------------------------------------------------------- #
#  HTML → Plain-text conversion for thermal printers
# --------------------------------------------------------------------------- #

def strip_html(html_content: str) -> str:
    """
    Convert HTML content to plain text suitable for thermal printers.

    Processing order:
      1. Convert ``<br>`` / ``<br/>`` / ``<br />`` → newline
      2. Convert ``</tr>`` → newline (end of table row)
      3. Convert ``</td>`` and ``</th>`` → tab (column separator)
      4. Remove all remaining HTML tags
      5. Decode HTML entities (``&nbsp;``, ``&amp;``, ``&lt;``, ``&gt;``, etc.)
      6. Normalise whitespace (collapse multiple blanks, trim lines)
      7. Collapse more than two consecutive blank lines into two

    Args:
        html_content: Raw HTML string from the Frappe print format.

    Returns:
        Clean plain-text string ready for the thermal printer.
    """
    if not html_content:
        return ""

    text = html_content

    # 1. <br> variants → newline
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # 2. </tr> → newline
    text = re.sub(r"</tr\s*>", "\n", text, flags=re.IGNORECASE)

    # 3. </td>, </th> → tab (column separator)
    text = re.sub(r"</t[dh]\s*>", "\t", text, flags=re.IGNORECASE)

    # 4. Remove all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # 5. Decode common HTML entities
    text = text.replace("&nbsp;", " ")
    text = unescape(text)  # handles &amp; &lt; &gt; &quot; &#xxxx; etc.

    # 6. Normalise whitespace on each line (collapse runs of spaces/tabs)
    lines = text.splitlines()
    cleaned_lines: list[str] = []
    for line in lines:
        # Replace tabs with spaces for consistent thermal-printer output
        line = line.replace("\t", "    ")
        # Collapse multiple spaces
        line = re.sub(r" {2,}", "  ", line)
        cleaned_lines.append(line.strip())

    text = "\n".join(cleaned_lines)

    # 7. Collapse excessive blank lines (more than 2 → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Final trim
    text = text.strip()

    # Append a few newlines at the end so the paper can be torn off
    text += "\n\n\n"

    return text
