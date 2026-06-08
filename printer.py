"""
Cross-platform thermal printer abstraction.

Supports listing and sending raw data to printers via:
  - Windows printing API  (win32print)
  - Network socket        (IP:port, typically ESC/POS port 9100)
  - Serial / device file  (COM port on Windows, /dev/ttyUSBx on Linux)
  - CUPS / USB on Linux   (lp -o raw)
"""

import os
import platform
import subprocess
import socket
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Conditional imports — win32print is only available on Windows
# --------------------------------------------------------------------------- #
IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    try:
        import win32print  # type: ignore[import-untyped]
    except ImportError:
        win32print = None  # type: ignore[assignment]
        logger.warning(
            "win32print not available — install pywin32 for Windows printer support."
        )
else:
    win32print = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
#  Printer discovery
# --------------------------------------------------------------------------- #

def list_printers() -> list[dict[str, str]]:
    """
    Enumerate locally available printers.

    On Windows uses win32print.EnumPrinters().
    On Linux  uses ``lpstat -p`` to query CUPS.

    Returns:
        A list of dicts with ``name`` and ``type`` keys, e.g.
        [{"name": "EPSON_TM_T88V", "type": "windows"}, ...]
    """
    printers: list[dict[str, str]] = []

    if IS_WINDOWS:
        printers.extend(_list_windows_printers())
    else:
        printers.extend(_list_cups_printers())

    return printers


def _list_windows_printers() -> list[dict[str, str]]:
    """List printers via the Windows printing subsystem."""
    if win32print is None:
        return []

    try:
        # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS = 0x02 | 0x04
        flags = 0x02 | 0x04
        raw = win32print.EnumPrinters(flags, None, 2)
        return [
            {"name": p["pPrinterName"], "type": "windows"}
            for p in raw
        ]
    except Exception as exc:
        logger.error("Failed to enumerate Windows printers: %s", exc)
        return []


