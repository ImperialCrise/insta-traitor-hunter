"""Destructive / rate-limited actions: unfollow, follow."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from instagrapi import Client

from .analysis import Account
from .config import Config

log = logging.getLogger(__name__)


@dataclass
class ActionResult:
    processed: int
    succeeded: int
    failed: int
    skipped: int


def _sleep(lo: int, hi: int) -> None:
    if hi <= 0:
        return
    time.sleep(random.uniform(max(lo, 0), max(hi, lo)))


def unfollow_many(
    api: Client,
    targets: list[Account],
    cfg: Config,
    dry_run: bool = True,
    confirm_each: bool = False,
) -> ActionResult:
    """Unfollow a list of accounts with anti-ban rate limiting.

    - dry_run=True only logs what would happen.
    - confirm_each=True asks y/n before each action (good for safety).
    """
    limit = cfg.unfollow_max_per_run if cfg.unfollow_max_per_run > 0 else len(targets)
    queue = targets[:limit]

    res = ActionResult(processed=0, succeeded=0, failed=0, skipped=0)
    log.info(
        "About to unfollow %d account(s) (dry_run=%s, limit=%d).",
        len(queue),
        dry_run,
        limit,
    )

    for i, acc in enumerate(queue, 1):
        res.processed += 1
        tag = f"[{i}/{len(queue)}] @{acc.username} ({acc.follower_count} followers)"

        if acc.username.lower() in cfg.whitelist:
            log.info("%s -> skipped (whitelist)", tag)
            res.skipped += 1
            continue

        if confirm_each and not dry_run:
            ans = input(f"Unfollow {tag}? [y/N/q] ").strip().lower()
            if ans == "q":
                log.info("Aborted by user.")
                break
            if ans != "y":
                res.skipped += 1
                continue

        if dry_run:
            log.info("%s -> DRY-RUN unfollow", tag)
            res.succeeded += 1
            continue

        try:
            ok = api.user_unfollow(acc.pk)
            if ok:
                log.info("%s -> unfollowed", tag)
                res.succeeded += 1
            else:
                log.warning("%s -> API returned False", tag)
                res.failed += 1
        except Exception as exc:
            log.error("%s -> error: %s", tag, exc)
            res.failed += 1

        _sleep(cfg.unfollow_delay_min, cfg.unfollow_delay_max)

        if cfg.unfollow_pause_every and i % cfg.unfollow_pause_every == 0:
            log.info(
                "Long pause after %d actions (between %ds and %ds)...",
                i,
                cfg.unfollow_long_pause_min,
                cfg.unfollow_long_pause_max,
            )
            _sleep(cfg.unfollow_long_pause_min, cfg.unfollow_long_pause_max)

    return res


def follow_many(
    api: Client,
    targets: list[Account],
    cfg: Config,
    dry_run: bool = True,
) -> ActionResult:
    """Follow a list of accounts with the same rate limiting as unfollow."""
    limit = cfg.unfollow_max_per_run if cfg.unfollow_max_per_run > 0 else len(targets)
    queue = targets[:limit]
    res = ActionResult(processed=0, succeeded=0, failed=0, skipped=0)

    for i, acc in enumerate(queue, 1):
        res.processed += 1
        tag = f"[{i}/{len(queue)}] @{acc.username}"
        if dry_run:
            log.info("%s -> DRY-RUN follow", tag)
            res.succeeded += 1
            continue
        try:
            ok = api.user_follow(acc.pk)
            res.succeeded += int(bool(ok))
            res.failed += int(not ok)
            log.info("%s -> %s", tag, "followed" if ok else "failed")
        except Exception as exc:
            res.failed += 1
            log.error("%s -> error: %s", tag, exc)
        _sleep(cfg.unfollow_delay_min, cfg.unfollow_delay_max)

    return res
