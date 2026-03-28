#!/usr/bin/env python3
"""
Assign house tasks to brothers for the current month and post to Discord.

- Tasks are distributed round-robin across brothers.
- The starting brother rotates each month so no one always gets the same tasks.
- Works regardless of how many brothers or tasks there are.

Usage:
    python3 assign.py
    DISCORD_WEBHOOK_URL=https://... python3 assign.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

from discord_webhook import DiscordEmbed, DiscordWebhook

DATA_DIR = Path(__file__).parent / "data"
BROTHERS_FILE = DATA_DIR / "brothers.json"
TASKS_FILE    = DATA_DIR / "tasks.json"


def load_json(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def assign_tasks(brothers: list, tasks: list, month_offset: int) -> dict[str, list]:
    """
    Distribute tasks across brothers using a monthly rotation.

    Returns {brother_name: [task, ...]} for every brother.
    Brothers with no task this month will have an empty list.
    """
    n = len(brothers)
    # Rotate the starting index each month so assignments cycle
    start = month_offset % n
    rotated = brothers[start:] + brothers[:start]

    assignments = {b["name"]: [] for b in brothers}
    for i, task in enumerate(tasks):
        recipient = rotated[i % n]
        assignments[recipient["name"]].append(task)

    return assignments


def post_to_discord(webhook_url: str, assignments: dict, brothers: list, month: str, year: int) -> int:
    id_map = {b["name"]: b.get("discord_id") for b in brothers}

    webhook = DiscordWebhook(
        url=webhook_url,
        content=f"@here — {month} {year} house task assignments are in!",
    )

    embed = DiscordEmbed(
        title=f"🏠 {month} {year} House Tasks",
        color="5865F2",
    )
    embed.set_footer(text="Auto-assigned monthly • rotates every month")

    for name, tasks in assignments.items():
        discord_id = id_map.get(name)
        mention = f"<@{discord_id}>" if discord_id else f"**{name}**"

        if tasks:
            value = "\n".join(
                f"• **{t['name']}**" + (f"\n  {t['description']}" if t.get("description") else "")
                for t in tasks
            )
        else:
            value = "_No tasks this month — enjoy the break!_"

        embed.add_embed_field(name=mention, value=value, inline=False)

    webhook.add_embed(embed)
    response = webhook.execute()
    return response.status_code


def main() -> None:
    brothers = load_json(BROTHERS_FILE)
    tasks    = load_json(TASKS_FILE)

    if not brothers:
        raise SystemExit("brothers.json is empty — add at least one brother")
    if not tasks:
        raise SystemExit("tasks.json is empty — add at least one task")

    now = datetime.now()
    # Unique integer per month — drives the rotation
    month_offset = now.year * 12 + now.month

    assignments = assign_tasks(brothers, tasks, month_offset)

    month_name = now.strftime("%B")

    # Pretty-print the assignment to stdout (visible in Actions logs)
    print(f"=== {month_name} {now.year} Task Assignments ===")
    for name, tasks_assigned in assignments.items():
        task_names = ", ".join(t["name"] for t in tasks_assigned) if tasks_assigned else "(none)"
        print(f"  {name}: {task_names}")
    print()

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if webhook_url:
        status = post_to_discord(webhook_url, assignments, brothers, month_name, now.year)
        print(f"Posted to Discord — HTTP {status}")
    else:
        print("DISCORD_WEBHOOK_URL not set — skipping Discord post (dry run)")


if __name__ == "__main__":
    main()
