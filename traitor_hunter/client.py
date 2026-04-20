"""Thin wrapper around instagrapi with persistent session + 2FA support."""

from __future__ import annotations

import logging
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import (
    BadPassword,
    ChallengeRequired,
    LoginRequired,
    TwoFactorRequired,
)

from .config import Config

log = logging.getLogger(__name__)


class InstaClient:
    """Login helper that caches the session to avoid hammering Instagram."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.api = Client()
        self.api.delay_range = [1, 3]

    def login(self) -> Client:
        session_path: Path = self.cfg.session_file
        cached = session_path.exists()

        if cached:
            try:
                self.api.load_settings(session_path)
                self.api.login(self.cfg.username, self.cfg.password)
                self.api.get_timeline_feed()
                log.info("Session reused for @%s", self.cfg.username)
                return self.api
            except (LoginRequired, Exception) as exc:
                log.warning("Cached session invalid (%s); logging in fresh.", exc)
                try:
                    session_path.unlink()
                except FileNotFoundError:
                    pass
                self.api = Client()
                self.api.delay_range = [1, 3]

        try:
            self._fresh_login()
        except TwoFactorRequired:
            code = input("Instagram 2FA code: ").strip()
            self.api.login(
                self.cfg.username,
                self.cfg.password,
                verification_code=code,
            )
        except ChallengeRequired:
            log.error(
                "Instagram issued a challenge. Open the app, approve the login "
                "attempt, then re-run this command."
            )
            raise
        except BadPassword:
            log.error("Bad password for @%s.", self.cfg.username)
            raise

        self.api.dump_settings(session_path)
        log.info("Logged in as @%s; session saved to %s", self.cfg.username, session_path)
        return self.api

    def _fresh_login(self) -> None:
        if self.cfg.totp_seed:
            code = self.api.totp_generate_code(self.cfg.totp_seed)
            self.api.login(
                self.cfg.username,
                self.cfg.password,
                verification_code=code,
            )
        else:
            self.api.login(self.cfg.username, self.cfg.password)
