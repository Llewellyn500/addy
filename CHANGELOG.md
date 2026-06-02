# Changelog

All notable changes to Addy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Android ARM64 companion app with a Buildozer configuration for APK releases
- Native ARM64 release targets for Linux and Windows on Arm
- Packaged PNG icon assets in desktop binaries for faster startup icon rendering
- Detailed generated release notes with changelog highlights, grouped commits, compare links, and release asset sizes

### Changed

- Android UI now matches the desktop Addy visual system with leaf-shaped cards, hard black shadows, compact header rhythm, and matching copy feedback
- Linux and macOS desktop builds now use the same Addy header sizing, GitHub action, font fallback order, and icon packaging as the Windows build
- Android header alignment now mirrors the desktop header and includes the GitHub action next to Refresh
- Android connected-network labels are now assigned per interface instead of reusing one global network label for every row

## [1.0.0] — 2026-06-01

### Added

- System tray integration — close the window and Addy stays in the tray using near-zero resources
- Shows all active network interfaces with hardware adapter name, WiFi SSID / network profile, IPv4, and IPv6
- One-click copy to clipboard with visual confirmation
- Refresh on demand or automatically when reopened from the tray
- Dark, minimal UI with Catppuccin-Mocha inspired palette
- Cross-platform support: Windows, macOS, and Linux
- Standalone executables published automatically via GitHub Actions for every merge to `main`
