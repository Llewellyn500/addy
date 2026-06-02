#!/usr/bin/env python3
"""Android companion app for Addy.

The desktop app is a Tk system-tray utility. Android has no equivalent tray,
so this entrypoint presents the same network-address copy workflow as a
foreground mobile app.
"""

from __future__ import annotations

import socket
import webbrowser
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
from kivy.utils import escape_markup

__version__ = "1.0.0"


BG = "#0c0a14"
CARD_BG = "#8252e9"
TEXT = "#ffffff"
TEXT_DIM = "#e2daff"
ACCENT = "#ffd23f"
BORDER = "#000000"
BUTTON_BG = "#ffffff"
COPY_OK = "#16a34a"
INK = "#0c0a14"
ASSET_DIR = Path(__file__).resolve().parent / "assets"
GITHUB_URL = "https://github.com/Llewellyn500/addy"

HEADER_LOGO_SIZE = 28
HEADER_HEIGHT = 40
HEADER_TITLE_SIZE = 20
HEADER_SPACING = 8
ACTION_HEIGHT = 40
REFRESH_WIDTH = 124
GITHUB_WIDTH = 100
COMPACT_REFRESH_WIDTH = 108
COMPACT_GITHUB_WIDTH = 84

CARD_RADIUS = 20
CARD_BORDER = 2
CARD_SHADOW = 5
CARD_PADDING = [16, 14, 21, 19]
CARD_SPACING = 4

TITLE_SIZE = 13
DESCRIPTION_SIZE = 11
ADDRESS_LABEL_SIZE = 10
ADDRESS_SIZE = 11
ROW_HEIGHT = 38
COPY_WIDTH = 84
COPY_HEIGHT = 34


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
    border_color = ListProperty(_rgba(BORDER))
    shadow_color = ListProperty(_rgba(BORDER))

    def __init__(
        self,
        bg_color=None,
        radius=20,
        border_width=2,
        shadow_offset=5,
        **kwargs,
    ):
        super().__init__(**kwargs)
        if bg_color is not None:
            self.bg_color = bg_color
        self._radius = radius
        self._border_width = border_width
        self._shadow_offset = shadow_offset

        with self.canvas.before:
            self._shadow_color_instruction = Color(*self.shadow_color)
            self._shadow_rect = RoundedRectangle(pos=self.pos, size=self.size)
            self._border_color_instruction = Color(*self.border_color)
            self._border_rect = RoundedRectangle(pos=self.pos, size=self.size)
            self._fill_color_instruction = Color(*self.bg_color)
            self._fill_rect = RoundedRectangle(pos=self.pos, size=self.size)

        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.bind(bg_color=self._sync_canvas)
        self.bind(border_color=self._sync_canvas, shadow_color=self._sync_canvas)

    def _sync_canvas(self, *_):
        x, y = self.pos
        width, height = self.size
        border = dp(self._border_width)
        shadow = dp(self._shadow_offset)
        body_width = max(0, width - shadow)
        body_height = max(0, height - shadow)
        radius = dp(self._radius)
        fill_radius = max(0, radius - border)

        self._shadow_color_instruction.rgba = self.shadow_color
        self._shadow_rect.pos = (x + shadow, y)
        self._shadow_rect.size = (body_width, body_height)
        self._shadow_rect.radius = [0, radius, 0, radius]

        self._border_color_instruction.rgba = self.border_color
        self._border_rect.pos = (x, y + shadow)
        self._border_rect.size = (body_width, body_height)
        self._border_rect.radius = [0, radius, 0, radius]

        self._fill_color_instruction.rgba = self.bg_color
        self._fill_rect.pos = (x + border, y + shadow + border)
        self._fill_rect.size = (
            max(0, body_width - border * 2),
            max(0, body_height - border * 2),
        )
        self._fill_rect.radius = [0, fill_radius, 0, fill_radius]


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


def _markup_label(text: str, *, size=14, height=28, shorten=False):
    label = _label(text, size=size, bold=False, height=height, shorten=shorten)
    label.markup = True
    return label


