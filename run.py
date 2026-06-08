#!/usr/bin/env python3
"""
Pick Note Print Service — Auto-bootstrapping launcher.

This script handles the full setup automatically:
  1. Creates a Python virtual environment (if not present)
  2. Installs required dependencies (if not already installed)
  3. Launches the Flask application

Non-technical users only need to run:
    python run.py          (or python3 run.py on Linux)

No manual venv activation or pip commands needed.
"""

import os
import platform
import socket
import subprocess
import sys
import webbrowser

# --------------------------------------------------------------------------- #
#  Paths
# --------------------------------------------------------------------------- #
APP_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(APP_DIR, "venv")
REQUIREMENTS = os.path.join(APP_DIR, "requirements.txt")
APP_MODULE = os.path.join(APP_DIR, "app.py")

IS_WINDOWS = platform.system() == "Windows"
PYTHON_BIN = os.path.join(
    VENV_DIR, "Scripts" if IS_WINDOWS else "bin", "python"
)
PIP_BIN = os.path.join(
    VENV_DIR, "Scripts" if IS_WINDOWS else "bin", "pip"
)

DASHBOARD_URL = "http://localhost:5555"


def print_banner() -> None:
    """Display a startup banner."""
    print()
    print("=" * 52)
    print("   Pick Note Print Service — Auto Setup & Launch")
    print("=" * 52)
    print()


def is_port_in_use(port: int = 5555) -> bool:
    """Check if the service is already running on the given port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def create_venv() -> None:
    """Create the virtual environment if it doesn't exist."""
    if os.path.isdir(VENV_DIR) and os.path.isfile(PYTHON_BIN):
        print("[✓] Virtual environment found.")
        return

    print("[…] Creating virtual environment...")
    subprocess.check_call(
        [sys.executable, "-m", "venv", VENV_DIR],
        cwd=APP_DIR,
    )
    print("[✓] Virtual environment created.")


def install_dependencies() -> None:
    """Install/upgrade dependencies from requirements.txt."""
    # Check if Flask is importable from the venv to skip unnecessary installs
    check = subprocess.run(
        [PYTHON_BIN, "-c", "import flask; import apscheduler; import requests"],
        capture_output=True,
    )
    if check.returncode == 0:
        print("[✓] Dependencies already installed.")
        return

    print("[…] Installing dependencies (this may take a minute)...")
    subprocess.check_call(
        [PIP_BIN, "install", "--quiet", "--disable-pip-version-check", "-r", REQUIREMENTS],
        cwd=APP_DIR,
    )
    print("[✓] Dependencies installed.")


def launch_app() -> None:
    """Launch the Flask application using the venv Python."""
    # Check if the service is already running as a background service
    if is_port_in_use():
        print()
        print("[✓] Service is already running in the background!")
        print(f"    Dashboard: {DASHBOARD_URL}")
        print()
        print("    Opening your browser...")
        try:
            webbrowser.open(DASHBOARD_URL)
        except Exception:
            pass
        print()
        print("    Use the dashboard to manage the service.")
        print("    This terminal window can be closed.")
        return

    print()
    print("─" * 52)
    print("  Starting Pick Note Print Service...")
    print(f"  Dashboard: {DASHBOARD_URL}")
    print("─" * 52)
    print()
    print("  ℹ  Once you click 'Start Service' in the dashboard,")
    print("     the service will be installed to run on boot.")
    print("     You can then close this terminal window.")
    print()

    # Start Flask as a subprocess so the browser-opener thread can fire
    try:
        proc = subprocess.Popen([PYTHON_BIN, APP_MODULE], cwd=APP_DIR)

        # Wait for Flask to be ready, then open browser
        import time
        for _ in range(20):  # wait up to 4 seconds
            time.sleep(0.2)
            if is_port_in_use():
                break

        try:
            webbrowser.open(DASHBOARD_URL)
        except Exception:
            pass

        # Keep running until the user presses Ctrl+C
        proc.wait()
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        print("\nService stopped.")
        proc.terminate()
        sys.exit(0)


def main() -> None:
    print_banner()

    try:
        create_venv()
        install_dependencies()
        launch_app()
    except subprocess.CalledProcessError as exc:
        print(f"\n[✗] Setup failed: {exc}")
        print("    Please ensure Python 3.9+ is installed and try again.")
        if IS_WINDOWS:
            input("\nPress Enter to exit...")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)


if __name__ == "__main__":
    main()
