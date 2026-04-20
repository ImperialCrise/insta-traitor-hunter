"""insta-traitor-hunter CLI.

Usage examples:
    python main.py stats
    python main.py list-traitors
    python main.py list-fans
    python main.py list-mutuals
    python main.py unfollow-traitors --dry-run
    python main.py unfollow-traitors --confirm
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from traitor_hunter.actions import unfollow_many
from traitor_hunter.analysis import (
    Account,
    Snapshot,
    fetch_snapshot,
    find_traitors,
    hydrate_follower_counts,
)
from traitor_hunter.client import InstaClient
from traitor_hunter.config import Config

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    logging.getLogger("public_request").setLevel(logging.WARNING)
    logging.getLogger("private_request").setLevel(logging.WARNING)


def _print_accounts(accounts: list[Account], title: str) -> None:
    table = Table(title=f"{title} ({len(accounts)})")
    table.add_column("#", justify="right", style="dim")
    table.add_column("username", style="bold cyan")
    table.add_column("full name")
    table.add_column("followers", justify="right")
    table.add_column("flags")
    for i, acc in enumerate(accounts, 1):
        flags = []
        if acc.is_verified:
            flags.append("[blue]verified[/]")
        if acc.is_private:
            flags.append("[yellow]private[/]")
        table.add_row(
            str(i),
            acc.username,
            acc.full_name,
            str(acc.follower_count),
            " ".join(flags),
        )
    console.print(table)


def _print_usernames(names: set[str], title: str) -> None:
    table = Table(title=f"{title} ({len(names)})")
    table.add_column("#", justify="right", style="dim")
    table.add_column("username", style="bold cyan")
    for i, name in enumerate(sorted(names), 1):
        table.add_row(str(i), name)
    console.print(table)


def _load_snapshot(cfg: Config, refresh: bool) -> tuple[Snapshot, object]:
    client = InstaClient(cfg).login()
    snap = fetch_snapshot(client, cfg, use_cache=not refresh)
    return snap, client


def cmd_stats(args: argparse.Namespace, cfg: Config) -> None:
    snap, _ = _load_snapshot(cfg, args.refresh)
    table = Table(title=f"@{cfg.username} - stats")
    table.add_column("metric", style="bold")
    table.add_column("value", justify="right")
    table.add_row("followers", str(len(snap.followers)))
    table.add_row("following", str(len(snap.following)))
    table.add_row("mutuals", str(len(snap.mutuals)))
    table.add_row("fans (they follow, you don't)", str(len(snap.fans)))
    table.add_row("non-followers (you follow, they don't)", str(len(snap.non_followers)))
    console.print(table)


def cmd_list_fans(args: argparse.Namespace, cfg: Config) -> None:
    snap, _ = _load_snapshot(cfg, args.refresh)
    _print_usernames(snap.fans, "Fans (they follow you, you don't follow back)")


def cmd_list_mutuals(args: argparse.Namespace, cfg: Config) -> None:
    snap, _ = _load_snapshot(cfg, args.refresh)
    _print_usernames(snap.mutuals, "Mutuals")


def cmd_list_non_followers(args: argparse.Namespace, cfg: Config) -> None:
    snap, _ = _load_snapshot(cfg, args.refresh)
    _print_usernames(snap.non_followers, "Non-followers (you follow, they don't)")


def cmd_list_traitors(args: argparse.Namespace, cfg: Config) -> list[Account]:
    snap, api = _load_snapshot(cfg, args.refresh)
    non_followers = snap.non_followers - cfg.whitelist
    targets = [snap.following[u] for u in non_followers if u in snap.following]

    cache_path = Path(cfg.cache_dir) / "user_info_cache.json"
    hydrated = hydrate_follower_counts(api, targets, cache_path)
    traitors = find_traitors(snap, hydrated, cfg)

    _print_accounts(
        traitors,
        f"Traitors (<{cfg.traitor_follower_threshold} followers, no follow-back)",
    )
    return traitors


def cmd_unfollow_traitors(args: argparse.Namespace, cfg: Config) -> None:
    traitors = cmd_list_traitors(args, cfg)
    if not traitors:
        console.print("[green]Nothing to unfollow. You're clean.[/]")
        return

    if args.yes or args.dry_run:
        proceed = True
    else:
        ans = console.input(
            f"\n[bold red]About to unfollow {len(traitors)} account(s). Continue? [y/N][/] "
        ).strip().lower()
        proceed = ans == "y"

    if not proceed:
        console.print("[yellow]Aborted.[/]")
        return

    snap, api = _load_snapshot(cfg, refresh=False)
    res = unfollow_many(
        api,
        traitors,
        cfg,
        dry_run=args.dry_run,
        confirm_each=args.confirm,
    )
    console.print(
        f"\n[bold]Done.[/] processed={res.processed} "
        f"ok={res.succeeded} failed={res.failed} skipped={res.skipped}"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="insta-traitor-hunter",
        description="Audit & clean your Instagram followings.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the on-disk snapshot and re-fetch followers/following from IG.",
    )

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Show follower/following counts & overlaps.")
    sub.add_parser("list-fans", help="List accounts following you that you don't follow back.")
    sub.add_parser("list-mutuals", help="List mutual follows.")
    sub.add_parser(
        "list-non-followers",
        help="List accounts you follow that don't follow you back.",
    )
    sub.add_parser(
        "list-traitors",
        help="List non-followers below the follower threshold (the unfollow candidates).",
    )

    unfollow = sub.add_parser(
        "unfollow-traitors",
        help="Unfollow all detected traitors (with rate limiting).",
    )
    unfollow.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would happen; do not touch IG.",
    )
    unfollow.add_argument(
        "--confirm",
        action="store_true",
        help="Ask y/n before each single unfollow.",
    )
    unfollow.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the global confirmation prompt.",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        cfg = Config.load()
    except RuntimeError as exc:
        console.print(f"[red]Config error:[/] {exc}")
        return 2

    dispatch = {
        "stats": cmd_stats,
        "list-fans": cmd_list_fans,
        "list-mutuals": cmd_list_mutuals,
        "list-non-followers": cmd_list_non_followers,
        "list-traitors": cmd_list_traitors,
        "unfollow-traitors": cmd_unfollow_traitors,
    }

    try:
        dispatch[args.command](args, cfg)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