class NeoButton(Button):
    fill_color = ListProperty(_rgba(BUTTON_BG))
    border_color = ListProperty(_rgba(BORDER))
    shadow_color = ListProperty(_rgba(BORDER))

    def __init__(
        self,
        *,
        text: str,
        width=96,
        height=44,
        color=INK,
        bg=BUTTON_BG,
        active_bg=ACCENT,
        radius=8,
        border_width=2,
        shadow_offset=3,
        **kwargs,
    ):
        super().__init__(
            text=text,
            color=_rgba(color),
            background_normal="",
            background_down="",
            background_color=[0, 0, 0, 0],
            font_size=sp(13),
            bold=True,
            size_hint=(None, None),
            size=(dp(width), dp(height)),
            **kwargs,
        )
        self._radius = radius
        self._border_width = border_width
        self._shadow_offset = shadow_offset
        self._default_fill = _rgba(bg)
        self._default_text = _rgba(color)
        self._active_fill = _rgba(active_bg)
        self.fill_color = self._default_fill

        with self.canvas.before:
            self._shadow_color_instruction = Color(*self.shadow_color)
            self._shadow_rect = RoundedRectangle(pos=self.pos, size=self.size)
            self._border_color_instruction = Color(*self.border_color)
            self._border_rect = RoundedRectangle(pos=self.pos, size=self.size)
            self._fill_color_instruction = Color(*self.fill_color)
            self._fill_rect = RoundedRectangle(pos=self.pos, size=self.size)

        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.bind(fill_color=self._sync_canvas)
        self.bind(border_color=self._sync_canvas, shadow_color=self._sync_canvas)
        self.bind(state=self._sync_state)
        self._sync_canvas()

    def set_visual(self, *, text: str | None = None, bg: str | None = None, color: str | None = None):
        if text is not None:
            self.text = text
        if bg is not None:
            self._default_fill = _rgba(bg)
        if color is not None:
            self._default_text = _rgba(color)

        self.color = self._default_text
        if self.state != "down":
            self.fill_color = self._default_fill

    def _sync_state(self, *_):
        self.fill_color = self._active_fill if self.state == "down" else self._default_fill

    def _sync_canvas(self, *_):
        x, y = self.pos
        width, height = self.size
        border = dp(self._border_width)
        shadow = dp(self._shadow_offset)
        body_width = max(0, width - shadow)
        body_height = max(0, height - shadow)
        radius = dp(self._radius)
        fill_radius = max(0, radius - border)

        self._shadow_color_instruction.rgba = self.shadow_color
        self._shadow_rect.pos = (x + shadow, y)
        self._shadow_rect.size = (body_width, body_height)
        self._shadow_rect.radius = [0, radius, 0, radius]

        self._border_color_instruction.rgba = self.border_color
        self._border_rect.pos = (x, y + shadow)
        self._border_rect.size = (body_width, body_height)
        self._border_rect.radius = [0, radius, 0, radius]

        self._fill_color_instruction.rgba = self.fill_color
        self._fill_rect.pos = (x + border, y + shadow + border)
        self._fill_rect.size = (
            max(0, body_width - border * 2),
            max(0, body_height - border * 2),
        )
        self._fill_rect.radius = [0, fill_radius, 0, fill_radius]


def _button(text: str, *, width=96, height=44, color=INK, bg=BUTTON_BG):
    return NeoButton(
        text=text,
        width=width,
        height=height,
        color=color,
        bg=bg,
    )


def _open_github():
    try:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")

        intent = Intent(Intent.ACTION_VIEW, Uri.parse(GITHUB_URL))
        PythonActivity.mActivity.startActivity(intent)
    except Exception:
        webbrowser.open(GITHUB_URL)


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
                network=_interface_network_label(name, network_label),
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


def _interface_network_label(interface_name: str, active_label: str | None) -> str | None:
    name = interface_name.lower()

    if name.startswith(("wlan", "wifi")):
        if active_label and active_label not in {"Cellular", "Ethernet", "VPN"}:
            return active_label
        return "Wi-Fi"

    if name.startswith(("rmnet", "ccmni", "pdp", "wwan", "cell")):
        return "Cellular"

    if name.startswith(("eth", "usb")):
        return "Ethernet"

    if name.startswith(("tun", "tap", "ppp")):
        return "VPN"

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
            radius=CARD_RADIUS,
            border_width=CARD_BORDER,
            shadow_offset=CARD_SHADOW,
            padding=[dp(value) for value in CARD_PADDING],
            spacing=dp(CARD_SPACING),
            size_hint_y=None,
            height=dp(1),
            **kwargs,
        )
        self.info = info
        self.bind(minimum_height=self.setter("height"))

        heading = BoxLayout(orientation="horizontal", spacing=dp(6), size_hint_y=None, height=dp(24))
        title_text = f"[b]{escape_markup(info.name)}[/b]"
        if info.network:
            title_text += f"  ·  [color=ffd23f][b]{escape_markup(info.network)}[/b][/color]"
        heading.add_widget(_markup_label(title_text, size=TITLE_SIZE, height=24, shorten=True))
        self.add_widget(heading)

        if info.description:
            self.add_widget(_label(info.description, color=TEXT_DIM, size=DESCRIPTION_SIZE, height=22, shorten=True))

        if info.ipv4:
            self.add_widget(self._address_row("IPv4", info.ipv4))
        if info.ipv6:
            self.add_widget(self._address_row("IPv6", info.ipv6))

    def _address_row(self, kind: str, address: str):
        row = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(ROW_HEIGHT))
        row.add_widget(
            _label(kind, size=ADDRESS_LABEL_SIZE, bold=True, height=ROW_HEIGHT, size_hint_x=None, width=50)
        )
        row.add_widget(_label(address, size=ADDRESS_SIZE, height=ROW_HEIGHT, shorten=True))

        copy_btn = _button("Copy", width=COPY_WIDTH, height=COPY_HEIGHT)
        copy_btn.bind(on_release=lambda btn: self._copy_address(btn, address))
        row.add_widget(copy_btn)
        return row

    def _copy_address(self, btn: Button, address: str):
        Clipboard.copy(address)
        if isinstance(btn, NeoButton):
            btn.set_visual(text="Copied", bg=COPY_OK, color=TEXT)
        else:
            btn.text = "Copied"
            btn.background_color = _rgba(COPY_OK)
            btn.color = _rgba(TEXT)

        def reset(_):
            if isinstance(btn, NeoButton):
                btn.set_visual(text="Copy", bg=BUTTON_BG, color=INK)
            else:
                btn.text = "Copy"
                btn.background_color = _rgba(BUTTON_BG)
                btn.color = _rgba(INK)

        Clock.schedule_once(reset, 1.2)


