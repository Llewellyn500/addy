#!/usr/bin/env python3
"""Android companion app for Addy.

The desktop app is a Tk system-tray utility. Android has no equivalent tray,
so this entrypoint presents the same network-address copy workflow as a
foreground mobile app.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

__version__ = "1.0.0"


BG = "#0c0a14"
CARD_BG = "#8252e9"
TEXT = "#ffffff"
TEXT_DIM = "#e2daff"
ACCENT = "#ffd23f"
COPY_OK = "#10b981"
INK = "#0c0a14"
ASSET_DIR = Path(__file__).resolve().parent / "assets"


def _rgba(hex_color: str, alpha: float = 1.0) -> list[float]:
    raw = hex_color.strip().lstrip("#")
    return [
        int(raw[0:2], 16) / 255,
        int(raw[2:4], 16) / 255,
        int(raw[4:6], 16) / 255,
        alpha,
    ]


@dataclass(frozen=True)
class InterfaceInfo:
    name: str
    ipv4: str | None = None
    ipv6: str | None = None
    description: str = ""
    network: str | None = None


class Surface(BoxLayout):
    bg_color = ListProperty(_rgba(CARD_BG))

    def __init__(self, bg_color=None, radius=8, **kwargs):
        super().__init__(**kwargs)
        if bg_color is not None:
            self.bg_color = bg_color
        self._radius = radius

        with self.canvas.before:
            self._canvas_color = Color(*self.bg_color)
            self._canvas_rect = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(self._radius)],
            )

        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.bind(bg_color=self._sync_canvas)

    def _sync_canvas(self, *_):
        self._canvas_color.rgba = self.bg_color
        self._canvas_rect.pos = self.pos
        self._canvas_rect.size = self.size
        self._canvas_rect.radius = [dp(self._radius)]


def _label(
    text: str,
    *,
    color=TEXT,
    size=14,
    bold=False,
    height=28,
    halign="left",
    shorten=False,
    size_hint_x=1,
    width=None,
):
    label = Label(
        text=text,
        color=_rgba(color),
        font_size=sp(size),
        bold=bold,
        halign=halign,
        valign="middle",
        shorten=shorten,
        shorten_from="right",
        size_hint_x=size_hint_x,
        size_hint_y=None,
        height=dp(height),
    )
    if width is not None:
        label.width = dp(width)
    label.bind(size=lambda instance, *_: setattr(instance, "text_size", (instance.width, None)))
    return label


def _button(text: str, *, width=96, color=INK, bg="#ffffff"):
    return Button(
        text=text,
        color=_rgba(color),
        background_normal="",
        background_down="",
        background_color=_rgba(bg),
        font_size=sp(14),
        bold=True,
        size_hint=(None, None),
        size=(dp(width), dp(48)),
    )


def _java_interfaces() -> list[InterfaceInfo]:
    try:
        from jnius import autoclass
    except Exception:
        return []

    try:
        NetworkInterface = autoclass("java.net.NetworkInterface")
        interfaces = NetworkInterface.getNetworkInterfaces()
    except Exception:
        return []

    network_label = _android_network_label()
    results: list[InterfaceInfo] = []

    while interfaces and interfaces.hasMoreElements():
        iface = interfaces.nextElement()

        try:
            if iface.isLoopback() or not iface.isUp():
                continue
        except Exception:
            continue

        ipv4 = None
        ipv6 = None
        addrs = iface.getInetAddresses()

        while addrs and addrs.hasMoreElements():
            addr = addrs.nextElement()

            try:
                if addr.isLoopbackAddress():
                    continue
                host = str(addr.getHostAddress()).split("%", 1)[0]
            except Exception:
                continue

            if not host or host in {"0.0.0.0", "::"}:
                continue
            if ":" in host:
                ipv6 = ipv6 or host
            else:
                ipv4 = ipv4 or host

        if not (ipv4 or ipv6):
            continue

        name = str(iface.getName())
        description = str(iface.getDisplayName() or name)
        results.append(
            InterfaceInfo(
                name=name,
                ipv4=ipv4,
                ipv6=ipv6,
                description=description if description != name else "",
                network=network_label,
            )
        )

    return sorted(results, key=lambda item: item.name)


def _android_network_label() -> str | None:
    try:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        NetworkCapabilities = autoclass("android.net.NetworkCapabilities")

        activity = PythonActivity.mActivity
        manager = activity.getSystemService(Context.CONNECTIVITY_SERVICE)
        network = manager.getActiveNetwork()
        capabilities = manager.getNetworkCapabilities(network)
        if capabilities is None:
            return None

        if capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI):
            ssid = _android_wifi_ssid(activity, Context)
            return ssid or "Wi-Fi"
        if capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR):
            return "Cellular"
        if capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET):
            return "Ethernet"
        if capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN):
            return "VPN"
    except Exception:
        return None

    return None


def _android_wifi_ssid(activity, context_class) -> str | None:
    try:
        wifi = activity.getApplicationContext().getSystemService(context_class.WIFI_SERVICE)
        info = wifi.getConnectionInfo()
        ssid = str(info.getSSID()).strip('"')
    except Exception:
        return None

    if not ssid or ssid == "<unknown ssid>":
        return None
    return ssid


def _socket_fallback() -> list[InterfaceInfo]:
    addresses: set[str] = set()

    try:
        hostname = socket.gethostname()
        for family in (socket.AF_INET, socket.AF_INET6):
            for result in socket.getaddrinfo(hostname, None, family):
                host = result[4][0].split("%", 1)[0]
                if host and not host.startswith("127.") and host != "::1":
                    addresses.add(host)
    except Exception:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host = sock.getsockname()[0]
            if host and not host.startswith("127."):
                addresses.add(host)
    except Exception:
        pass

    if not addresses:
        return []

    ipv4 = next((addr for addr in sorted(addresses) if ":" not in addr), None)
    ipv6 = next((addr for addr in sorted(addresses) if ":" in addr), None)
    return [InterfaceInfo(name="device", ipv4=ipv4, ipv6=ipv6, description="Local device")]


def get_interfaces() -> list[InterfaceInfo]:
    return _java_interfaces() or _socket_fallback()


class InterfaceCard(Surface):
    def __init__(self, info: InterfaceInfo, **kwargs):
        super().__init__(
            orientation="vertical",
            bg_color=_rgba(CARD_BG),
            padding=[dp(16), dp(14), dp(16), dp(14)],
            spacing=dp(8),
            size_hint_y=None,
            **kwargs,
        )
        self.info = info

        heading = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(30))
        heading.add_widget(_label(info.name, size=16, bold=True, height=30))
        if info.network:
            heading.add_widget(
                _label(
                    info.network,
                    color=ACCENT,
                    size=13,
                    bold=True,
                    height=30,
                    shorten=True,
                    size_hint_x=None,
                    width=120,
                )
            )
        self.add_widget(heading)

        if info.description:
            self.add_widget(_label(info.description, color=TEXT_DIM, size=13, height=26, shorten=True))

        if info.ipv4:
            self.add_widget(self._address_row("IPv4", info.ipv4))
        if info.ipv6:
            self.add_widget(self._address_row("IPv6", info.ipv6))

        row_count = int(bool(info.ipv4)) + int(bool(info.ipv6))
        self.height = dp(86 + (26 if info.description else 0) + row_count * 56)

    def _address_row(self, kind: str, address: str):
        row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(52))
        row.add_widget(_label(kind, size=13, bold=True, height=52, size_hint_x=None, width=54))
        row.add_widget(_label(address, size=14, height=52, shorten=True))

        copy_btn = _button("Copy", width=92)
        copy_btn.bind(on_release=lambda btn: self._copy_address(btn, address))
        row.add_widget(copy_btn)
        return row

    def _copy_address(self, btn: Button, address: str):
        Clipboard.copy(address)
        btn.text = "Copied"
        btn.background_color = _rgba(COPY_OK)
        btn.color = _rgba(TEXT)

        def reset(_):
            btn.text = "Copy"
            btn.background_color = _rgba("#ffffff")
            btn.color = _rgba(INK)

        Clock.schedule_once(reset, 1.2)


class AddyAndroidApp(App):
    title = "Addy"
    icon = str(ASSET_DIR / "icon.png")

    def build(self):
        Window.clearcolor = _rgba(BG)

        root = BoxLayout(
            orientation="vertical",
            padding=[dp(20), dp(34), dp(20), dp(20)],
            spacing=dp(16),
        )

        header = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(52))
        logo = Image(source=str(ASSET_DIR / "logo.png"), size_hint=(None, None), size=(dp(44), dp(44)))
        header.add_widget(logo)
        header.add_widget(_label("ADDY", size=24, bold=True, height=52))

        refresh = _button("Refresh", width=112)
        refresh.bind(on_release=lambda *_: self.refresh_interfaces())
        header.add_widget(refresh)
        root.add_widget(header)

        self.status_label = _label("Scanning networks...", color=TEXT_DIM, size=13, height=24)
        root.add_widget(self.status_label)

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(4))
        self.cards = BoxLayout(orientation="vertical", spacing=dp(12), size_hint_y=None)
        self.cards.bind(minimum_height=self.cards.setter("height"))
        scroll.add_widget(self.cards)
        root.add_widget(scroll)

        Clock.schedule_once(lambda _: self.refresh_interfaces(), 0.1)
        return root

    def refresh_interfaces(self):
        self.status_label.text = "Scanning networks..."
        Clock.schedule_once(lambda _: self._render_interfaces(get_interfaces()), 0)

    def _render_interfaces(self, interfaces: list[InterfaceInfo]):
        self.cards.clear_widgets()

        if not interfaces:
            empty = Surface(
                orientation="vertical",
                bg_color=_rgba(CARD_BG),
                padding=[dp(16), dp(20), dp(16), dp(20)],
                size_hint_y=None,
                height=dp(96),
            )
            empty.add_widget(_label("No active network interfaces found.", size=15, bold=True, height=42))
            self.cards.add_widget(empty)
            self.status_label.text = "No active interfaces"
            return

        for info in interfaces:
            self.cards.add_widget(InterfaceCard(info))

        noun = "interface" if len(interfaces) == 1 else "interfaces"
        self.status_label.text = f"{len(interfaces)} active {noun}"


if __name__ == "__main__":
    AddyAndroidApp().run()
