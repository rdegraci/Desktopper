# Operator guide

This guide is for people who run Desktopper day to day. It covers start and stop, configuration, Ops, Home, auth, backups, sync, and common failures.

For install and feature overview, see the [README](../README.md).

## What you operate

Desktopper is a single Python process on macOS. It serves a loopback HTTP UI in Safari.

| Surface | URL | Purpose |
| --- | --- | --- |
| Home (App) | `/` | Use the generated app: lists, forms, search, notices, layouts. |
| Ops | `/ops` | Change schema and automation. Manage hooks, reminders, users, sync, and logs. |

The LLM never writes HTML, JavaScript, or SQL. The host validates schema diffs and applies them to SQLite. Data and secrets live in the appdir, not in the git repo.

## Day-one checklist

1. From the repo, activate the virtualenv: `source .venv/bin/activate`. If `.venv` is missing, follow the [README](../README.md) install steps first.
2. Confirm Bootstrap assets exist (`static/css/bootstrap.min.css`). If missing, run `python3 tools/fetch_bootstrap.py`.
3. Start the server: `python3 -m app.server`.
4. Open the printed URL in Safari (for example `http://127.0.0.1:8000/`).
5. Put an LLM key in `appdir/.env` if you use a cloud provider. Restart after edits.
6. Sign in on Home as the owner when you need user management or grant-aware views.
7. Open Ops and type `help` to see the built-in Ops help.

## Appdir and files

Default appdir:

```text
~/Library/Application Support/Desktopper/
```

Override with environment variable `DESKTOPPER_APPDIR` (tests must use a temporary directory).

| Path under appdir | Role |
| --- | --- |
| `.env` | Secrets (`LLM_API_KEY` / `XAI_API_KEY`, optional owner bootstrap). |
| `conf.yaml` | Bind, port, LLM provider, model, timeouts, timezone, logging, auth.owner. |
| `schema.json` | Current app schema (versioned). |
| `schema.json.bak` | Backup written before schema applies. |
| `app.sqlite` | User tables plus host tables (`_users`, `_sessions`, `_notices`, sync, schedules). |
| `migrations/` | Migration artifacts from schema applies. |
| `hooks/` and `hooks.json` | Hook source files and registry. |
| `ops_thread.jsonl` | Ops conversation history. |
| `desktopper.jsonl` | Rotating JSON Lines server log (name from `logging.file`). |
| `replica.json` | Local sync replica id and sequence. |
| `sync_out/` | JSON batches written by Sync export. |

First start copies `.env.example` and `config.yaml.example` into the appdir only when those files are absent. The process does not overwrite existing files.

Do not put API keys in `conf.yaml`. Do not commit live `.env` or `conf.yaml`. The server does not serve those files over HTTP.

## Start and stop

### Start

From the repo, activate the project virtualenv, then start the server:

```bash
source .venv/bin/activate
python3 -m app.server
```

Without activating, call the venv interpreter directly:

```bash
.venv/bin/python -m app.server
```

Do not use a bare system or conda `(base)` `python3` unless that environment has the packages from `requirements.txt`. A missing `flask` (or `yaml`) usually means the wrong interpreter.

On success the process prints the Home URL and keeps running. Startup also:

1. Loads config and creates the appdir if needed.
2. Ensures host tables exist.
3. Creates the owner account if no users exist yet.
4. Runs enabled **startup** hooks.
5. Starts the background scheduler (ticks every 10 seconds).

### Stop

Stop the process in the terminal (Ctrl+C). There is no separate daemon service in this MVP.

### Bind rules

The process binds to `server.bind` in `conf.yaml`. Default is `127.0.0.1`. Bind `0.0.0.0` is refused. After you change bind, port, LLM settings, or secrets, restart the process.

## Configuration knobs

Edit files in the appdir, then restart.

### `.env`

| Variable | Purpose |
| --- | --- |
| `LLM_API_KEY` | Cloud LLM key (preferred). |
| `XAI_API_KEY` | Used for xAI when `LLM_API_KEY` is empty. |
| `DESKTOPPER_OWNER_NAME` | First-run owner username override. |
| `DESKTOPPER_OWNER_PASSWORD` | First-run owner password override. |

### `conf.yaml` (high value)

