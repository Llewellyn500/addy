#!/usr/bin/env python3
"""
Addy — A minimal cross-platform system-tray app that displays
network interface IP addresses with one-click copy.

Closing the window minimises to the system tray.
Right-click the tray icon → Quit to exit.
"""

import json
import platform
import socket
import subprocess
import sys
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from tkinter import ttk

import psutil

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

try:
    import pystray
    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False


_APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
_ASSET_DIR = _APP_ROOT / "docs" / "assets"


def _asset_path(filename):
    return _ASSET_DIR / filename


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd):
    """Run *cmd* and return stdout, or ``""`` on any failure."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        return r.stdout.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Platform-aware network enrichment
# ---------------------------------------------------------------------------

def _enrich_windows():
    info: dict[str, dict] = {}

    # Launch all three queries in parallel — the single PowerShell call is the
    # bottleneck (~1-2 s); ipconfig and netsh are fast (~100 ms each).
    ps_script = (
        "$a = @(Get-NetAdapter -IncludeHidden"
        " | Select-Object Name, InterfaceDescription);"
        " $p = @(Get-NetConnectionProfile"
        " | Select-Object InterfaceAlias, Name);"
        " ConvertTo-Json -Compress -Depth 2 @{a=$a;p=$p}"
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_ps = pool.submit(
            _run,
            ["powershell", "-NoLogo", "-NoProfile",
             "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        )
        fut_ipc = pool.submit(_run, ["ipconfig", "/all"])
        fut_wifi = pool.submit(_run, ["netsh", "wlan", "show", "interfaces"])

    # ── PowerShell: adapter descriptions + connection profiles ──────────────
    ps_out = fut_ps.result()
    if ps_out:
        try:
            data = json.loads(ps_out)
            adapters = data.get("a") or []
            if isinstance(adapters, dict):
                adapters = [adapters]
            profiles = data.get("p") or []
            if isinstance(profiles, dict):
                profiles = [profiles]

            for a in adapters:
                if isinstance(a, dict):
                    name = a.get("Name", "")
                    info[name] = {
                        "description": a.get("InterfaceDescription", ""),
                        "ssid": None,
                        "network": None,
                    }

            for p in profiles:
                if isinstance(p, dict):
                    alias = p.get("InterfaceAlias", "")
                    net_name = p.get("Name", "")
                    if alias in info and net_name:
                        info[alias]["network"] = net_name
        except (json.JSONDecodeError, TypeError):
            pass

    # ── ipconfig /all fallback ──────────────────────────────────────────────
    ipc_out = fut_ipc.result()
    if ipc_out:
        current: str | None = None
        for line in ipc_out.splitlines():
            stripped = line.strip()
            if "adapter " in line and stripped.endswith(":"):
                _, _, after = line.partition("adapter ")
                current = after.rstrip(":").strip()
            elif current is not None and stripped.startswith("Description"):
                _, _, val = stripped.partition(":")
                desc = val.strip()
                if current not in info:
                    info[current] = {"description": desc, "ssid": None, "network": None}
                elif not info[current]["description"] and desc:
                    info[current]["description"] = desc
                current = None

    # ── WiFi SSID via netsh ─────────────────────────────────────────────────
    wifi_out = fut_wifi.result()
    if wifi_out:
        current_iface = None
        for line in wifi_out.splitlines():
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

    out = _run(["networksetup", "-listallhardwareports"])
    current_port = None
    for line in out.splitlines():
        if line.startswith("Hardware Port:"):
            current_port = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and current_port:
            device = line.split(":", 1)[1].strip()
            info[device] = {"description": current_port, "ssid": None, "network": None}
            current_port = None

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

    out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,CONNECTION", "device", "status"])
    if out:
        for line in out.splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 3:
                device, dtype, connection = parts
                friendly = dtype.replace("wifi", "Wi-Fi").replace("ethernet", "Ethernet")
                conn = connection if connection and connection != "--" else None
                info[device] = {
                    "description": friendly if friendly != device else "",
                    "ssid": conn if "wifi" in dtype.lower() else None,
                    "network": conn,
                }

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


def _get_enrichment():
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
    enrichment = _get_enrichment()

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
            results.append({
                "name": iface,
                "ipv4": ipv4,
                "ipv6": ipv6,
                "description": extra.get("description") or "",
                "ssid": extra.get("ssid") or None,
                "network": extra.get("network") or None,
            })

    return results


# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _load_logo_asset(size):
    if not _HAS_PIL:
        return None

    for filename in ("icon.png", "logo.png"):
        path = _asset_path(filename)
        if not path.exists():
            continue

        try:
            with Image.open(path) as img:
                return img.convert("RGBA").resize(
                    (size, size),
                    Image.Resampling.LANCZOS,
                )
        except Exception:
            continue

    return None


def _create_logo_image(size=64):
    if not _HAS_PIL:
        return None

    asset_img = _load_logo_asset(size)
    if asset_img:
        return asset_img.copy()

    scale = 4
    canvas_size = size * scale

    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    offset = int(canvas_size * 0.05)
    leaf_w = canvas_size - offset - 8

    s_x0 = offset + 4
    s_y0 = offset + 4
    s_x1 = s_x0 + leaf_w
    s_y1 = s_y0 + leaf_w

    o_x0 = 4
    o_y0 = 4
    o_x1 = o_x0 + leaf_w
    o_y1 = o_y0 + leaf_w

    R_outer = leaf_w // 2

    def draw_leaf_shape(draw_obj, box, R, color):
        x0, y0, x1, y1 = box
        draw_obj.rectangle([x0 + R, y0 + R, x1 - R, y1 - R], fill=color)
        draw_obj.rectangle([x0, y0, x0 + R, y1 - R], fill=color)
        draw_obj.rectangle([x0 + R, y0, x1 - R, y0 + R], fill=color)
        draw_obj.rectangle([x0 + R, y1 - R, x1 - R, y1], fill=color)
        draw_obj.rectangle([x1 - R, y0 + R, x1, y1], fill=color)
        draw_obj.pieslice([x0, y1 - 2*R, x0 + 2*R, y1], 90, 180, fill=color)
        draw_obj.pieslice([x1 - 2*R, y0, x1, y0 + 2*R], 270, 360, fill=color)

    draw_leaf_shape(draw, [s_x0, s_y0, s_x1, s_y1], R_outer, "black")
    draw_leaf_shape(draw, [o_x0, o_y0, o_x1, o_y1], R_outer, "black")

    border = max(4, int(leaf_w * 0.08))
    p_x0 = o_x0 + border
    p_y0 = o_y0 + border
    p_x1 = o_x1 - border
    p_y1 = o_y1 - border
    R_inner = R_outer - border

    draw_leaf_shape(draw, [p_x0, p_y0, p_x1, p_y1], R_inner, "#8252e9")

    cx = (p_x0 + p_x1) // 2
    cy = (p_y0 + p_y1) // 2

    font = None
    font_size = int(leaf_w * 0.55)
    for name in (
        "seguibl.ttf", "ariblk.ttf", "comicbd.ttf", "impact.ttf", "arialbd.ttf",
        "Segoe UI Black", "Segoe UI Bold", "Arial Black", "Arial Bold"
    ):
        try:
            font = ImageFont.truetype(name, font_size)
            break
        except (OSError, IOError):
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "A", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = cx - tw // 2 - bbox[0]
    ty = cy - th // 2 - bbox[1]

    stroke_width = max(1, int(leaf_w * 0.02))
    draw.text((tx, ty), "A", fill="black", font=font, stroke_width=stroke_width, stroke_fill="black")

    img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def _create_tray_image():
    if not _HAS_PIL:
        return None

    if _HAS_PIL:
        img = _create_logo_image(64)
        if img:
            return img

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, size - 1, size - 1], fill="#7c3aed")
    draw.text((24, 15), "A", fill="white")
    return img


# ---------------------------------------------------------------------------
# NeoFrame custom panel widgets
# ---------------------------------------------------------------------------

BaseFrame = tk.Canvas if _HAS_PIL else tk.Frame


class NeoFrame(BaseFrame):
    """A card frame that draws a Neo-brutalist panel with 2 rounded corners (leaf shape), thick borders and solid black shadow."""

    def __init__(self, parent, bg, card_bg, border_color, border_width=2, shadow_offset=5, radius=20, card_hover=None, **kwargs):
        if not _HAS_PIL:
            super().__init__(
                parent, bg=card_bg, highlightbackground=border_color,
                highlightthickness=border_width, **kwargs
            )
            self.inner_frame = self
            self.card_bg = card_bg
            self.card_hover_color = card_hover or card_bg
            return

        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, **kwargs)
        self.bg = bg
        self.card_bg_color = card_bg
        self.card_bg = card_bg
        self.card_hover_color = card_hover or card_bg
        self.border_color = border_color
        self.border_width = border_width
        self.shadow_offset = shadow_offset
        self.radius = radius

        self.inner_frame = tk.Frame(self, bg=self.card_bg)
        # Offset padding to keep content inside the card borders and make space for the shadow
        self.inner_frame.pack(
            fill="both", expand=True,
            padx=(self.border_width + 10, self.shadow_offset + self.border_width + 10),
            pady=(self.border_width + 8, self.shadow_offset + self.border_width + 8)
        )

        self.bind("<Configure>", self._on_configure)
        self._bg_image = None
        self._bg_image_id = None
        self._attach_hover_events()

    def set_card_bg(self, color):
        if not _HAS_PIL:
            self.configure(bg=color)
            self._set_children_bg(self, color)
            return
        if self.card_bg != color:
            self.card_bg = color
            self.inner_frame.configure(bg=color)
            self._set_children_bg(self.inner_frame, color)
            self._redraw()

    def _set_children_bg(self, widget, color):
        for child in widget.winfo_children():
            try:
                child.configure(bg=color)
            except tk.TclError:
                pass
            self._set_children_bg(child, color)

    def _attach_hover_events(self):
        def on_enter(event):
            self.set_card_bg(self.card_hover_color)

        def on_leave(event):
            x, y = self.winfo_pointerxy()
            x0 = self.winfo_rootx()
            y0 = self.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            if not (x0 <= x < x0 + w and y0 <= y < y0 + h):
                self.set_card_bg(self.card_bg_color)

        self.bind("<Enter>", on_enter)
        self.bind("<Leave>", on_leave)
        self.inner_frame.bind("<Enter>", on_enter)
        self.inner_frame.bind("<Leave>", on_leave)

    def bind_hover_to(self, widget):
        if not _HAS_PIL:
            return
        def on_enter(event):
            self.set_card_bg(self.card_hover_color)

        def on_leave(event):
            x, y = self.winfo_pointerxy()
            x0 = self.winfo_rootx()
            y0 = self.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            if not (x0 <= x < x0 + w and y0 <= y < y0 + h):
                self.set_card_bg(self.card_bg_color)

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
        for child in widget.winfo_children():
            self.bind_hover_to(child)

    def _redraw(self):
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= self.shadow_offset * 2 or h <= self.shadow_offset * 2:
            return

        scale = 2
        sw, sh = w * scale, h * scale
        sb = self.border_width * scale
        so = self.shadow_offset * scale
        sr = self.radius * scale

        img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        def draw_leaf_shape(draw_obj, box_coords, rad, color):
            x0, y0, x1, y1 = box_coords
            x0, x1 = min(x0, x1), max(x0, x1)
            y0, y1 = min(y0, y1), max(y0, y1)
            if (x1 - x0) <= 2 * rad or (y1 - y0) <= 2 * rad:
                draw_obj.rectangle([x0, y0, x1, y1], fill=color)
                return
            draw_obj.rectangle([x0 + rad, y0 + rad, x1 - rad, y1 - rad], fill=color)
            draw_obj.rectangle([x0, y0, x0 + rad, y1 - rad], fill=color)
            draw_obj.rectangle([x0 + rad, y0, x1 - rad, y0 + rad], fill=color)
            draw_obj.rectangle([x0 + rad, y1 - rad, x1 - rad, y1], fill=color)
            draw_obj.rectangle([x1 - rad, y0 + rad, x1, y1], fill=color)
            draw_obj.pieslice([x0, y1 - 2*rad, x0 + 2*rad, y1], 90, 180, fill=color)
            draw_obj.pieslice([x1 - 2*rad, y0, x1, y0 + 2*rad], 270, 360, fill=color)

        # 1. Draw solid black leaf shadow
        shadow_box = [so, so, sw - 1, sh - 1]
        draw_leaf_shape(draw, shadow_box, sr, "black")

        # 2. Draw card border leaf (outer card area, black)
        border_box = [0, 0, sw - so - 1, sh - so - 1]
        draw_leaf_shape(draw, border_box, sr, "black")

        # 3. Draw card interior leaf (inner card area, filled with self.card_bg)
        interior_box = [sb, sb, sw - so - sb - 1, sh - so - sb - 1]
        interior_rad = max(0, sr - sb)
        draw_leaf_shape(draw, interior_box, interior_rad, self.card_bg)

        img = img.resize((w, h), Image.Resampling.LANCZOS)
        self._bg_image = ImageTk.PhotoImage(img)

        if self._bg_image_id is not None:
            self.delete(self._bg_image_id)
        self._bg_image_id = self.create_image(0, 0, image=self._bg_image, anchor="nw")
        self.tag_lower(self._bg_image_id)

    def _on_configure(self, event):
        self._redraw()
def _load_font(family, size):
    """Try to load a scalable font, falling back to common system fonts."""
    names = []
    if family:
        names.extend([family, family.lower(), family.replace(" ", "").lower()])
    
    # Common system font files
    is_bold = family and "bold" in str(family).lower()
    names.extend([
        "segoeuib" if is_bold else "segoeui",
        "arialbd" if is_bold else "arial",
        "tahoma",
        "ubuntu",
        "DejaVuSans",
        "LiberationSans"
    ])
    
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
        try:
            return ImageFont.truetype(name + ".ttf", size)
        except Exception:
            pass
            
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


class NeoButton(tk.Canvas):
    """A custom Neo-brutalist leaf-shaped button (2 rounded corners, 2 sharp corners) with hover effects."""

    def __init__(self, parent, text, command, bg, button_bg="#ffffff", hover_bg="#ffd23f", active_bg="#16a34a", active_fg="#ffffff", border_width=2, shadow_offset=3, radius=8, font=None, **kwargs):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, cursor="hand2", **kwargs)
        self.text = text
        self.command = command
        self.bg_color = bg
        self.button_bg = button_bg
        self.hover_bg = hover_bg
        self.active_bg = active_bg
        self.active_fg = active_fg
        self.current_bg = button_bg
        self.current_fg = "#000000"
        self.border_width = border_width
        self.shadow_offset = shadow_offset
        self.radius = radius
        self.font = font

        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", lambda _: self._on_click())
        self.bind("<Enter>", lambda _: self._on_enter())
        self.bind("<Leave>", lambda _: self._on_leave())

        self._bg_image = None
        self._bg_image_id = None

    def configure_button(self, text=None, bg=None, fg=None):
        if text is not None:
            self.text = text
        if bg is not None:
            self.current_bg = bg
        if fg is not None:
            self.current_fg = fg
        self._redraw()

    def _on_click(self):
        if self.command:
            self.command()

    def _on_enter(self):
        if self.current_bg == self.button_bg:
            self.current_bg = self.hover_bg
            self._redraw()

    def _on_leave(self):
        if self.current_bg == self.hover_bg:
            self.current_bg = self.button_bg
            self._redraw()

    def _on_configure(self, event):
        self._redraw()

    def _redraw(self):
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= self.shadow_offset * 2 or h <= self.shadow_offset * 2:
            return

        scale = 2
        sw, sh = w * scale, h * scale
        sb = self.border_width * scale
        so = self.shadow_offset * scale
        sr = self.radius * scale

        img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        def draw_leaf_shape(draw_obj, box_coords, rad, color):
            x0, y0, x1, y1 = box_coords
            x0, x1 = min(x0, x1), max(x0, x1)
            y0, y1 = min(y0, y1), max(y0, y1)
            if (x1 - x0) <= 2 * rad or (y1 - y0) <= 2 * rad:
                draw_obj.rectangle([x0, y0, x1, y1], fill=color)
                return
            draw_obj.rectangle([x0 + rad, y0 + rad, x1 - rad, y1 - rad], fill=color)
            draw_obj.rectangle([x0, y0, x0 + rad, y1 - rad], fill=color)
            draw_obj.rectangle([x0 + rad, y0, x1 - rad, y0 + rad], fill=color)
            draw_obj.rectangle([x0 + rad, y1 - rad, x1 - rad, y1], fill=color)
            draw_obj.rectangle([x1 - rad, y0 + rad, x1, y1], fill=color)
            draw_obj.pieslice([x0, y1 - 2*rad, x0 + 2*rad, y1], 90, 180, fill=color)
            draw_obj.pieslice([x1 - 2*rad, y0, x1, y0 + 2*rad], 270, 360, fill=color)

        # 1. Draw solid black leaf shadow
        shadow_box = [so, so, sw - 1, sh - 1]
        draw_leaf_shape(draw, shadow_box, sr, "black")

        # 2. Draw card border leaf (black outline)
        border_box = [0, 0, sw - so - 1, sh - so - 1]
        draw_leaf_shape(draw, border_box, sr, "black")

        # 3. Draw card interior leaf (filled with self.current_bg)
        interior_box = [sb, sb, sw - so - sb - 1, sh - so - sb - 1]
        interior_rad = max(0, sr - sb)
        draw_leaf_shape(draw, interior_box, interior_rad, self.current_bg)

        # 4. Draw text centered
        font_family = "Segoe UI"
        font_size = 10
        if self.font:
            if isinstance(self.font, tuple):
                if len(self.font) > 0:
                    font_family = self.font[0]
                if len(self.font) > 1:
                    font_size = self.font[1]
            elif isinstance(self.font, str):
                font_family = self.font

        font = _load_font(font_family, font_size * scale)

        cx = (sw - so) // 2
        cy = (sh - so) // 2

        display_text = self.text
        has_refresh_icon = False
        has_check_icon = False
        if display_text.endswith(" ↻"):
            display_text = display_text[:-2]
            has_refresh_icon = True
        elif display_text.endswith("↻"):
            display_text = display_text[:-1]
            has_refresh_icon = True
        elif display_text.endswith(" ✓"):
            display_text = display_text[:-2]
            has_check_icon = True
        elif display_text.endswith("✓"):
            display_text = display_text[:-1]
            has_check_icon = True

        bbox = draw.textbbox((0, 0), display_text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        icon_size = int(12 * scale)
        spacing = int(5 * scale)

        if has_refresh_icon or has_check_icon:
            if tw > 0:
                total_width = tw + spacing + icon_size
            else:
                total_width = icon_size
        else:
            total_width = tw

        tx = cx - total_width // 2 - bbox[0]
        ty = cy - th // 2 - bbox[1]

        if tw > 0:
            draw.text((tx, ty), display_text, fill=self.current_fg, font=font)

        if has_refresh_icon:
            if tw > 0:
                ix0 = tx + bbox[0] + tw + spacing
            else:
                ix0 = cx - icon_size // 2
            
            iy0 = cy - icon_size // 2
            icx = ix0 + icon_size // 2
            icy = iy0 + icon_size // 2
            
            r = 4 * scale
            line_width = max(1, int(1 * scale))
            arrow_size = int(2.2 * scale)
            
            x0, y0 = icx - r, icy - r
            x1, y1 = icx + r, icy + r
            
            draw.arc([x0, y0, x1, y1], start=0, end=270, fill=self.current_fg, width=line_width)
            
            p1 = (icx + arrow_size, icy - r)
            p2 = (icx, icy - r - arrow_size)
            p3 = (icx, icy - r + arrow_size)
            
            draw.polygon([p1, p2, p3], fill=self.current_fg)
        elif has_check_icon:
            if tw > 0:
                ix0 = tx + bbox[0] + tw + spacing
            else:
                ix0 = cx - icon_size // 2
            
            iy0 = cy - icon_size // 2
            icx = ix0 + icon_size // 2
            icy = iy0 + icon_size // 2
            
            line_width = max(1, int(1.5 * scale))
            
            p1 = (icx - 3 * scale, icy)
            p2 = (icx - 0.5 * scale, icy + 2.5 * scale)
            p3 = (icx + 3 * scale, icy - 2 * scale)
            
            draw.line([p1, p2, p3], fill=self.current_fg, width=line_width, joint="round")

        img = img.resize((w, h), Image.Resampling.LANCZOS)
        self._bg_image = ImageTk.PhotoImage(img)

        self.delete("all")
        self._bg_image_id = self.create_image(0, 0, image=self._bg_image, anchor="nw")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class AddyApp:
    """Main application — window + optional system-tray icon."""

    BG = "#0c0a14"             # Dark violet-black (logo theme)
    CARD_BG = "#8252e9"          # Vibrant logo violet
    CARD_HOVER = "#9b70ff"       # Lighter logo violet
    TEXT = "#ffffff"             # Pure white text
    TEXT_DIM = "#e2daff"         # Soft lavender secondary text
    ACCENT = "#ffd23f"           # Vibrant yellow accent
    ACCENT_HOVER = "#ffffff"     # Pure white
    COPY_OK = "#10b981"          # Strong green
    BORDER = "#000000"           # Deep black border
    CONN_COLOR = "#ffd23f"       # Vibrant yellow
    FONT_FAMILY = (
        "Segoe UI"
        if platform.system() == "Windows"
        else ("SF Pro Text" if platform.system() == "Darwin" else "Cantarell")
    )

    def __init__(self):
        if platform.system() == "Windows":
            try:
                import ctypes
                myappid = "llewellyn500.addy.trayapp.v1.0"
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception:
                pass

        self.root = tk.Tk()
        self.root.title("Addy")
        self.root.configure(bg=self.BG)
        self.root.resizable(False, False)
        self.root.minsize(420, 200)

        if platform.system() == "Darwin":
            self.root.createcommand("tk::mac::Quit", self._quit)

        # Set window icon photo matching the logo
        if _HAS_PIL:
            try:
                self.window_icon_pil = _create_logo_image(32)
                self.window_icon = ImageTk.PhotoImage(self.window_icon_pil)
                self.root.iconphoto(True, self.window_icon)
            except Exception:
                pass

        # Data cache — accessed on main thread only (via root.after)
        self._cache: list[dict] = []
        self._refreshing = False

        self.tray_icon = None
        self._setup_tray()
        self._build_ui()

        # First launch: show loading placeholder, fetch data in background
        self._show_loading()
        self._refresh_async()

    # -- System tray ----------------------------------------------------------

    def _setup_tray(self):
        if not _HAS_TRAY:
            self.root.protocol("WM_DELETE_WINDOW", self._quit)
            return
        try:
            tray_image = _create_tray_image()
            if tray_image is None:
                raise RuntimeError("tray icon image unavailable")

            self.tray_icon = pystray.Icon(
                "addy",
                tray_image,
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
        self.root.withdraw()

    def _tray_show(self, _icon=None, _item=None):
        self.root.after(0, self._show_window)

    def _show_window(self):
        # Render cached data instantly — no subprocess calls
        self._render_cards()
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(150, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        # Quietly refresh in the background
        self._refresh_async()

    def _tray_refresh(self, _icon=None, _item=None):
        self.root.after(0, lambda: self._refresh_async(force=True))

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

    # -- Async data fetching --------------------------------------------------

    def _refresh_async(self, force=False):
        """Kick off a background fetch.  Skips if one is already running."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self.refresh_btn.configure_button(text="Scanning...", bg="#ffd23f")
        except Exception:
            pass
        threading.Thread(target=self._fetch_data, args=(force,), daemon=True).start()

    def _fetch_data(self, force=False):
        """Run in background thread — never touches tkinter directly."""
        try:
            interfaces = get_interfaces()
            if force or interfaces != self._cache:
                self._cache = interfaces
                self.root.after(0, self._render_cards)
        finally:
            self._refreshing = False
            self.root.after(0, self._reset_refresh_btn)

    def _reset_refresh_btn(self):
        try:
            self.refresh_btn.configure_button(text="Refresh ↻", bg="#ffffff")
        except Exception:
            pass

    # -- Layout ---------------------------------------------------------------

    def _build_ui(self):
        # Configure custom scrollbar style to match Neo-brutalist theme
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.style.configure(
            "Vertical.TScrollbar",
            troughcolor=self.BG,
            background=self.CARD_BG,
            bordercolor="#000000",
            arrowcolor="#ffffff",
            lightcolor=self.CARD_BG,
            darkcolor=self.CARD_BG,
            gripcount=0
        )
        self.style.map(
            "Vertical.TScrollbar",
            background=[("active", "#ffd23f"), ("pressed", "#ffd23f")],
            lightcolor=[("active", "#ffd23f"), ("pressed", "#ffd23f")],
            darkcolor=[("active", "#ffd23f"), ("pressed", "#ffd23f")],
        )

        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill="x", padx=20, pady=(18, 4))

        if _HAS_PIL:
            try:
                self.logo_img_pil = _create_logo_image(28)
                self.logo_img = ImageTk.PhotoImage(self.logo_img_pil)
                logo_lbl = tk.Label(header, image=self.logo_img, bg=self.BG)
                logo_lbl.pack(side="left", padx=(0, 8))
            except Exception:
                pass

        tk.Label(
            header, text="ADDY", font=(self.FONT_FAMILY, 20, "bold"),
            bg=self.BG, fg=self.TEXT,
        ).pack(side="left")

        self.refresh_btn = NeoButton(
            header, text="Refresh ↻", command=lambda: self._refresh_async(force=True),
            bg=self.BG, button_bg="#ffffff", hover_bg="#ffd23f",
            width=124, height=40, font=(self.FONT_FAMILY, 12, "bold")
        )
        self.refresh_btn.pack(side="right")

        import webbrowser
        self.github_btn = NeoButton(
            header, text="GitHub", command=lambda: webbrowser.open("https://github.com/Llewellyn500/addy"),
            bg=self.BG, button_bg="#ffffff", hover_bg="#ffd23f",
            width=100, height=40, font=(self.FONT_FAMILY, 12, "bold")
        )
        self.github_btn.pack(side="right", padx=(0, 10))

        tk.Label(
            self.root, text="Active network interfaces",
            font=(self.FONT_FAMILY, 10, "bold"), bg=self.BG, fg=self.TEXT, anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 10))

        container = tk.Frame(self.root, bg=self.BG)
        container.pack(fill="both", expand=True, padx=20, pady=(0, 18))

        self.canvas = tk.Canvas(container, bg=self.BG, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=self.canvas.yview,
            style="Vertical.TScrollbar",
        )
        self.cards_frame = tk.Frame(self.canvas, bg=self.BG)

        self.cards_frame.bind(
            "<Configure>",
            lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.cards_frame, anchor="nw",
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
                self.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")

        if platform.system() == "Linux":
            self.canvas.bind_all("<Button-4>", _scroll)
            self.canvas.bind_all("<Button-5>", _scroll)
        else:
            self.canvas.bind_all("<MouseWheel>", _scroll)

    # -- Rendering ------------------------------------------------------------

    def _show_loading(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()
        tk.Label(
            self.cards_frame, text="Scanning networks…",
            font=(self.FONT_FAMILY, 11, "bold"), bg=self.BG, fg=self.TEXT, pady=30,
        ).pack()
        self._resize_window(1)

    def _render_cards(self):
        """Render interface cards from the in-memory cache (instant)."""
        for w in self.cards_frame.winfo_children():
            w.destroy()

        interfaces = self._cache

        if not interfaces:
            tk.Label(
                self.cards_frame, text="No active network interfaces found.",
                font=(self.FONT_FAMILY, 11, "bold"), bg=self.BG, fg=self.TEXT, pady=30,
            ).pack()
            self._resize_window(1)
            return

        for iface in interfaces:
            self._make_card(iface)
        self._resize_window(len(interfaces))

    def _resize_window(self, card_count: int):
        per_card = 120
        ideal = 80 + 36 + per_card * card_count
        self.root.geometry(f"440x{min(ideal, 650)}")

    def _make_card(self, iface: dict):
        card = NeoFrame(
            self.cards_frame, bg=self.BG, card_bg=self.CARD_BG,
            border_color=self.BORDER, border_width=2, shadow_offset=5,
            card_hover=self.CARD_HOVER
        )
        card.pack(fill="x", pady=(0, 12))

        # Row 1 — interface name  ·  connected-to
        title_row = tk.Frame(card.inner_frame, bg=self.CARD_BG)
        title_row.pack(fill="x")

        tk.Label(
            title_row, text=iface["name"],
            font=(self.FONT_FAMILY, 11, "bold"),
            bg=self.CARD_BG, fg=self.TEXT, anchor="w",
        ).pack(side="left")

        conn = iface["ssid"] or iface["network"]
        if conn:
            tk.Label(
                title_row, text="  ·  ",
                font=(self.FONT_FAMILY, 10, "bold"), bg=self.CARD_BG, fg=self.TEXT,
            ).pack(side="left")
            tk.Label(
                title_row, text=conn,
                font=(self.FONT_FAMILY, 10, "bold"), bg=self.CARD_BG,
                fg=self.CONN_COLOR, anchor="w",
            ).pack(side="left")

        # Row 2 — hardware adapter description
        if iface["description"]:
            tk.Label(
                card.inner_frame, text=iface["description"],
                font=(self.FONT_FAMILY, 9), bg=self.CARD_BG,
                fg=self.TEXT_DIM, anchor="w",
            ).pack(fill="x", pady=(2, 2))

        # IP rows
        if iface["ipv4"]:
            self._make_addr_row(card.inner_frame, "IPv4", iface["ipv4"])
        if iface["ipv6"]:
            self._make_addr_row(card.inner_frame, "IPv6", iface["ipv6"])

        card.bind_hover_to(card.inner_frame)

    def _make_addr_row(self, parent, label, address):
        row = tk.Frame(parent, bg=self.CARD_BG)
        row.pack(fill="x", pady=(4, 0))

        tk.Label(
            row, text=label, width=5, anchor="w",
            font=(self.FONT_FAMILY, 9, "bold"), bg=self.CARD_BG, fg=self.TEXT,
        ).pack(side="left")

        tk.Label(
            row, text=address, anchor="w",
            font=(self.FONT_FAMILY, 10), bg=self.CARD_BG, fg=self.TEXT,
        ).pack(side="left", fill="x", expand=True)

        copy_btn = NeoButton(
            row, text="Copy", command=None,
            bg=self.CARD_BG, button_bg="#ffffff", hover_bg="#ffd23f",
            width=84, height=34, font=(self.FONT_FAMILY, 10, "bold")
        )
        copy_btn.pack(side="right")

        def _copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(address)
            copy_btn.configure_button(text="Copied ✓", bg="#16a34a", fg="#ffffff")
            self.root.after(
                1200, lambda: copy_btn.configure_button(text="Copy", bg="#ffffff", fg="#000000"),
            )

        copy_btn.command = _copy

    # -- Hover ----------------------------------------------------------------
    # Custom hover logic is handled natively inside NeoFrame.

    # -- Run ------------------------------------------------------------------

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AddyApp().run()
