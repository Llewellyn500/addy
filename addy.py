#!/usr/bin/env python3
"""
Addy — A minimal cross-platform system-tray app that displays
network interface IP addresses with one-click copy.

Runs on Windows, macOS, and Linux.  Closing the window minimises to
the system tray; right-click the tray icon → Quit to exit.
"""

import json
import platform
import socket
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

import psutil

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont

    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd):
    """Run *cmd* and return stdout, or ``""`` on any failure."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_NO_WINDOW,
        )
        return r.stdout.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Platform-aware network enrichment
# ---------------------------------------------------------------------------


def _parse_ipconfig():
    """Parse ``ipconfig /all`` for adapter descriptions (Windows fallback)."""
    out = _run(["ipconfig", "/all"])
    if not out:
        return {}
    info: dict[str, str] = {}
    current: str | None = None
    for line in out.splitlines():
        stripped = line.strip()
        # Header: "Ethernet adapter Ethernet 2:" / "Wireless LAN adapter Wi-Fi:"
        if "adapter " in line and stripped.endswith(":"):
            _, _, after = line.partition("adapter ")
            current = after.rstrip(":").strip()
            info[current] = ""
        elif current is not None and stripped.startswith("Description"):
            _, _, val = stripped.partition(":")
            info[current] = val.strip()
            current = None
    return info


def _enrich_windows():
    info: dict[str, dict] = {}

    # 1) Adapter descriptions via PowerShell --------------------------------
    out = _run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "Get-NetAdapter -IncludeHidden"
        " | Select-Object Name, InterfaceDescription"
        " | ConvertTo-Json -Compress",
    ])
    if out:
        try:
            adapters = json.loads(out)
            if isinstance(adapters, dict):
                adapters = [adapters]
            for a in adapters:
                name = a.get("Name", "")
                info[name] = {
                    "description": a.get("InterfaceDescription", ""),
                    "ssid": None,
                    "network": None,
                }
        except (json.JSONDecodeError, TypeError):
            pass

    # 2) Fallback descriptions from ipconfig /all ---------------------------
    for iface, desc in _parse_ipconfig().items():
        if iface not in info:
            info[iface] = {"description": desc, "ssid": None, "network": None}
        elif not info[iface]["description"] and desc:
            info[iface]["description"] = desc

    # 3) Network profile names (domain / "Network" / SSID echo) -------------
    out = _run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "Get-NetConnectionProfile"
        " | Select-Object InterfaceAlias, Name"
        " | ConvertTo-Json -Compress",
    ])
    if out:
        try:
            profiles = json.loads(out)
            if isinstance(profiles, dict):
                profiles = [profiles]
            for p in profiles:
                alias = p.get("InterfaceAlias", "")
                net_name = p.get("Name", "")
                if alias in info and net_name:
                    info[alias]["network"] = net_name
        except (json.JSONDecodeError, TypeError):
            pass

    # 4) WiFi SSID via netsh ------------------------------------------------
    out = _run(["netsh", "wlan", "show", "interfaces"])
    if out:
        current_iface = None
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("Name"):
                _, _, v = s.partition(":")
                current_iface = v.strip()
            elif s.startswith("SSID") and not s.startswith("BSSID"):
                _, _, v = s.partition(":")
                ssid = v.strip()
                if current_iface and current_iface in info and ssid:
                    info[current_iface]["ssid"] = ssid

    return info


def _enrich_macos():
    info: dict[str, dict] = {}

    # Hardware port → device mapping
    out = _run(["networksetup", "-listallhardwareports"])
    current_port = None
    for line in out.splitlines():
        if line.startswith("Hardware Port:"):
            current_port = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and current_port:
            device = line.split(":", 1)[1].strip()
            info[device] = {
                "description": current_port,
                "ssid": None,
                "network": None,
            }
            current_port = None

    # WiFi SSID
    for iface, data in info.items():
        if data["description"] and "wi-fi" in data["description"].lower():
            out = _run(["networksetup", "-getairportnetwork", iface])
            if "Current Wi-Fi Network:" in out:
                ssid = out.split(":", 1)[1].strip()
                data["ssid"] = ssid
                data["network"] = ssid

    return info


def _enrich_linux():
    info: dict[str, dict] = {}

    # NetworkManager
    out = _run(
        ["nmcli", "-t", "-f", "DEVICE,TYPE,CONNECTION", "device", "status"]
    )
    if out:
        for line in out.splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 3:
                device, dtype, connection = parts
                friendly = (
                    dtype.replace("wifi", "Wi-Fi").replace("ethernet", "Ethernet")
                )
                conn = connection if connection and connection != "--" else None
                info[device] = {
                    "description": friendly if friendly != device else "",
                    "ssid": conn if "wifi" in dtype.lower() else None,
                    "network": conn,
                }

    # Fallback WiFi SSID
    if not any(d.get("ssid") for d in info.values()):
        out = _run(["iwgetid", "-r"])
        if out:
            for data in info.values():
                if data.get("description", "").lower() in ("wi-fi", "wifi", ""):
                    data["ssid"] = out
                    if not data["network"]:
                        data["network"] = out
                    break

    return info


def get_enrichment():
    system = platform.system()
    try:
        if system == "Windows":
            return _enrich_windows()
        if system == "Darwin":
            return _enrich_macos()
        return _enrich_linux()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Interface discovery
# ---------------------------------------------------------------------------


def get_interfaces():
    results = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    enrichment = get_enrichment()

    for iface, addr_list in sorted(addrs.items()):
        if iface.lower() in ("lo", "lo0", "loopback pseudo-interface 1"):
            continue
        if iface in stats and not stats[iface].isup:
            continue

        ipv4, ipv6 = None, None
        for addr in addr_list:
            if addr.family == socket.AF_INET:
                ipv4 = addr.address
            elif addr.family == socket.AF_INET6:
                ipv6 = addr.address.split("%")[0]

        if ipv4 or ipv6:
            extra = enrichment.get(iface, {})
            results.append(
                {
                    "name": iface,
                    "ipv4": ipv4,
                    "ipv6": ipv6,
                    "description": extra.get("description") or "",
                    "ssid": extra.get("ssid") or None,
                    "network": extra.get("network") or None,
                }
            )

    return results


# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------


def _create_tray_image():
    """Programmatically render a 64×64 tray icon with an "A" glyph."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Two-tone circle
    draw.ellipse([0, 0, size - 1, size - 1], fill="#7c3aed")
    draw.ellipse([4, 4, size - 5, size - 5], fill="#89b4fa")

    # Pick a font that exists on the current platform
    font = None
    for name in (
        "Segoe UI Bold", "Segoe UI",
        "SF Pro Display Bold", "SF Pro Text",
        "Cantarell Bold", "DejaVu Sans Bold",
        "Arial Bold", "Helvetica Bold",
        "Arial", "Helvetica", "DejaVu Sans",
    ):
        try:
            font = ImageFont.truetype(name, 34)
            break
        except (OSError, IOError):
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=30)
        except TypeError:
            font = ImageFont.load_default()

    # Centre the glyph
    bbox = draw.textbbox((0, 0), "A", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), "A", fill="white", font=font)

    return img


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class AddyApp:
    """Main application – window + optional system-tray icon."""

    # Catppuccin-Mocha inspired palette
    BG = "#1e1e2e"
    CARD_BG = "#2a2a3c"
    CARD_HOVER = "#33334d"
    TEXT = "#cdd6f4"
    TEXT_DIM = "#6c7086"
    ACCENT = "#89b4fa"
    ACCENT_HOVER = "#74c7ec"
    COPY_OK = "#a6e3a1"
    BORDER = "#45475a"
    CONN_COLOR = "#cba6f7"
    FONT_FAMILY = (
        "Segoe UI"
        if platform.system() == "Windows"
        else ("SF Pro Text" if platform.system() == "Darwin" else "Cantarell")
    )

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Addy")
        self.root.configure(bg=self.BG)
        self.root.resizable(False, False)
        self.root.minsize(420, 200)

        if platform.system() == "Darwin":
            self.root.createcommand("tk::mac::Quit", self._quit)

        self.tray_icon = None
        self._setup_tray()
        self._build_ui()
        self._populate()

    # -- System tray ----------------------------------------------------------

    def _setup_tray(self):
        if not _HAS_TRAY:
            self.root.protocol("WM_DELETE_WINDOW", self._quit)
            return

        try:
            self.tray_icon = pystray.Icon(
                "addy",
                _create_tray_image(),
                "Addy – click to show",
                menu=pystray.Menu(
                    pystray.MenuItem("Show Addy", self._tray_show, default=True),
                    pystray.MenuItem("Refresh", self._tray_refresh),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Quit", self._tray_quit),
                ),
            )
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        except Exception:
            self.tray_icon = None
            self.root.protocol("WM_DELETE_WINDOW", self._quit)

    def _minimize_to_tray(self):
        """Hide the window; the tray icon stays visible."""
        self.root.withdraw()

    def _tray_show(self, _icon=None, _item=None):
        self.root.after(0, self._show_window)

    def _show_window(self):
        self._populate()                     # refresh on re-show
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(150, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def _tray_refresh(self, _icon=None, _item=None):
        self.root.after(0, self._populate)

    def _tray_quit(self, _icon=None, _item=None):
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self._quit)

    def _quit(self):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    # -- Layout ---------------------------------------------------------------

    def _build_ui(self):
        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill="x", padx=20, pady=(18, 4))

        tk.Label(
            header,
            text="Addy",
            font=(self.FONT_FAMILY, 16, "bold"),
            bg=self.BG,
            fg=self.TEXT,
        ).pack(side="left")

        self.refresh_btn = tk.Label(
            header,
            text="↻  Refresh",
            font=(self.FONT_FAMILY, 10),
            bg=self.BG,
            fg=self.ACCENT,
            cursor="hand2",
        )
        self.refresh_btn.pack(side="right")
        self.refresh_btn.bind("<Button-1>", lambda _: self._populate())
        self.refresh_btn.bind(
            "<Enter>", lambda _: self.refresh_btn.configure(fg=self.ACCENT_HOVER)
        )
        self.refresh_btn.bind(
            "<Leave>", lambda _: self.refresh_btn.configure(fg=self.ACCENT)
        )

        tk.Label(
            self.root,
            text="Active network interfaces",
            font=(self.FONT_FAMILY, 10),
            bg=self.BG,
            fg=self.TEXT_DIM,
            anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 10))

        container = tk.Frame(self.root, bg=self.BG)
        container.pack(fill="both", expand=True, padx=20, pady=(0, 18))

        self.canvas = tk.Canvas(
            container, bg=self.BG, highlightthickness=0, bd=0
        )
        self.scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=self.canvas.yview
        )
        self.cards_frame = tk.Frame(self.canvas, bg=self.BG)

        self.cards_frame.bind(
            "<Configure>",
            lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.cards_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _bind_mousewheel(self):
        def _scroll(event):
            if platform.system() == "Darwin":
                self.canvas.yview_scroll(-1 * event.delta, "units")
            elif platform.system() == "Windows":
                self.canvas.yview_scroll(-1 * (event.delta // 120), "units")
            else:
                self.canvas.yview_scroll(
                    -1 if event.num == 4 else 1, "units"
                )

        if platform.system() == "Linux":
            self.canvas.bind_all("<Button-4>", _scroll)
            self.canvas.bind_all("<Button-5>", _scroll)
        else:
            self.canvas.bind_all("<MouseWheel>", _scroll)

    # -- Data → Cards ---------------------------------------------------------

    def _populate(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()

        interfaces = get_interfaces()

        if not interfaces:
            tk.Label(
                self.cards_frame,
                text="No active network interfaces found.",
                font=(self.FONT_FAMILY, 11),
                bg=self.BG,
                fg=self.TEXT_DIM,
                pady=30,
            ).pack()
            self._resize_window(1)
            return

        for iface in interfaces:
            self._make_card(iface)

        self._resize_window(len(interfaces))

    def _resize_window(self, card_count: int):
        per_card = 110
        ideal = 80 + 36 + per_card * card_count
        self.root.geometry(f"440x{min(ideal, 650)}")

    def _make_card(self, iface: dict):
        card = tk.Frame(
            self.cards_frame,
            bg=self.CARD_BG,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            padx=14,
            pady=10,
        )
        card.pack(fill="x", pady=(0, 8))

        # Row 1 — interface name  ·  connected-to
        title_row = tk.Frame(card, bg=self.CARD_BG)
        title_row.pack(fill="x")

        tk.Label(
            title_row,
            text=iface["name"],
            font=(self.FONT_FAMILY, 11, "bold"),
            bg=self.CARD_BG,
            fg=self.TEXT,
            anchor="w",
        ).pack(side="left")

        conn = iface["ssid"] or iface["network"]
        if conn:
            tk.Label(
                title_row,
                text="  ·  ",
                font=(self.FONT_FAMILY, 10),
                bg=self.CARD_BG,
                fg=self.TEXT_DIM,
            ).pack(side="left")
            tk.Label(
                title_row,
                text=conn,
                font=(self.FONT_FAMILY, 10),
                bg=self.CARD_BG,
                fg=self.CONN_COLOR,
                anchor="w",
            ).pack(side="left")

        # Row 2 — hardware adapter description
        if iface["description"]:
            tk.Label(
                card,
                text=iface["description"],
                font=(self.FONT_FAMILY, 9),
                bg=self.CARD_BG,
                fg=self.TEXT_DIM,
                anchor="w",
            ).pack(fill="x", pady=(2, 2))

        # IP rows
        if iface["ipv4"]:
            self._make_addr_row(card, "IPv4", iface["ipv4"])
        if iface["ipv6"]:
            self._make_addr_row(card, "IPv6", iface["ipv6"])

        self._attach_hover(card)

    def _make_addr_row(self, parent, label, address):
        row = tk.Frame(parent, bg=self.CARD_BG)
        row.pack(fill="x", pady=(4, 0))

        tk.Label(
            row,
            text=label,
            width=5,
            anchor="w",
            font=(self.FONT_FAMILY, 9),
            bg=self.CARD_BG,
            fg=self.TEXT_DIM,
        ).pack(side="left")

        tk.Label(
            row,
            text=address,
            anchor="w",
            font=(self.FONT_FAMILY, 10),
            bg=self.CARD_BG,
            fg=self.TEXT,
        ).pack(side="left", fill="x", expand=True)

        copy_btn = tk.Label(
            row,
            text="  Copy  ",
            font=(self.FONT_FAMILY, 9),
            bg=self.CARD_BG,
            fg=self.ACCENT,
            cursor="hand2",
        )
        copy_btn.pack(side="right")

        def _copy(_):
            self.root.clipboard_clear()
            self.root.clipboard_append(address)
            copy_btn.configure(text="  ✓ Copied  ", fg=self.COPY_OK)
            self.root.after(
                1200, lambda: copy_btn.configure(text="  Copy  ", fg=self.ACCENT)
            )

        copy_btn.bind("<Button-1>", _copy)
        copy_btn.bind(
            "<Enter>", lambda _: copy_btn.configure(fg=self.ACCENT_HOVER)
        )
        copy_btn.bind("<Leave>", lambda _: copy_btn.configure(fg=self.ACCENT))

    # -- Hover ----------------------------------------------------------------

    @staticmethod
    def _set_bg(widget, color):
        try:
            widget.configure(bg=color)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            AddyApp._set_bg(child, color)

    def _attach_hover(self, card):
        card.bind(
            "<Enter>", lambda _: self._set_bg(card, self.CARD_HOVER)
        )
        card.bind(
            "<Leave>", lambda _: self._set_bg(card, self.CARD_BG)
        )

    # -- Run ------------------------------------------------------------------

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AddyApp().run()
