# Desktopper

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#requirements)

Local macOS app that builds information models from ordinary language.

You describe tables and screens in Ops. An LLM returns an additive schema diff. Python validates the diff and applies it to SQLite. Safari shows lists, forms, and layouts from that schema.

The model does not write HTML, JavaScript, or SQL. Flask serves a frozen shell. Data and secrets live under Application Support. There is no Node.js runtime and no npm.

## Features

- **Ops intent chat** — describe schema changes in plain language; the host validates and applies JSON diffs
- **Generated UI** — lists, forms, related child lists, belongs-to links, scopes, field groups, and empty states
- **Lookups vs primary tables** — catalogs stay out of global search; join lists can hide from nav
- **Hooks** — Python `run(ctx)` on create, update, delete, or server startup
- **Reminders and notices** — cron-like or one-shot schedules with navbar badges and snooze/dismiss
- **Formulas and rules** — named expressions and write/schedule automations via Ops
- **Auth and grants** — users, roles, and column-level visibility
- **CSV import** — named profiles map CSV columns to tables
- **Peer sync** — export/import change events with last-write-wins conflicts
- **Layouts** — home dashboards with metric, kanban, calendar, notices, and more

Day-to-day runbooks live in [docs/OPERATOR-GUIDE.md](docs/OPERATOR-GUIDE.md).

## Table of contents