| Section | Operator notes |
| --- | --- |
| `server.bind` / `server.port` | Loopback only. Port must be free. |
| `llm.provider` | `xai` or `openai_compatible`. |
| `llm.model` / `llm.base_url` | Model name and endpoint. Ollama uses a local `base_url`. |
| `llm.timeout_seconds` | Long Ops intents can need 180s or more. |
| `llm.reasoning_effort` | xAI only: `low`, `medium`, `high`, `xhigh`. |
| `app.timezone` | IANA zone for UI timestamps and schedules. |
| `auth.owner` | First-run owner name/password when no users exist. |
| `logging.level` / `logging.file` | Log verbosity and JSONL file name. |

`app.support_name` names the Application Support folder. Do not change it after first run unless you also move data.

## Owner account and auth

On first run with an empty `_users` table:

- If `auth.owner.password` (or `DESKTOPPER_OWNER_PASSWORD`) is set, the host creates that owner and prints a creation notice.
- If no password is configured, the host prints a **one-time** username and password to the terminal. Save them immediately.

Sessions use cookie `desktopper_session` and last 72 hours. Home has Login / Logout. Unauthenticated reads use the guest role.

Column **grants** live in schema and hide fields per role. Define roles and grants through Ops intent. Create extra users on Ops (**Users** panel) while signed in as owner, or via `POST /api/users`.

You cannot create another account with role `owner` through the Users panel.

## Operating Home

- Use hash routes such as `#list/contacts` and `#form/contacts/1`.
- After Ops applies a schema change, return to Home and **refresh**. Home does not live-update.
- Navbar **Ops** opens `/ops` in the same tab. The app does not redirect `/` to Ops by itself.
- Unread notices show on the navbar badge when reminders or rules create them.
- CSV import appears on Home only when import profiles exist in schema.
- Login is required for owner-only actions and for grant-aware visibility beyond guest.

## Operating Ops

Ops is the control plane. Type `help` anytime for the built-in summary.

### Conversation (intent)

1. Describe the change in ordinary language (tables, screens, rules, permissions, formulas, layouts, and so on).
2. The assistant may **clarify** (ask questions), **propose** a plan, or **apply** a validated diff.
3. Nothing changes until a plan applies (or you confirm Apply on a proposal).
4. On validation failure, Ops shows the error and the rejected diff so you can edit and retry.
5. After a successful apply, note the new schema version, open Home, and refresh.

**Empty schema tip:** first describe tables and list/form screens. Add dashboard layouts, rules, or reminders in a second intent.

**Field changes tip:**

- Hide a field to stop showing it.
- Use label updates to rename display text.
- Use column updates for widget changes.
- To change type, add a new column and hide the old one, or use `remove_columns` when you mean to delete stored data.

### UI context from Home

Home can open Ops anchored to the current screen, column, field, or related list. Ops shows a chip such as “Talking about: …”. Clear the chip when you want a general request.

### Thread

The conversation persists in `ops_thread.jsonl` across reloads. Use **Clear thread** when the thread no longer matches the schema (for example after a data reset) or when context confuses the model. Recent turns are sent to the model for context.

### Panels on Ops

| Panel | Use when |
| --- | --- |
| Packs | Load a shipped or local markdown prompt pack and run ordered Ops intents step by step. Propose still requires Apply; the thread is not cleared on load. |
| Reminders | Create, edit, enable, or disable wall-clock reminders. View scheduler status. |
| Business rules | List data nags; enable, disable, or delete rules. Create and edit `when` / `then` in the conversation. |
| Hooks | Edit Python hook code; enable, disable, or delete hooks. |
| Users | Create app login accounts (owner session required). |
| Sync export / import | Move change events between replicas. |
| Logs | Read and copy recent server events. |

Most schema still goes through the conversation. Formulas have no separate Ops editor. Rules are authored via intent; the Business rules panel manages enable, disable, and delete.

## Hooks

Hook files live in `appdir/hooks/`. The registry is `hooks.json`.

- CRUD hooks run on create, update, or delete. They must define `run(ctx)` and may use `ctx.row`, `ctx.conn`, and related fields.
- Startup hooks run once when the server starts. They use `ctx.appdir` and `ctx.cfg`.
- If a CRUD hook raises, the row change rolls back.
- Startup hook errors are logged. The server still starts.

Prefer Ops intent to add hooks. Use the Hooks panel to edit code after creation.

## Reminders and the scheduler

The scheduler is a daemon thread inside the server process. It ticks about every 10 seconds and fires due reminders and jobs.

Reminder schedule kinds in the Ops editor include `once`, `daily`, `weekly`, and `interval`. Schema may also use column-based schedules. When due, reminders typically create **notices** on Home.

Reminders only fire while the server process runs. If the process is stopped, due work waits until the next tick after restart.

