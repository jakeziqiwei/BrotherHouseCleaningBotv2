# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the script

```bash
# Dry run (no Discord post) — prints assignments and the payload that would be sent
python3 assign.py

# Live run — posts to Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... python3 assign.py
```

No dependencies beyond the Python 3.11+ standard library.

## Architecture

The project has one entry point (`assign.py`) and two data files. The GitHub Actions workflow runs the script monthly and injects the webhook URL from a repository secret.

**Data flow:**
1. `data/brothers.json` — array of `{name, discord_id}` objects (discord_id is optional; omitting it falls back to bold name instead of a mention)
2. `data/tasks.json` — array of `{name, description}` objects (description is optional)
3. `assign.py` reads both files, distributes tasks round-robin, and POSTs a Discord embed via webhook

**Rotation logic (`assign_tasks`):**
- `month_offset = year * 12 + month` gives a unique integer per calendar month
- `start = month_offset % num_brothers` shifts the starting brother each month
- Tasks are assigned round-robin from that starting position, so the rotation is deterministic and repeatable

**Imbalanced counts:**
- More tasks than brothers → some brothers receive multiple tasks
- More brothers than tasks → some brothers receive no task that month (shown as "enjoy the break")

## GitHub Actions

Workflow: `.github/workflows/monthly_tasks.yml`
- Triggers automatically at 12:00 UTC on the 1st of every month, plus `workflow_dispatch` for manual runs
- Requires one repository secret: `DISCORD_WEBHOOK_URL`

## Data file schemas

`data/brothers.json`:
```json
[
  { "name": "Display Name", "discord_id": "123456789012345678" }
]
```

`data/tasks.json`:
```json
[
  { "name": "Task Name", "description": "Optional detail shown under the task" }
]
```
