"""Build the follower / following graph and classify accounts."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from instagrapi import Client
from instagrapi.types import UserShort

from .config import Config

log = logging.getLogger(__name__)


@dataclass
class Account:
    pk: int
    username: str
    full_name: str = ""
    is_private: bool = False
    is_verified: bool = False
    follower_count: int = 0
    following_count: int = 0
    media_count: int = 0

    @property
    def url(self) -> str:
        return f"https://instagram.com/{self.username}"


@dataclass
class Snapshot:
    """Relationship snapshot for the authenticated user."""

    followers: dict[str, Account]
    following: dict[str, Account]

    @property
    def follower_usernames(self) -> set[str]:
        return set(self.followers)

    @property
    def following_usernames(self) -> set[str]:
        return set(self.following)

    @property
    def mutuals(self) -> set[str]:
        return self.follower_usernames & self.following_usernames

    @property
    def fans(self) -> set[str]:
        """They follow you, you don't follow them."""
        return self.follower_usernames - self.following_usernames

    @property
    def non_followers(self) -> set[str]:
        """You follow them, they don't follow you back."""
        return self.following_usernames - self.follower_usernames


def _short_to_account(u: UserShort) -> Account:
    return Account(
        pk=int(u.pk),
        username=u.username,
        full_name=getattr(u, "full_name", "") or "",
        is_private=bool(getattr(u, "is_private", False)),
        is_verified=bool(getattr(u, "is_verified", False)),
    )


def fetch_snapshot(api: Client, cfg: Config, use_cache: bool = True) -> Snapshot:
    """Fetch the full followers + following lists of the logged-in user."""
    cache = cfg.cache_dir / "snapshot.json"
    if use_cache and cache.exists():
        log.info("Loading snapshot from cache: %s", cache)
        raw = json.loads(cache.read_text(encoding="utf-8"))
        return Snapshot(
            followers={k: Account(**v) for k, v in raw["followers"].items()},
            following={k: Account(**v) for k, v in raw["following"].items()},
        )

    me = api.user_id_from_username(cfg.username)

    log.info("Fetching followers (this can take a while)...")
    followers_raw = api.user_followers(me, amount=0)
    log.info("Fetched %d followers.", len(followers_raw))

    log.info("Fetching followings...")
    following_raw = api.user_following(me, amount=0)
    log.info("Fetched %d followings.", len(following_raw))

    followers = {u.username.lower(): _short_to_account(u) for u in followers_raw.values()}
    following = {u.username.lower(): _short_to_account(u) for u in following_raw.values()}

    snap = Snapshot(followers=followers, following=following)
    cache.write_text(
        json.dumps(
            {
                "followers": {k: asdict(v) for k, v in followers.items()},
                "following": {k: asdict(v) for k, v in following.items()},
                "fetched_at": int(time.time()),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    log.info("Snapshot cached to %s", cache)
    return snap


def hydrate_follower_counts(
    api: Client,
    accounts: list[Account],
    cache_path: Path,
) -> list[Account]:
    """Fill in follower_count / is_verified / is_private via user_info.

    Results are cached on disk because this is the slow/rate-limited part.
    """
    cache: dict[str, dict] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}

    hydrated: list[Account] = []
    dirty = False
    for i, acc in enumerate(accounts, 1):
        key = str(acc.pk)
        if key in cache:
            data = cache[key]
            hydrated.append(Account(**data))
            continue

        try:
            info = api.user_info(acc.pk)
        except Exception as exc:
            log.warning("user_info(%s) failed: %s", acc.username, exc)
            hydrated.append(acc)
            continue

        full = Account(
            pk=int(info.pk),
            username=info.username,
            full_name=info.full_name or "",
            is_private=bool(info.is_private),
            is_verified=bool(info.is_verified),
            follower_count=int(info.follower_count or 0),
            following_count=int(info.following_count or 0),
            media_count=int(info.media_count or 0),
        )
        hydrated.append(full)
        cache[key] = asdict(full)
        dirty = True

        if i % 25 == 0:
            log.info("Hydrated %d/%d accounts", i, len(accounts))
            cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
            time.sleep(2)

    if dirty:
        cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    return hydrated


def find_traitors(
    snap: Snapshot,
    hydrated: list[Account],
    cfg: Config,
) -> list[Account]:
    """Rank non-followers below the threshold as traitors."""
    non_followers = snap.non_followers
    by_username = {a.username.lower(): a for a in hydrated}

    traitors: list[Account] = []
    for uname in non_followers:
        if uname in cfg.whitelist:
            continue
        acc = by_username.get(uname)
        if acc is None:
            continue
        if acc.is_verified and not cfg.traitor_include_verified:
            continue
        if acc.is_private and not cfg.traitor_include_private:
            continue
        if acc.follower_count >= cfg.traitor_follower_threshold:
            continue
        traitors.append(acc)

    traitors.sort(key=lambda a: a.follower_count)
    return traitors
