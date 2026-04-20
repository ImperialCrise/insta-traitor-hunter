"""Thin wrapper around instagrapi with persistent session + 2FA support."""

from __future__ import annotations

import logging
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import (
    BadPassword,
    ChallengeRequired,
    ChallengeUnknownStep,
    LoginRequired,
    TwoFactorRequired,
)

from .config import Config

log = logging.getLogger(__name__)


# Fixed device/app metadata so IG always sees "the same phone".
# This is crucial: if the device fingerprint changes between runs,
# IG triggers a challenge.
_DEVICE_SETTINGS = {
    "app_version": "269.0.0.18.75",
    "android_version": 28,
    "android_release": "9.0",
    "dpi": "480dpi",
    "resolution": "1080x1920",
    "manufacturer": "Xiaomi",
    "device": "capricorn",
    "model": "MI 9",
    "cpu": "qcom",
    "version_code": "314665256",
}
_USER_AGENT = (
    "Instagram 269.0.0.18.75 Android "
    "(28/9.0; 480dpi; 1080x1920; Xiaomi; MI 9; capricorn; qcom; en_US; 314665256)"
)


def _challenge_code_handler(username: str, choice) -> str:
    """Called by instagrapi when IG sends a verification code via email/SMS."""
    print(
        f"\n[!] Instagram sent a verification code to @{username} "
        f"(channel: {choice}).",
        flush=True,
    )
    code = input("Enter the 6-digit code you received: ").strip()
    return code


def _change_password_handler(username: str) -> str:
    """Called when IG forces a password change."""
    import secrets
    import string

    chars = string.ascii_letters + string.digits + "!@#$%"
    new_pw = "".join(secrets.choice(chars) for _ in range(14))
    print(
        f"\n[!] Instagram is forcing @{username} to change password.\n"
        f"    Setting a new random password: {new_pw}\n"
        f"    SAVE IT NOW, and update your .env afterwards.",
        flush=True,
    )
    input("Press Enter to confirm... ")
    return new_pw


def _challenge_help() -> str:
    return (
        "\n"
        "==========================================================\n"
        " Instagram is asking for a manual security check.\n"
        " To fix this:\n"
        "   1. Open the Instagram app on your phone.\n"
        "   2. Approve any 'unusual login attempt' notification.\n"
        "   3. Log in to https://www.instagram.com from a browser\n"
        "      on THIS computer and solve any captcha/email check.\n"
        "   4. Delete data/session.json and re-run this command.\n"
        "   5. Wait a few minutes before retrying.\n"
        "==========================================================\n"
    )


class InstaClient:
    """Login helper that caches the session to avoid hammering Instagram."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.api = self._build_client()

    def _build_client(self) -> Client:
        api = Client()
        api.delay_range = [2, 5]
        api.set_device(_DEVICE_SETTINGS)
        api.set_user_agent(_USER_AGENT)
        api.set_country("FR")
        api.set_country_code(33)
        api.set_locale("fr_FR")
        api.set_timezone_offset(2 * 60 * 60)
        api.challenge_code_handler = _challenge_code_handler
        api.change_password_handler = _change_password_handler
        return api

    def _nuke_session(self) -> None:
        for p in (self.cfg.session_file, self.cfg.cache_dir / "snapshot.json"):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        self.api = self._build_client()

    def login(self) -> Client:
        session_path: Path = self.cfg.session_file

        if session_path.exists():
            try:
                self.api.load_settings(session_path)
                self.api.login(self.cfg.username, self.cfg.password)
                self.api.get_timeline_feed()
                log.info("Session reused for @%s", self.cfg.username)
                return self.api
            except (ChallengeRequired, ChallengeUnknownStep):
                log.error("Cached session is flagged by Instagram.")
                self._nuke_session()
                log.error(_challenge_help())
                raise
            except LoginRequired as exc:
                log.warning("Cached session expired (%s); logging in fresh.", exc)
                self._nuke_session()
            except Exception as exc:
                log.warning("Cached session unusable (%s); logging in fresh.", exc)
                self._nuke_session()

        try:
            self._fresh_login()
        except TwoFactorRequired:
            code = input("Instagram 2FA code: ").strip()
            self.api.login(
                self.cfg.username,
                self.cfg.password,
                verification_code=code,
            )
        except (ChallengeRequired, ChallengeUnknownStep):
            self._nuke_session()
            log.error(_challenge_help())
            raise
        except BadPassword:
            log.error("Bad password for @%s.", self.cfg.username)
            raise

        self.api.dump_settings(session_path)
        log.info("Logged in as @%s; session saved to %s", self.cfg.username, session_path)
        return self.api

    def _fresh_login(self) -> None:
        """Login, and tolerate failures in the post-login warmup flow.

        instagrapi's `login()` runs a sequence of "warmup" calls after the
        real login (reels_tray, launcher_sync, contact_point_prefill, ...).
        If any of those triggers a challenge, the whole login aborts - even
        though the auth cookie is already valid. We re-run just the login
        core without the warmup if that happens.
        """
        code = (
            self.api.totp_generate_code(self.cfg.totp_seed)
            if self.cfg.totp_seed
            else None
        )

        try:
            self.api.login(
                self.cfg.username,
                self.cfg.password,
                verification_code=code,
            )
            return
        except (ChallengeRequired, ChallengeUnknownStep):
            raise
        except Exception as exc:
            msg = str(exc).lower()
            if "expecting value" in msg or "jsondecodeerror" in msg:
                log.warning(
                    "Login warmup failed (%s). The auth cookie might still "
                    "be valid - trying to use it.",
                    exc,
                )
            else:
                raise

        if not self.api.authorization_data:
            raise RuntimeError(
                "Login failed and no auth data was captured. "
                + _challenge_help()
            )
        log.info("Using auth cookie despite warmup failure.")
