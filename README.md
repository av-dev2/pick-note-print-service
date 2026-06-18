# Pick Note Print Service

A standalone Python service that **polls a remote Frappe site for unprinted Pick Notes**, fetches the rendered print format output, converts it to plain text, and sends it to a local **thermal printer**. Includes a modern web dashboard for configuration, monitoring, and control.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Frappe Setup](#frappe-setup)
5. [Configuration](#configuration)
6. [Printer Setup](#printer-setup)
7. [Running as a Service](#running-as-a-service)
8. [Dashboard](#dashboard)
9. [API Endpoints](#api-endpoints)
10. [Print Format](#print-format)
11. [Troubleshooting](#troubleshooting)
12. [License](#license)

---

## Overview

```
┌──────────────────┐     REST API      ┌────────────────────┐
│   Frappe Site     │ ◄──────────────── │  Print Service     │
│   (ERPNext)       │ ──────────────►   │  (Python/Flask)    │
│                   │    Pick Notes     │                    │
└──────────────────┘                    │  ┌──────────────┐  │
                                        │  │  APScheduler  │  │
                                        │  │  Poll Worker  │  │
                                        │  └──────┬───────┘  │
                                        │         │          │
                                        │    Raw bytes       │
                                        │         │          │
                                        │  ┌──────▼───────┐  │
                                        │  │   Printer     │  │
                                        │  │   Module      │  │
                                        │  └──────┬───────┘  │
                                        └─────────┼──────────┘
                                                  │
                                        ┌─────────▼──────────┐
                                        │  Thermal Printer    │
                                        │  (USB/Network/      │
                                        │   Serial/Windows)   │
                                        └────────────────────┘
```

**How it works:**

1. The service polls Frappe every N seconds for unprinted Pick Notes.
2. For each unprinted Pick Note, it fetches the rendered print format output.
3. HTML content is stripped and converted to plain text suitable for thermal printers.
4. The plain text is encoded and sent to the configured thermal printer.
5. On successful printing, the Pick Note is marked as "Printed" on the Frappe site.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.9+ | 3.10+ recommended |
| Frappe | v14+ | With the Pick Note Print API installed |
| Thermal Printer | — | USB, Network (ESC/POS), Serial, or Windows driver |
| API Keys | — | Generated from the Frappe User settings |

### Frappe API Module

The service expects the following API endpoint module on your Frappe site:

```
amex.amex.utils.pick_note_print_api
```

This module should expose these whitelisted methods:
- `get_unprinted_pick_notes` — Returns unprinted Pick Notes
- `get_pick_note_print_raw` — Returns rendered print format output
- `mark_pick_note_printed` — Marks a Pick Note as printed

---

## Quick Start

### Windows

```batch
# 1. Clone or copy the project
# 2. Run the setup script
setup_windows.bat

# 3. Start the service
venv\Scripts\activate
python app.py

# 4. Open the dashboard
# Navigate to http://localhost:5555
```

### Linux

```bash
# 1. Clone or copy the project
# 2. Make the setup script executable and run it
chmod +x setup_linux.sh
./setup_linux.sh

# 3. Start the service
source venv/bin/activate
python app.py

# 4. Open the dashboard
# Navigate to http://localhost:5555
```

---

## Frappe Setup

### Generating API Keys

1. Log in to your Frappe site as an Administrator.
2. Go to **User** → select the user that will authenticate the print service.
3. Scroll down to **API Access** section.
4. Click **Generate Keys**.
5. **Copy the API Secret immediately** — it will not be shown again.
6. Copy the **API Key** from the same section.

### Required Permissions

The API user needs the following permissions:
- **Read** access to the **Pick Note** DocType
- **Write** access to the **Pick Note** DocType (to mark as printed)
- Access to the custom API methods in `amex.amex.utils.pick_note_print_api`

---

## Configuration

All settings are stored in `config.json` in the application directory. You can configure everything through the web dashboard at `http://localhost:5555`.

| Setting | Type | Default | Description |
|---|---|---|---|
| `frappe_url` | string | `""` | Root URL of your Frappe site (e.g. `https://erp.example.com`) |
| `api_key` | string | `""` | Frappe API key |
| `api_secret` | string | `""` | Frappe API secret |
| `printer_name` | string | `""` | Name of the selected printer |
| `printer_type` | string | `"windows"` | `"windows"`, `"network"`, `"serial"`, or `"cups"` |
| `printer_address` | string | `""` | IP:port (network) or device path (serial) |
| `poll_interval_seconds` | int | `30` | How often to check for new Pick Notes (minimum: 5) |
| `print_format` | string | `""` | Optional Frappe print format name |

---

## Printer Setup

### Windows Printer

Use the Windows printer driver. The service sends raw data using `win32print`.

1. Install the printer driver from the manufacturer.
2. Ensure the printer appears in **Settings → Printers & Scanners**.
3. In the dashboard, select **Printer Type: Windows Printer**.
4. Click **Refresh** to list printers, then select your thermal printer.

### Network Printer (ESC/POS)

Connect directly via TCP/IP to an ESC/POS compatible thermal printer.

1. Find your printer's IP address (check printer settings or router).
2. The default ESC/POS port is **9100**.
3. In the dashboard, select **Printer Type: Network (IP)**.
4. Enter the address as `192.168.1.100:9100`.

### Serial Printer

Connect via a serial/COM port.

| OS | Example Address |
|---|---|
| Windows | `COM3` |
| Linux | `/dev/ttyUSB0` |

1. Connect the printer via USB-to-serial or RS-232.
2. In the dashboard, select **Printer Type: Serial**.
3. Enter the device path.

### USB / CUPS (Linux)

Use CUPS (Common UNIX Printing System) for USB-connected printers on Linux.

1. Install CUPS: `sudo apt install cups`
2. Add your printer via CUPS web interface (`http://localhost:631`) or `lpadmin`.
3. Verify with: `lpstat -p`
4. In the dashboard, select **Printer Type: USB / CUPS (Linux)**.
5. Click **Refresh** to list CUPS printers and select yours.

---

## Running as a Service

### Windows — Using NSSM

[NSSM](https://nssm.cc/) (Non-Sucking Service Manager) is the recommended way to run the service in the background on Windows.

```batch
# Download NSSM from https://nssm.cc/download
# Then install the service:

nssm install PickNotePrintService "C:\path\to\pick_note_print_service\venv\Scripts\python.exe" "C:\path\to\pick_note_print_service\app.py"
nssm set PickNotePrintService AppDirectory "C:\path\to\pick_note_print_service"
nssm set PickNotePrintService DisplayName "Pick Note Print Service"
nssm set PickNotePrintService Description "Automatic Pick Note thermal printing service"
nssm set PickNotePrintService Start SERVICE_AUTO_START

# Start the service
nssm start PickNotePrintService

# To remove the service later:
nssm remove PickNotePrintService confirm
```

### Linux — Using systemd

Create a systemd unit file:

```ini
# /etc/systemd/system/pick-note-print.service

[Unit]
Description=Pick Note Print Service
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/pick_note_print_service
ExecStart=/path/to/pick_note_print_service/venv/bin/python app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable pick-note-print.service
sudo systemctl start pick-note-print.service

# Check status
sudo systemctl status pick-note-print.service

# View logs
sudo journalctl -u pick-note-print.service -f
```

---

## Dashboard

The web dashboard is accessible at **http://localhost:5555** and provides:

- **Connection Settings** — Configure and test the Frappe site connection
- **Print Settings** — Configure print layout settings, optional print format, and poll interval
- **Printer Settings** — Select printer type, enumerate local printers, test printing
- **Service Controls** — Start/Stop the background worker, view stats
- **Print Log** — Real-time table of recent print jobs with status and timestamps

The log panel auto-refreshes every 10 seconds.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Dashboard HTML page |
| `GET` | `/api/config` | Get current configuration (secret masked) |
| `POST` | `/api/config` | Save configuration |
| `POST` | `/api/test-connection` | Test Frappe connection with provided credentials |
| `GET` | `/api/printers` | List locally available printers |
| `POST` | `/api/service/start` | Start the print worker |
| `POST` | `/api/service/stop` | Stop the print worker |
| `GET` | `/api/status` | Get worker status (running, last poll, errors, jobs count) |
| `GET` | `/api/logs` | Get recent print job logs |
| `POST` | `/api/test-print` | Send a test print to the configured printer |

---

## Print Format

For the best results with thermal printers, create a dedicated Frappe Print Format:

### Tips for Thermal Print Formats

1. **Keep it narrow** — Thermal printers are typically 58mm or 80mm wide (32 or 48 characters per line for monospace).
2. **Use monospace fonts** — `Courier New` or similar for aligned columns.
3. **Minimal HTML** — The service strips HTML to plain text. Use simple structures.
4. **Use `<br>` for line breaks** — They are converted to newlines.
5. **Use `<table>` for columns** — `</td>` is converted to tab spacing, `</tr>` to newlines.

### Example Print Format (Jinja)

```html
<div style="font-family: Courier New, monospace; font-size: 12px; width: 280px;">
    <div style="text-align: center;">
        <b>{{ doc.company }}</b><br>
        <b>PICK NOTE</b><br>
        {{ doc.name }}<br>
        --------------------------------
    </div>
    <br>
    Date: {{ doc.posting_date }}<br>
    --------------------------------<br>
    <table>
        <tr>
            <td><b>Item</b></td>
            <td><b>Qty</b></td>
        </tr>
        {% for item in doc.items %}
        <tr>
            <td>{{ item.item_code }}</td>
            <td>{{ item.qty }}</td>
        </tr>
        {% endfor %}
    </table>
    --------------------------------<br>
    <div style="text-align: center;">
        Printed: {{ frappe.utils.now() }}
    </div>
</div>
```

---

## Troubleshooting

### Connection Issues

| Problem | Solution |
|---|---|
| **Connection refused** | Verify the Frappe URL is correct and accessible from this machine. Check firewalls. |
| **Authentication failed (HTTP 401/403)** | Verify API key and secret. Ensure the user has the required permissions. |
| **SSL certificate error** | If using self-signed certs, you may need to set `verify=False` in the session (not recommended for production). |
| **Timeout** | Check network connectivity. The default timeout is 10s for connect, 30s for read. |

### Printer Issues

| Problem | Solution |
|---|---|
| **No printers found** | Windows: Check printer driver installation. Linux: Check CUPS is installed and running (`sudo systemctl status cups`). |
| **Permission denied** | Linux: Add your user to the `lp` group: `sudo usermod -aG lp $USER` |
| **Network printer timeout** | Verify IP address and port. Test with: `nc -zv 192.168.1.100 9100` |
| **Garbled output** | Ensure the printer supports raw/text mode. Check the encoding (UTF-8 vs ASCII). |
| **Serial port access denied** | Linux: `sudo chmod 666 /dev/ttyUSB0` or add user to `dialout` group. Windows: Check COM port in Device Manager. |

### Service Issues

| Problem | Solution |
|---|---|
| **Service won't start** | Check that all configuration fields are filled (URL, keys, printer). Check the terminal output for errors. |
| **Pick Notes not printing** | Check that unprinted Pick Notes exist. Look at the print log for errors. |
| **Duplicate prints** | The service marks Pick Notes as printed after successful dispatch. If the Frappe API call to mark as printed fails, duplicates may occur. Check network stability. |

---

## License

MIT License

Copyright (c) 2024

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
