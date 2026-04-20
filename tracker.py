#!/usr/bin/env python3
"""
Weekly Discord task tracker.

Every Monday this script:
  1. Checks ✅ reactions on last week's check-in message → records who completed their tasks
  2. Posts a new check-in message for the current week
  3. Posts an updated monthly progress summary

Requires:
  - DISCORD_WEBHOOK_URL  — same webhook used by assign.py
  - DISCORD_BOT_TOKEN    — bot token with Read Message History + Add Reactions in the channel

Usage:
    python3 tracker.py
    DISCORD_WEBHOOK_URL=https://... DISCORD_BOT_TOKEN=... python3 tracker.py
"""

import json
import os
import urllib.parse
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

from discord_webhook import DiscordEmbed, DiscordWebhook

DATA_DIR   = Path(__file__).parent / "data"
STATE_FILE = DATA_DIR / "state.json"

CHECKMARK   = "✅"
DISCORD_API = "https://discord.com/api/v10"


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Discord REST helpers (bot token)
# ---------------------------------------------------------------------------

def _bot_request(method: str, path: str, bot_token: str) -> dict | None:
    req = urllib.request.Request(
        f"{DISCORD_API}{path}",
        headers={"Authorization": f"Bot {bot_token}", "User-Agent": "DiscordBot (https://github.com, 1.0)"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Discord API {method} {path} failed ({e.code}): {body}") from e


def get_reactors(channel_id: str, message_id: str, bot_token: str) -> list[str]:
    """Return list of user IDs who reacted ✅ on a message (bots excluded)."""
    emoji = urllib.parse.quote(CHECKMARK)
    users = _bot_request("GET", f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}", bot_token)
    return [u["id"] for u in (users or []) if not u.get("bot")]


def add_reaction(channel_id: str, message_id: str, bot_token: str) -> None:
    """Have the bot pre-add ✅ so brothers just click the existing reaction."""
    emoji = urllib.parse.quote(CHECKMARK)
    _bot_request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me", bot_token)


# ---------------------------------------------------------------------------
# Week helpers
# ---------------------------------------------------------------------------

def get_week_of_month(d: date | None = None) -> int:
    """Return week number within the month (1-4)."""
    if d is None:
        d = date.today()
    return min((d.day - 1) // 7 + 1, 4)


# ---------------------------------------------------------------------------
# Discord posting
# ---------------------------------------------------------------------------

def post_checkin(webhook_url: str, state: dict, week_num: int, bot_token: str) -> str:
    """Post the weekly check-in embed. Returns the new message ID."""
    month       = state["month"]
    year        = state["year"]
    assignments = state["assignments"]

    mentions = " ".join(
        f"<@{info['discord_id']}>" for info in assignments.values() if info.get("discord_id")
    )

    # ?wait=true so Discord returns the created message object
    webhook = DiscordWebhook(
        url=webhook_url + "?wait=true",
        content=f"{mentions}",
        allowed_mentions={"parse": ["users"]},
        rate_limit_retry=True,
    )

    embed = DiscordEmbed(
        title=f"📋 Week {week_num} Check-in — {month} {year}",
        description=f"React {CHECKMARK} once you've completed your tasks this week!",
        color="57F287",
    )
    for name, info in assignments.items():
        task_list = "\n".join(f"• {t}" for t in info["tasks"]) or "_No tasks this month_"
        embed.add_embed_field(name=name, value=task_list, inline=True)

    embed.set_footer(text=f"Week {week_num} of 4 • {month} {year}")
    webhook.add_embed(embed)

    response   = webhook.execute()
    msg        = response.json()
    message_id = msg["id"]
    channel_id = msg.get("channel_id", state.get("channel_id", ""))

    if channel_id and not state.get("channel_id"):
        state["channel_id"] = channel_id

    # Bot reacts first so brothers just click the existing ✅
    if bot_token and channel_id:
        try:
            add_reaction(channel_id, message_id, bot_token)
        except RuntimeError as e:
            print(f"  Warning: could not add reaction — {e}")

    return message_id


def post_progress(webhook_url: str, state: dict, current_week: int) -> None:
    """Post the full monthly completion progress embed."""
    month       = state["month"]
    year        = state["year"]
    assignments = state["assignments"]
    weeks_data  = state.get("weeks", {})

    webhook = DiscordWebhook(url=webhook_url, rate_limit_retry=True)
    embed   = DiscordEmbed(
        title=f"📊 {month} {year} — Monthly Progress",
        color="5865F2",
    )

    for name, info in assignments.items():
        discord_id = info.get("discord_id")
        boxes = ""
        done  = 0
        for w in range(1, 5):
            completed_ids = weeks_data.get(str(w), {}).get("completed", [])
            if w > current_week:
                boxes += "⬜"  # future weeks
            elif discord_id and discord_id in completed_ids:
                boxes += "✅"
                done += 1
            else:
                boxes += "❌"

        embed.add_embed_field(
            name=name,
            value=f"{boxes}  **{done}/{current_week}** weeks done",
            inline=False,
        )

    embed.set_footer(text=f"Updated after Week {current_week} • {month} {year}")
    webhook.add_embed(embed)
    webhook.execute()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def dry_run(state: dict, week_num: int) -> None:
    """Print what the tracker would post without hitting Discord."""
    month       = state["month"]
    year        = state["year"]
    assignments = state["assignments"]
    weeks_data  = state.get("weeks", {})

    print(f"=== DRY RUN: Week {week_num} of {month} {year} ===")
    print()

    print(f"[CHECK-IN EMBED] 📋 Week {week_num} Check-in — {month} {year}")
    print(f"  React {CHECKMARK} once you've completed your tasks this week!")
    for name, info in assignments.items():
        discord_id = info.get("discord_id")
        mention    = f"<@{discord_id}>" if discord_id else f"**{name}**"
        task_list  = "\n    ".join(f"• {t}" for t in info["tasks"]) or "No tasks this month"
        print(f"  {mention}:\n    {task_list}")
    print()

    print(f"[PROGRESS EMBED] 📊 {month} {year} — Monthly Progress")
    for name, info in assignments.items():
        discord_id    = info.get("discord_id")
        mention       = f"<@{discord_id}>" if discord_id else f"**{name}**"
        boxes = ""
        done  = 0
        for w in range(1, 5):
            completed_ids = weeks_data.get(str(w), {}).get("completed", [])
            if w > week_num:
                boxes += "⬜"
            elif discord_id and discord_id in completed_ids:
                boxes += "✅"
                done += 1
            else:
                boxes += "❌"
        print(f"  {mention}: {boxes}  {done}/{week_num} weeks done")


def main() -> None:
    if not STATE_FILE.exists():
        raise SystemExit("data/state.json not found — run assign.py first")

    state       = load_state()
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    bot_token   = os.environ.get("DISCORD_BOT_TOKEN", "").strip()

    today    = date.today()
    week_num = get_week_of_month(today)

    if not webhook_url:
        dry_run(state, week_num)
        return

    weeks    = state.setdefault("weeks", {})

    print(f"=== Tracker: Week {week_num} of {state['month']} {state['year']} ===")

    # Step 1 — Record completions from the previous week's check-in
    if week_num > 1:
        prev            = str(week_num - 1)
        prev_message_id = weeks.get(prev, {}).get("message_id")
        channel_id      = state.get("channel_id", "")

        if prev_message_id and channel_id and bot_token:
            print(f"Checking Week {week_num - 1} reactions...")
            completed = get_reactors(channel_id, prev_message_id, bot_token)
            weeks.setdefault(prev, {})["completed"] = completed
            names = [
                name for name, info in assignments.items()
                if info.get("discord_id") in completed
            ] if (assignments := state["assignments"]) else []
            print(f"  Completed: {names or '(none)'}")
        else:
            missing = []
            if not prev_message_id:
                missing.append("no message_id for last week")
            if not channel_id:
                missing.append("no channel_id in state")
            if not bot_token:
                missing.append("DISCORD_BOT_TOKEN not set")
            print(f"  Skipping reaction check — {', '.join(missing)}")

    # Step 2 — Post this week's check-in (only once per week)
    week_key = str(week_num)
    if not weeks.get(week_key, {}).get("message_id"):
        print(f"Posting Week {week_num} check-in...")
        message_id = post_checkin(webhook_url, state, week_num, bot_token)
        weeks.setdefault(week_key, {})["message_id"] = message_id
        weeks[week_key].setdefault("completed", [])
        print(f"  Message ID: {message_id}")
    else:
        print(f"Week {week_num} check-in already posted — skipping")

    # Step 3 — Post updated progress summary
    print("Posting progress summary...")
    post_progress(webhook_url, state, week_num)

    save_state(state)
    print("Done.")


if __name__ == "__main__":
    main()
