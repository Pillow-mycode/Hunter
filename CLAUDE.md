# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Coding Guidelines

### Think Before Coding
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity First
- Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

### Surgical Changes
- Touch only what you must. Clean up only your own mess.
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- Remove imports/variables/functions that YOUR changes made unused, but don't remove pre-existing dead code unless asked.

### Goal-Driven Execution
- Define success criteria. Loop until verified.
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- For multi-step tasks, state a brief plan with verification steps.

### Git Commits
- After completing a significant task or phase, make a git commit.

## Overview

Hunter is an LLM-driven automated penetration testing tool with a multi-agent architecture that integrates with Kali Linux tools. It has a Python FastAPI server (deployed on Kali) and a browser-based web client. The server manages sessions via WebSocket, and four specialized LLM agents collaborate to plan and execute pentest tasks.

## Run the server (Kali Linux)

```bash
cd hunter-server
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit .env with your API keys
python server/app.py    # starts on http://0.0.0.0:8000
```

CLI interactive mode (no server):

```bash
python starter/main.py            # interactive REPL
python starter/main.py "scan example.com ports"  # single command
```

There are no tests or linting configured in this project.

## Architecture

### Multi-Agent System

Four LLM agents collaborate, each with its own OpenAI-compatible client, model, and system prompt:

1. **AttackLeader** (`agent/smart_brain/attack_leader.py`) — "Penetration Expert." Orchestrates the pentest: parses user requests, makes dynamic decisions in a loop, delegates tasks to the Weapon Master via natural-language instructions. Runs up to 50 steps with automatic termination on too many failures or no progress. Bilingual (zh/en).

2. **AttackToolMaster** (`agent/smart_brain/attack_tool_master.py`) — "Weapon Master." Receives instructions from AttackLeader, selects tools, generates/executes shell commands, waits for results. Uses a structured JSON response protocol with types like `check_tools`, `read_tool_doc`, `shell`, `task_done`, `need_message`, `install_tool`. Handles max 50 rounds internally.

3. **Hawkeye** (`agent/smart_brain/hawkeye.py`) — Interaction detection. Polls PTY output to detect whether a running process is waiting for user input (password prompts, confirmations, etc.). A lightweight LLM call; uses fresh messages each check to avoid history bloat.

4. **DataAnalyst** (`agent/smart_brain/data_analyst.py`) — Long-output analysis. When command output exceeds 30K chars, batches it and summarizes via LLM. Automatically saves full output to `results/<task_id>/`.

Each agent's config is in `agent/pojo/<name>_config.py`. They all read `DEFAULT_API_KEY|BASE_URL|MODEL` from `.env`, with per-agent overrides (`ATTACKER_*`, `LEADER_*`, `HAWKEYE_*`, `ANALYST_*`) taking priority.

### Server (FastAPI + WebSocket)

`server/app.py` is the entry point. Key components:

- **SessionManager** — creates/restores sessions, manages WebSocket connections, provides callbacks (`on_progress`, `on_need_input`, `on_need_confirm`) that bridge async WebSocket I/O with the synchronous agent logic (which runs in a thread pool via `run_in_executor`).
- **DatabaseManager** (`agent/manager/database_manager.py`) — SQLite persistence (`data/hunter.db`). Stores sessions and all messages with strict `order_index` ordering. Thread-safe with per-thread connections. Singleton via `get_database()`.
- **HistoryManager** (`agent/manager/history_manager.py`) — manages conversation history for LLM context.

HTTP endpoints: `POST /session`, `GET /session/{id}`, `GET /session/{id}/messages`, `DELETE /session/{id}`, `GET /sessions`, `POST /session/{id}/cancel`.

WebSocket: `ws://host:8000/ws/{session_id}`. Client sends `{type: "message"|"input"|"cancel"}`; server pushes `progress`, `need_input`, `need_confirm`, `task_completed`, `error`.

### Command Execution (`agent/system/system_command.py`)

`sys_shell(bash)` executes commands through a PTY (Linux) or winpty (Windows), using `pyte` to render ANSI output. A `TimeCountThread` polls Hawkeye every N seconds (with exponential backoff) to detect interaction prompts. The global `active_process` dict tracks the running process for later input injection via `write_input_to_active_process()`.

### Hardcoded Rules (`agent/smart_brain/hardcoded_rules.py`)

`HardcodedRules` checks tasks before execution for: high/medium risk actions requiring confirmation, sensitive target suffixes (`.gov`, `.mil`, `.edu`, etc.) that trigger abort, consecutive failure limits, and loop limits.

### Tool System

Tools are registered in `tools/tools_readme/all-tools.txt` with format: `[TYPE]tool_name:description;`. Three types:

- `[KALI]` — 86 Kali-native tools, Weapon Master uses directly from knowledge
- `[CUSTOM]` — project-specific tools (e.g., `brute_force_attack.py`), requires documentation in `tools/tools_readme/<name>.txt`; Weapon Master reads docs before use
- `[EXTERNAL]` — tools not in default Kali; Weapon Master checks installation (`check_tool_installed`) then auto-installs (`install_tool`) using commands from `_get_install_command()` in `attack_tool_master.py`

To add a custom tool: place it in `tools/<name>/`, write docs in `tools/tools_readme/<name>.txt`, register in `all-tools.txt`.

### Client

The client (`hunter-clinet/web/`) is a pure static web app: `index.html`, `app.js`, `style.css`. No build step. Connects to the server via HTTP + WebSocket.

### Platform adaptation

Change `my_platform` in `agent/system/system_command.py` from `"linux"` to `"windows"` for Windows server deployment (only Kali-native tools won't be available).

## Key files

| File | Purpose |
|------|---------|
| `server/app.py` | FastAPI server, SessionManager, WebSocket handler |
| `starter/main.py` | CLI entry point (interactive + single-command) |
| `agent/smart_brain/attack_leader.py` | Penetration Expert — decision loop, task orchestration |
| `agent/smart_brain/attack_tool_master.py` | Weapon Master — tool selection, shell execution |
| `agent/smart_brain/hawkeye.py` | Interaction detection agent |
| `agent/smart_brain/data_analyst.py` | Long output analysis agent |
| `agent/smart_brain/hardcoded_rules.py` | Pre-execution safety checks |
| `agent/system/system_command.py` | PTY command execution + Hawkeye integration |
| `agent/system/output_handler.py` | ANSI cleaning, output file saving, DataAnalyst trigger |
| `agent/manager/database_manager.py` | SQLite sessions + messages persistence |
| `agent/pojo/leader_config.py` | AttackLeader config + bilingual system prompts |
| `agent/pojo/attack_config.py` | WeaponMaster config + bilingual system prompts |
| `tools/tools_readme/all-tools.txt` | Tool registry (86 Kali + 14 external + 1 custom) |