class AddyAndroidApp(App):
    title = "Addy"
    icon = str(ASSET_DIR / "icon.png")

    def build(self):
        Window.clearcolor = _rgba(BG)

        root = BoxLayout(
            orientation="vertical",
            padding=[dp(20), dp(18), dp(20), dp(18)],
            spacing=dp(10),
        )

        compact = Window.width <= dp(380)
        github_width = COMPACT_GITHUB_WIDTH if compact else GITHUB_WIDTH
        refresh_width = COMPACT_REFRESH_WIDTH if compact else REFRESH_WIDTH

        header = BoxLayout(
            orientation="horizontal",
            spacing=dp(HEADER_SPACING),
            size_hint_y=None,
            height=dp(HEADER_HEIGHT),
        )
        logo = Image(
            source=str(ASSET_DIR / "logo.png"),
            size_hint=(None, None),
            size=(dp(HEADER_LOGO_SIZE), dp(HEADER_LOGO_SIZE)),
            pos_hint={"center_y": 0.5},
        )
        header.add_widget(logo)
        header.add_widget(_label("ADDY", size=HEADER_TITLE_SIZE, bold=True, height=HEADER_HEIGHT, shorten=True))

        self.github_btn = _button("GitHub", width=github_width, height=ACTION_HEIGHT)
        self.github_btn.bind(on_release=lambda *_: _open_github())
        header.add_widget(self.github_btn)

        self.refresh_btn = _button("Refresh", width=refresh_width, height=ACTION_HEIGHT)
        self.refresh_btn.bind(on_release=lambda *_: self.refresh_interfaces())
        header.add_widget(self.refresh_btn)
        root.add_widget(header)

        root.add_widget(_label("Active network interfaces", size=10, bold=True, height=24))

        scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(5),
            bar_color=_rgba(CARD_BG),
            bar_inactive_color=_rgba(CARD_BG, 0.45),
        )
        self.cards = BoxLayout(orientation="vertical", spacing=dp(12), size_hint_y=None)
        self.cards.bind(minimum_height=self.cards.setter("height"))
        scroll.add_widget(self.cards)
        root.add_widget(scroll)

        Clock.schedule_once(lambda _: self.refresh_interfaces(), 0.1)
        return root

    def refresh_interfaces(self):
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.set_visual(text="Scanning", bg=ACCENT, color=INK)
        self._show_loading()
        Clock.schedule_once(lambda _: self._render_interfaces(get_interfaces()), 0)

    def _show_loading(self):
        if not hasattr(self, "cards"):
            return
        self.cards.clear_widgets()
        self.cards.add_widget(_label("Scanning networks...", size=11, bold=True, height=56, halign="center"))

    def _render_interfaces(self, interfaces: list[InterfaceInfo]):
        self.cards.clear_widgets()
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.set_visual(text="Refresh", bg=BUTTON_BG, color=INK)

        if not interfaces:
            empty = Surface(
                orientation="vertical",
                bg_color=_rgba(CARD_BG),
                radius=CARD_RADIUS,
                border_width=CARD_BORDER,
                shadow_offset=CARD_SHADOW,
                padding=[dp(value) for value in CARD_PADDING],
                size_hint_y=None,
                height=dp(86),
            )
            empty.add_widget(_label("No active network interfaces found.", size=15, bold=True, height=42))
            self.cards.add_widget(empty)
            return

        for info in interfaces:
            self.cards.add_widget(InterfaceCard(info))


if __name__ == "__main__":
    AddyAndroidApp().run()