def _list_cups_printers() -> list[dict[str, str]]:
    """List printers via CUPS (Linux/macOS)."""
    printers: list[dict[str, str]] = []
    try:
        result = subprocess.run(
            ["lpstat", "-p"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                # Typical lpstat -p output:
                #   printer EPSON_TM_T88V is idle.  enabled since ...
                parts = line.split()
                if len(parts) >= 2 and parts[0].lower() == "printer":
                    printers.append({"name": parts[1], "type": "cups"})
    except FileNotFoundError:
        logger.info("lpstat not found — CUPS may not be installed.")
    except subprocess.TimeoutExpired:
        logger.warning("lpstat timed out while listing printers.")
    except Exception as exc:
        logger.error("Failed to list CUPS printers: %s", exc)

    return printers


# --------------------------------------------------------------------------- #
#  Sending raw data to a printer
# --------------------------------------------------------------------------- #

def send_to_printer(
    printer_name: str,
    printer_type: str,
    printer_address: str,
    raw_data: bytes,
) -> None:
    """
    Send raw byte data to a printer.

    Args:
        printer_name:    Name of the printer (for Windows/CUPS types).
        printer_type:    One of "windows", "network", "serial", "cups", "usb".
        printer_address: IP:port for network, device path for serial, ignored otherwise.
        raw_data:        The raw bytes to send.

    Raises:
        RuntimeError: If printing fails for any reason.
        ValueError:   If an unsupported printer_type is specified.
    """
    ptype = printer_type.lower().strip()

    if ptype == "windows":
        _send_windows(printer_name, raw_data)
    elif ptype == "network":
        _send_network(printer_address, raw_data)
    elif ptype == "serial":
        _send_serial(printer_address, raw_data)
    elif ptype in ("cups", "usb"):
        _send_cups(printer_name, raw_data)
    else:
        raise ValueError(
            f"Unsupported printer type: '{printer_type}'. "
            f"Use 'windows', 'network', 'serial', 'cups', or 'usb'."
        )


def _send_windows(printer_name: str, raw_data: bytes) -> None:
    """Send raw data via the Windows printing subsystem."""
    if win32print is None:
        raise RuntimeError(
            "win32print is not available. Install pywin32: pip install pywin32"
        )

    handle = None
    try:
        handle = win32print.OpenPrinter(printer_name)
        # Start a raw document — "RAW" datatype bypasses the driver
        win32print.StartDocPrinter(handle, 1, ("Pick Note", None, "RAW"))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, raw_data)
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
        logger.info("Printed to Windows printer '%s' (%d bytes).", printer_name, len(raw_data))
    except Exception as exc:
        raise RuntimeError(
            f"Failed to print to Windows printer '{printer_name}': {exc}"
        ) from exc
    finally:
        if handle is not None:
            try:
                win32print.ClosePrinter(handle)
            except Exception:
                pass


def _send_network(address: str, raw_data: bytes) -> None:
    """
    Send raw data over a TCP socket (ESC/POS network printer).

    The address should be in ``host:port`` format (e.g. ``192.168.1.100:9100``).
    """
    if ":" not in address:
        raise ValueError(
            f"Network printer address must be host:port, got: '{address}'"
        )

    host, port_str = address.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ValueError(f"Invalid port number in address '{address}'") from exc

    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            sock.sendall(raw_data)
        logger.info("Printed to network printer %s (%d bytes).", address, len(raw_data))
    except socket.timeout as exc:
        raise RuntimeError(
            f"Connection to {address} timed out."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Failed to send data to {address}: {exc}"
        ) from exc


def _send_serial(device_path: str, raw_data: bytes) -> None:
    """
    Send raw data to a serial device (COM port / /dev/ttyUSBx).

    Falls back to a direct file write if pyserial is not installed.
    """
    if not device_path:
        raise ValueError("Serial printer address (device path) is required.")

    # Try pyserial first for proper baud-rate control
    try:
        import serial  # type: ignore[import-untyped]
        with serial.Serial(device_path, baudrate=9600, timeout=5) as ser:
            ser.write(raw_data)
            ser.flush()
        logger.info("Printed to serial device %s via pyserial (%d bytes).", device_path, len(raw_data))
        return
    except ImportError:
        logger.debug("pyserial not installed — falling back to direct file write.")
    except Exception as exc:
        raise RuntimeError(
            f"Failed to write to serial device '{device_path}': {exc}"
        ) from exc

    # Fallback: direct file write (Linux / macOS)
    try:
        with open(device_path, "wb") as dev:
            dev.write(raw_data)
            dev.flush()
        logger.info("Printed to serial device %s via file write (%d bytes).", device_path, len(raw_data))
    except OSError as exc:
        raise RuntimeError(
            f"Failed to write to serial device '{device_path}': {exc}"
        ) from exc


def _send_cups(printer_name: str, raw_data: bytes) -> None:
    """
    Send raw data via CUPS using the ``lp`` command with raw mode.

    This is the standard approach on Linux for USB thermal printers
    managed through CUPS.
    """
    try:
        result = subprocess.run(
            ["lp", "-o", "raw", "-d", printer_name],
            input=raw_data,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"lp command failed (exit {result.returncode}): {stderr}"
            )
        logger.info("Printed to CUPS printer '%s' (%d bytes).", printer_name, len(raw_data))
    except FileNotFoundError:
        raise RuntimeError(
            "The 'lp' command was not found. Is CUPS installed?"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Printing to CUPS printer '{printer_name}' timed out."
        )


# --------------------------------------------------------------------------- #
#  Test print
# --------------------------------------------------------------------------- #

def send_test_print(
    printer_name: str,
    printer_type: str,
    printer_address: str,
) -> None:
    """
    Send a brief test page to verify printer connectivity.

    Args:
        printer_name:    Name of the printer.
        printer_type:    Printer type identifier.
        printer_address: Address (network/serial) or empty.

    Raises:
        RuntimeError / ValueError: If the test print fails.
    """
    test_content = (
        "================================\n"
        "  PICK NOTE PRINT SERVICE\n"
        "  ---- Test Print ----\n"
        "================================\n"
        "\n"
        "  Printer : {name}\n"
        "  Type    : {ptype}\n"
        "  Address : {addr}\n"
        "\n"
        "  If you can read this, the\n"
        "  printer is working correctly.\n"
        "\n"
        "================================\n"
        "\n\n\n"  # Feed a few blank lines so the paper can be torn
    ).format(
        name=printer_name,
        ptype=printer_type,
        addr=printer_address or "(local)",
    )

    raw_bytes = test_content.encode("utf-8")
    send_to_printer(printer_name, printer_type, printer_address, raw_bytes)
