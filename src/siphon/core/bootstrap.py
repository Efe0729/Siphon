"""Early frozen-runtime guards shared by both Windows entry points."""

from __future__ import annotations

import os
import ssl


def install_ssl_guard() -> None:
    """Install the ASCII-safe certifi path before curl_cffi is imported."""
    try:
        import certifi

        ca_path = certifi.where()
        if not ca_path or not os.path.exists(ca_path):
            return
        os.environ.setdefault("SSL_CERT_FILE", ca_path)
        os.environ.setdefault("SSL_CERT_DIR", os.path.dirname(ca_path))
        try:
            ssl.get_default_verify_paths()
        except (UnicodeDecodeError, SystemError):
            defaults = ssl.DefaultVerifyPaths(
                ca_path,
                os.path.dirname(ca_path),
                "SSL_CERT_FILE",
                ca_path,
                "SSL_CERT_DIR",
                os.path.dirname(ca_path),
            )
            ssl.get_default_verify_paths = lambda: defaults
    except Exception:
        pass


def install_crash_logger() -> None:
    try:
        from siphon.core import crashlog

        crashlog.install()
    except Exception:
        pass


def install_runtime_guards() -> None:
    install_ssl_guard()
    install_crash_logger()


def run_translation_diagnostic_if_requested() -> None:
    """Kept as a no-op: the subtitle engine this used to drive is gone."""
    return None
