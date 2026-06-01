# Addy

A minimal cross-platform system-tray app that shows your network interfaces and IP addresses. Copy any address with one click.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

## Features

- **System tray** — lives in your taskbar; close the window and it minimises to the tray
- Shows all active network interfaces with **hardware adapter name**, **WiFi SSID / network name**, IPv4 and IPv6
- One-click **copy** to clipboard
- **Refresh** on demand or automatically when re-opened from the tray
- Near-zero resource usage when minimised
- Works on **Windows**, **macOS**, and **Linux**

## Quick Start

```bash
pip install -r requirements.txt
python addy.py
```

## Usage

| Action | Result |
|--------|--------|
| **Close (✕)** | Window hides; Addy stays in the system tray |
| **Left-click tray icon** | Show the window |
| **Right-click tray icon → Refresh** | Re-scan network interfaces |
| **Right-click tray icon → Quit** | Exit Addy completely |

## Requirements

- Python 3.10+
- `psutil`, `pystray`, `Pillow` (installed via `requirements.txt`)
- tkinter (included with most Python installs)

> **Linux note:** tkinter may be a separate package — install with  
> `sudo apt install python3-tk` (Debian/Ubuntu) or `sudo dnf install python3-tkinter` (Fedora).

## Releases

Pre-built standalone executables for every platform are published automatically when code is merged to `main`. Download from the [Releases](../../releases) page — no Python installation required.
