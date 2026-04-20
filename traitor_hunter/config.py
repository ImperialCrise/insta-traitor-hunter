"""Load runtime configuration from a .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    username: str
    password: str
    totp_seed: str | None

    traitor_follower_threshold: int
    traitor_include_private: bool
    traitor_include_verified: bool
    whitelist: set[str] = field(default_factory=set)

    unfollow_delay_min: int = 35
    unfollow_delay_max: int = 90
    unfollow_max_per_run: int = 40
    unfollow_pause_every: int = 15
    unfollow_long_pause_min: int = 300
    unfollow_long_pause_max: int = 600

    session_file: Path = Path("data/session.json")
    cache_dir: Path = Path("data")

    @classmethod
    def load(cls, env_path: str | os.PathLike[str] | None = None) -> "Config":
        if env_path is None:
            env_path = Path(__file__).resolve().parent.parent / ".env"
        load_dotenv(env_path, override=False)

        username = os.getenv("IG_USERNAME", "").strip()
        password = os.getenv("IG_PASSWORD", "")
        if not username or not password:
            raise RuntimeError(
                "IG_USERNAME and IG_PASSWORD must be set in your .env file."
            )

        cfg = cls(
            username=username,
            password=password,
            totp_seed=os.getenv("IG_TOTP_SEED", "").strip() or None,
            traitor_follower_threshold=_get_int("TRAITOR_FOLLOWER_THRESHOLD", 10000),
            traitor_include_private=_get_bool("TRAITOR_INCLUDE_PRIVATE", True),
            traitor_include_verified=_get_bool("TRAITOR_INCLUDE_VERIFIED", False),
            whitelist=set(_get_list("WHITELIST")),
            unfollow_delay_min=_get_int("UNFOLLOW_DELAY_MIN", 35),
            unfollow_delay_max=_get_int("UNFOLLOW_DELAY_MAX", 90),
            unfollow_max_per_run=_get_int("UNFOLLOW_MAX_PER_RUN", 40),
            unfollow_pause_every=_get_int("UNFOLLOW_PAUSE_EVERY", 15),
            unfollow_long_pause_min=_get_int("UNFOLLOW_LONG_PAUSE_MIN", 300),
            unfollow_long_pause_max=_get_int("UNFOLLOW_LONG_PAUSE_MAX", 600),
            session_file=Path(os.getenv("SESSION_FILE", "data/session.json")),
            cache_dir=Path(os.getenv("CACHE_DIR", "data")),
        )

        cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        cfg.session_file.parent.mkdir(parents=True, exist_ok=True)
        return cfg
