#!/usr/bin/env python3
"""
Discord bot that manages brothers.json via @mentions.

Commands (tag the bot in any message):
  @bot add "Name" discord_id   — add a brother
  @bot remove "Name"           — remove a brother

Environment variables:
  DISCORD_BOT_TOKEN  — bot token (same one used by check_bot.py / tracker.py)
  GITHUB_TOKEN       — personal access token with repo contents:write scope
  GITHUB_REPO        — owner/repo (e.g. "jakewei/bros-house-script")
"""

import base64
import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import discord


def load_dotenv() -> None:
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

GITHUB_API = "https://api.github.com"
BROTHERS_PATH = "data/brothers.json"
TASKS_PATH = "data/tasks.json"


def github_request(token: str, repo: str, method: str, path: str, data: dict | None = None) -> dict:
    url = f"{GITHUB_API}/repos/{repo}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "BrothersBot/1.0",
        },
        method=method,
    )
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_github_json(github_token: str, repo: str, path: str) -> tuple[list, str]:
    """Fetch a JSON file from GitHub. Returns (parsed_content, file_sha)."""
    data = github_request(github_token, repo, "GET", f"/contents/{path}")
    content = base64.b64decode(data["content"]).decode()
    return json.loads(content), data["sha"]


def get_brothers(github_token: str, repo: str) -> tuple[list, str]:
    return get_github_json(github_token, repo, BROTHERS_PATH)


def assign_tasks(brothers: list, tasks: list, month_offset: int) -> dict[str, list]:
    n = len(brothers)
    start = month_offset % n
    rotated = brothers[start:] + brothers[:start]
    assignments = {b["name"]: [] for b in brothers}
    for i, task in enumerate(tasks):
        assignments[rotated[i % n]["name"]].append(task)
    return assignments


def commit_brothers(github_token: str, repo: str, brothers: list, sha: str, message: str) -> None:
    """Commit an updated brothers.json to GitHub."""
    content = json.dumps(brothers, indent=2, ensure_ascii=False) + "\n"
    encoded = base64.b64encode(content.encode()).decode()
    github_request(github_token, repo, "PUT", f"/contents/{BROTHERS_PATH}", {
        "message": message,
        "content": encoded,
        "sha": sha,
    })


class BrothersBot(discord.Client):
    def __init__(self, github_token: str, github_repo: str) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.github_token = github_token
        self.github_repo = github_repo

    async def on_ready(self) -> None:
        print(f"Bot online as {self.user} — listening for commands")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not self.user.mentioned_in(message):
            return

        content = re.sub(r"<@!?\d+>", "", message.content).strip()

        if content.lower().startswith("ping"):
            await message.reply("pong 🏓")
        elif content.lower().startswith("add"):
            await self._handle_add(message, content[3:].strip())
        elif content.lower().startswith("remove"):
            await self._handle_remove(message, content[6:].strip())
        elif content.lower().startswith("reassign"):
            await self._handle_reassign(message)
        else:
            await message.reply(
                "**Commands:**\n"
                '`@bot add "Name" discord_id`\n'
                '`@bot remove "Name"`\n'
                "`@bot reassign` — repost this month's schedule"
            )

    async def _handle_add(self, message: discord.Message, args: str) -> None:
        match = re.match(r'"([^"]+)"\s+(\d+)', args)
        if not match:
            match = re.match(r"(\S+(?:\s+\S+)*?)\s+(\d+)$", args)
        if not match:
            await message.reply('Usage: `@bot add "Name" discord_id`')
            return

        name = match.group(1)
        discord_id = match.group(2)

        try:
            brothers, sha = get_brothers(self.github_token, self.github_repo)
        except Exception as e:
            await message.reply(f"Failed to read brothers.json: {e}")
            return

        if any(b["name"].lower() == name.lower() for b in brothers):
            await message.reply(f"**{name}** is already in the list.")
            return

        brothers.append({"name": name, "discord_id": discord_id})

        try:
            commit_brothers(
                self.github_token, self.github_repo, brothers, sha,
                f"chore: add {name} to brothers list",
            )
            await message.reply(f"Added **{name}** (Discord ID: `{discord_id}`).")
        except Exception as e:
            await message.reply(f"Failed to update: {e}")

    async def _handle_reassign(self, message: discord.Message) -> None:
        try:
            brothers, _ = get_brothers(self.github_token, self.github_repo)
            tasks, _ = get_github_json(self.github_token, self.github_repo, TASKS_PATH)
        except Exception as e:
            await message.reply(f"Failed to read data files: {e}")
            return

        now = datetime.now()
        month_offset = now.year * 12 + now.month
        assignments = assign_tasks(brothers, tasks, month_offset)
        month_name = now.strftime("%B")

        mentions = " ".join(
            f"<@{b['discord_id']}>" for b in brothers if b.get("discord_id")
        )

        embed = discord.Embed(
            title=f"🏠 {month_name} {now.year} House Tasks (Updated)",
            color=0x5865F2,
        )
        embed.set_footer(text="Re-assigned due to roster change")

        for name, task_list in assignments.items():
            if task_list:
                parts = []
                for t in task_list:
                    block = f"**{t['name']}**"
                    if t.get("description"):
                        quoted = "\n".join(f"> {line}" for line in t["description"].split("\n"))
                        block += f"\n{quoted}"
                    parts.append(block)
                value = "\n\n".join(parts)
            else:
                value = "_No tasks this month — enjoy the break!_"
            embed.add_field(name=name, value=value, inline=False)

        await message.channel.send(
            content=f"{mentions} — updated {month_name} {now.year} assignments!",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def _handle_remove(self, message: discord.Message, args: str) -> None:
        name = args.strip('"').strip()
        if not name:
            await message.reply('Usage: `@bot remove "Name"`')
            return

        try:
            brothers, sha = get_brothers(self.github_token, self.github_repo)
        except Exception as e:
            await message.reply(f"Failed to read brothers.json: {e}")
            return

        filtered = [b for b in brothers if b["name"].lower() != name.lower()]
        if len(filtered) == len(brothers):
            await message.reply(f"**{name}** not found in the list.")
            return

        try:
            commit_brothers(
                self.github_token, self.github_repo, filtered, sha,
                f"chore: remove {name} from brothers list",
            )
            await message.reply(f"Removed **{name}**.")
        except Exception as e:
            await message.reply(f"Failed to update: {e}")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:
        pass


def start_health_server() -> None:
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Health server listening on port {port}")


def main() -> None:
    load_dotenv()
    start_health_server()

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    github_repo = os.environ.get("GITHUB_REPO", "").strip()

    if not token:
        raise SystemExit("Set DISCORD_BOT_TOKEN")
    if not github_token:
        raise SystemExit("Set GITHUB_TOKEN (needs contents:write scope)")
    if not github_repo:
        raise SystemExit("Set GITHUB_REPO (e.g. owner/repo)")

    bot = BrothersBot(github_token, github_repo)
    bot.run(token)


if __name__ == "__main__":
    main()