- [Operator guide](docs/OPERATOR-GUIDE.md)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Screen language](#screen-language)
- [Hooks](#hooks)
- [Reminders and scheduling](#reminders-and-scheduling)
- [Formulas and rules](#formulas-and-rules)
- [Auth](#auth)
- [CSV import](#csv-import)
- [Sync](#sync)
- [Layouts](#layouts)
- [Reset local data](#reset-local-data)
- [Development](#development)
- [Project layout](#project-layout)
- [License](#license)

## Requirements

- macOS
- Python 3.11 or newer
- Safari (open `http://127.0.0.1`, not a `file://` page)
- An LLM API key for xAI Grok, or a local OpenAI-compatible endpoint such as Ollama

## Quick start

### Install

1. Clone this repository.
2. From the repo root, install into the Python you use on the command line (no project `.venv`):

   ```bash
   python3 -m pip install -e .
   ```

   Check that `which python3` and `which pip` (or `python3 -m pip`) are the same environment. If you use conda `(base)` but `which python3` shows Homebrew (`/opt/homebrew/...`), either put conda first on `PATH` or install with conda’s pip:

   ```bash
   "$HOME/miniconda3/bin/pip" install -e .
   ```

   Homebrew’s Python (PEP 668) often refuses `pip install` into itself. Prefer conda, or another env you manage — not a project `.venv` unless you want one.

3. Fetch Bootstrap once: `python3 tools/fetch_bootstrap.py`

`python3 -m pip install -r requirements.txt` is equivalent (it installs `-e .`).

### Run

1. Start the server: `desktopper`. To use a port other than `server.port` in `conf.yaml`, add `--port N`.
2. Open the printed URL in Safari, for example `http://127.0.0.1:8000/`.

To run Desktopper in the background, use `desktopper daemon start`. To start it at login with launchd, use `desktopper daemon install`. See [Background service](docs/OPERATOR-GUIDE.md#background-service).

If `desktopper` is not on your `PATH`, run `python3 -m app.server` from the repo (same `python3` you installed into), or put that environment’s `bin` directory on `PATH` (for conda: `$HOME/miniconda3/bin`).

The process binds to `server.bind` in `conf.yaml`. It refuses `0.0.0.0`.

On first start the process creates:

```text
~/Library/Application Support/Desktopper/
```

It copies `.env.example` to `.env` and `config.yaml.example` to `conf.yaml` only when those files are absent. It does not overwrite existing files.

Override the appdir with `DESKTOPPER_APPDIR`. Tests must set that variable to a temporary directory.

Optional seed without Ops:

1. Start the server.
2. Run `python3 tools/seed_schema.py`
3. Refresh Safari.

## Configuration

| File | Role |
| --- | --- |
| Repo `.env.example` | Template. Live copy is `appdir/.env`. Holds `LLM_API_KEY` (or `XAI_API_KEY` for xAI). |
| Repo `config.yaml.example` | Template. Live copy is `appdir/conf.yaml`. Holds bind, port, LLM provider, model, timeouts, timezone, and log knobs. |

Do not put the API key in YAML. Do not commit live `.env` or `conf.yaml`. The server does not serve those files over HTTP.

Edit knobs in Application Support, then restart the process.

Named LLM providers live under `llm.provider` in `conf.yaml`:

| Provider | Notes |
| --- | --- |
| `xai` | Uses `https://api.x.ai/v1`. Default model is `grok-4.6`. |
| `openai_compatible` | Uses the URL you set. Local Ollama is valid. |

Put the key in `.env` only.

## Usage

| Surface | URL | Role |
| --- | --- | --- |
| Home | `/` | Generated app: lists, forms, related child lists, and search. No chat box. |
| Ops | `/ops` | Describe changes. The LLM returns a JSON schema diff. The host validates and applies it. |

After a successful Ops change, return to Home and refresh. Home does not live-update.

The navbar **Ops** link opens `/ops` in the same tab. You must click it. The app does not open Ops by itself and does not redirect `/` to `/ops`.

Hash routes: `#list/contacts` and `#form/contacts/1`.

The runtime system prompt is `FINAL_SYSTEM_PROMPT` in `app/system_prompt.py`. Files under `docs/cache/*-PROMPT.md` are design drafts only. The server does not read them.

Ops still applies most schema via intent. **Packs** loads ordered markdown prompt recipes. Only **hooks** and **reminders** have direct CRUD panels on Ops.

## Screen language

| Feature | Meaning |
| --- | --- |
| Related | Child rows on a parent form, with inline add |
| Belongs-to | Bound parent foreign key shown as a link back to the parent |
| Scopes | Named list filters such as All / Open / Done |
| Groups | Labeled field sections on long forms |
| Empty | Optional copy when a list or related block has no rows |
| Lookup vs primary | Catalogs use `"role": "lookup"` and appear under Lookups. Global search skips them. `app.home` must be a primary list. Join lists use `"nav": false`. |

## Hooks

CRUD hooks are Python that runs on **create**, **update**, or **delete**. **Startup** hooks run once when the Python server starts. Files live in `appdir/hooks/`. The registry is `appdir/hooks.json`.

- **Create or change via Ops:** describe behavior in the intent box (for example, “when I create a note, write the body to exports”). The LLM returns `add_hooks` or `update_hooks` in the spec diff.
- **Edit manually:** on the Ops page, use the Hooks table — Edit, change code, Save. Enable, Disable, or Delete from the same panel.
- **Transaction:** if a CRUD hook raises, the row change rolls back. Startup hook errors are logged; the server still starts.

Hook files must define `run(ctx)`. CRUD hooks use `ctx.row`, `ctx.conn`, and related fields. Startup hooks use `ctx.appdir` and `ctx.cfg`.

## Reminders and scheduling

Reminders fire on a schedule (cron-like or one-shot). The background scheduler runs in the Python process and writes **notices** when a reminder is due. On Home, the navbar badge shows unread notices. Layout widgets can list them with snooze and dismiss actions.

- **Create or change via Ops:** describe the reminder in the intent box (for example, “remind me every Monday to review open tasks”). The LLM returns `add_reminders` or `update_reminders` in the spec diff.
- **Ops panel:** use the Reminders table to enable, disable, edit, or delete reminders directly.
- **API:** `GET` / `POST` / `PATCH` / `DELETE` `/api/reminders`, plus `/snooze` and `/dismiss` on individual reminders.

## Formulas and rules

**Formulas** are named expressions (aggregates, dates, row math) declared in `add_formulas`. List and layout views can reference them. Row formulas run on read with grant-aware column hiding.

**Rules** run on write or on a schedule (`add_rules`). They can send email, insert notices, or patch rows when conditions match.

Describe both in Ops intent. There is no separate Ops editor for formulas or rules.

## Auth

Users and roles live in the host database. Column **grants** in the schema hide fields per role. Home has a **Login** control in the navbar (`POST /api/login`, session cookie). Unauthenticated reads use the default guest role.

On first run the host creates one **owner** account from `auth.owner` in `conf.yaml` (see `config.yaml.example`: default name and password `admin`). Override with `DESKTOPPER_OWNER_NAME` or `DESKTOPPER_OWNER_PASSWORD` in the appdir `.env`. If no password is configured, the server prints a one-time random password at startup.

Create additional users on Ops (**Users** panel, owner session required) or with `POST /api/users`. List users with `GET /api/users` (owner only).

## CSV import

**Import profiles** map CSV columns to tables (`add_import_profiles`). When profiles exist, Home shows a CSV import control. Upload hits `POST /api/import/{profile_id}` with multipart form field `file`.

## Sync

Peer sync logs row changes to `_sync_events`. On Ops, **Sync export** writes events to the appdir. **Sync import** applies a JSON batch from another replica (`GET /api/sync/export`, `POST /api/sync/import`). Conflict resolution is last-write-wins on configured tables.

## Layouts

`add_layouts` defines the home dashboard. Widgets include **metric**, **notices**, **reminders**, **text**, **table** links, **kanban**, and **calendar**. Home renders the layout named by `app.home` when it points at a layout id instead of a list screen. The **kanban** widget shows every enum value as a column (including empty ones); drag a card to update that status field, or click a card to open its edit modal. **New** opens a create modal with Cancel and Ok. The status field starts at the first enum value. The **calendar** widget is a month grid (prev/next) for a table date column; click an item to open its form.

## Reset local data

To wipe schema and rows but keep secrets and knobs, stop the server and delete these under the appdir:

- `app.sqlite` (and `app.sqlite-wal` / `app.sqlite-shm` if present)
- `schema.json`
- `schema.json.bak`
- `migrations/`

Keep `.env` and `conf.yaml`. You may also delete `desktopper.jsonl` if you want a clean log.

## Development

With the package installed in the Python you use for tests:

```bash
python3 -m unittest discover -s tests -v
```

Focused runs:

```bash
python3 -m unittest tests.test_hooks tests.test_screens tests.test_slice7 tests.test_slice8 tests.test_final -v
```

## Project layout

```text
app/                  Python (config, engine, intent, LLM, CRUD, search, Flask)
static/               Frozen HTML, CSS, JS
tools/                Bootstrap fetch and optional seed
tests/                unittest suite
.env.example          Secrets template (copied to appdir)
config.yaml.example   Knobs template (copied to appdir as conf.yaml)
pyproject.toml        Package metadata and `desktopper` CLI entry point
requirements.txt      Thin wrapper: `pip install -e .`
LICENSE
```

User data, schema, SQLite, and logs go in the Application Support appdir, not in git.

## License

MIT. See [LICENSE](LICENSE). Copyright 2026 Rodney Degracia.
