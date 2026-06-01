# Contributing to Addy

First off, **thank you** for considering contributing! Every contribution — from fixing typos to adding features — is welcome and appreciated.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Pull Request Process](#pull-request-process)
- [Style Guide](#style-guide)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)

## Getting Started

1. **Fork** the repository
2. **Clone** your fork:
   ```bash
   git clone https://github.com/<your-username>/addy.git
   cd addy
   ```
3. **Create a branch** for your work:
   ```bash
   git checkout -b feat/my-awesome-feature
   ```

## Development Setup

Addy requires **Python 3.10+** and uses only a few dependencies.

```bash
# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
.venv\Scripts\activate      # Windows

# Install dependencies
pip install -r requirements.txt
```

To run the app locally:

```bash
python addy.py
```

> **Linux note:** If you get a tkinter import error, install it with your package manager:
> `sudo apt install python3-tk` (Debian/Ubuntu) or `sudo dnf install python3-tkinter` (Fedora).

## How to Contribute

### 🐛 Fix a Bug

1. Check the [Issues](../../issues) page to see if it's already reported
2. If not, [open a new issue](../../issues/new?template=bug_report.yml) first so we can discuss
3. Fork, fix, and open a PR referencing the issue

### ✨ Add a Feature

1. Check [existing feature requests](../../issues?q=is%3Aissue+label%3Aenhancement)
2. If your idea is new, [open a feature request](../../issues/new?template=feature_request.yml) first
3. Wait for a maintainer to approve the direction before writing code
4. Fork, implement, and open a PR

### 📖 Improve Documentation

Docs improvements (README, code comments, docstrings) are always welcome — no issue needed, just open a PR.

## Pull Request Process

1. **Keep PRs small and focused** — one logical change per PR
2. **Update documentation** if your change affects usage or behaviour
3. **Test on your platform** — at minimum, verify the app launches and shows IP addresses correctly
4. **Fill out the PR template** — it helps reviewers understand your changes
5. **Be patient** — maintainers review PRs as time allows

### Branch Naming

| Type      | Prefix           | Example                     |
|-----------|------------------|-----------------------------|
| Feature   | `feat/`          | `feat/dark-mode-toggle`     |
| Bug fix   | `fix/`           | `fix/ipv6-copy-crash`       |
| Docs      | `docs/`          | `docs/linux-install-guide`  |
| Refactor  | `refactor/`      | `refactor/enrichment-cache` |

## Style Guide

- **Python**: Follow [PEP 8](https://peps.python.org/pep-0008/). Use type hints where practical.
- **Commits**: Use clear, imperative-mood messages (e.g., `fix: handle missing adapter description on Linux`)
- **Comments**: Explain *why*, not *what*. The code should be self-explanatory for the *what*.

## Reporting Bugs

Use the **Bug Report** issue template. Include:

- Your OS and version (e.g., Windows 11 23H2, Ubuntu 24.04, macOS 15)
- Python version (`python --version`)
- Steps to reproduce the bug
- Expected vs. actual behaviour
- Screenshots if applicable

## Requesting Features

Use the **Feature Request** issue template. Describe:

- The problem you're trying to solve
- Your proposed solution
- Any alternatives you've considered

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