Check scheduler status on the Ops Reminders panel (`/api/scheduler/status`).

## Sync between replicas

1. Declare sync tables in schema (`update_sync` via Ops intent).
2. Row changes on those tables append to `_sync_events`.
3. On Ops, **Sync export** writes a JSON batch under `appdir/sync_out/`.
4. On the other replica, **Sync import** (or `POST /api/sync/import`) applies the batch.

Conflict policy is last-write-wins on configured tables. Each replica has a `replica.json` id and sequence. Already-applied remote sequences are skipped.

## Logs and diagnostics

- File log: `appdir/desktopper.jsonl` (or `logging.file`). JSON Lines, rotated by size.
- Ops **Logs** panel and `GET /api/logs` show recent events.
- HTTP requests (except static CSS/JS) emit `http.request` events with a request id.
- Copy recent logs from Ops when you report a failure.

Do not paste `.env` contents into tickets. Logs redact common key patterns, but treat the log file as sensitive.

## Backup and reset

### Backup (recommended)

Stop the server first when you need a consistent copy. Copy at least:

- `schema.json` and `schema.json.bak`
- `app.sqlite` plus `-wal` / `-shm` if present
- `hooks/` and `hooks.json`
- `.env` and `conf.yaml` (secrets)
- Optional: `ops_thread.jsonl`, `desktopper.jsonl`, `replica.json`, `migrations/`, `sync_out/`

### Reset schema and rows (keep knobs)

Stop the server. Delete under the appdir:

- `app.sqlite` (and wal/shm)
- `schema.json`
- `schema.json.bak`
- `migrations/`

Keep `.env` and `conf.yaml`. Optionally delete `desktopper.jsonl` and `ops_thread.jsonl` for a clean Ops thread and log. Restart. The owner account is created again if `_users` is empty (because the database file was removed).

## Common failures

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'flask'` (or `yaml`) | Wrong Python (system or conda base) | From the repo: `source .venv/bin/activate`, or run `.venv/bin/python -m app.server`. Install with `pip install -r requirements.txt` inside the venv if needed. |
| Process exits: Bootstrap CSS missing | Assets not fetched | With the venv active, run `python3 tools/fetch_bootstrap.py`. |
| Process exits: bind refused | `server.bind` is `0.0.0.0` | Set a loopback address in `conf.yaml`. |
| Process exits: unknown LLM provider | Bad `llm.provider` | Use `xai` or `openai_compatible`. |
| Ops returns LLM down / timeout | Network, key, model, or timeout | Check `.env` key, provider URL, and `timeout_seconds`. Restart after edits. |
| Ops returns validation error | Diff fails host rules | Read the error and rejected diff. Clarify intent or edit the proposal and retry. |
| Home looks stale after Ops | No live refresh | Hard-refresh Home after a successful apply. |
| Reminders do not fire | Server stopped or reminder disabled | Keep the process running. Check Reminders panel and scheduler status. |
| Users panel blocked | Not signed in as owner | Log in on Home as owner, then open Ops. |
| Empty schema but old thread | Thread survived a reset | Clear thread on Ops, or delete `ops_thread.jsonl`. |
| Port already in use | Another process on the port | Change `server.port` or stop the other process. |

## Security notes for operators

- Bind stays on loopback by design. Do not expose the port on a public interface.
- Treat the appdir as the trust boundary: secrets, database, hooks, and logs.
- Hook code runs inside the server process with full local privileges of that process. Review hook changes before you enable them.
- Change the default owner password (`admin` / `admin` in the example) on any machine that other people can use.
- Safari should open `http://127.0.0.1`, not a `file://` page.

## Quick command reference

```bash
# Activate venv (from repo) — required so python3 has Flask and deps
source .venv/bin/activate

# Or skip activate and call the venv interpreter:
# .venv/bin/python -m app.server

# One-time Bootstrap fetch
python3 tools/fetch_bootstrap.py

# Run
python3 -m app.server

# Optional sample schema (server must be running)
python3 tools/seed_schema.py

# Override data directory for a throwaway instance
DESKTOPPER_APPDIR=/tmp/desktopper-op python3 -m app.server
```

## Related files

| File | Audience |
| --- | --- |
| [README.md](../README.md) | Install, features, and reference |
| `config.yaml.example` | Knobs template |
| `.env.example` | Secrets template |
| `app/system_prompt.py` | Runtime Ops system prompt (not for day-to-day edits) |
| `docs/cache/*` | Design drafts only; the server does not read them |
