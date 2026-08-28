# Desktopper

A local Python app for macOS. You describe an information model in ordinary language. An LLM returns an additive schema diff. Python applies the diff to SQLite. Safari shows list and form screens from that schema.

The model does not write HTML, JavaScript, or SQL. Flask serves a frozen shell. Data and secrets live under Application Support.

There is no Node.js runtime and no npm.

## Status

The MVP works end to end: schema engine, CRUD, search, Ops intent chat, and the first screen language.

Screen language covers related child lists, belongs-to parent links, list scopes, form field groups, empty states, and primary vs lookup tables.

The **FINAL** shape adds reminders and scheduling, computed formulas, automation rules, auth with column grants, CSV import profiles, peer sync, and declarative home layouts (metrics, kanban, calendar, and more). Ops still applies schema via intent; only **hooks** and **reminders** have direct CRUD panels on Ops.

## Requirements

- macOS
- Python 3.11 or newer
- Safari (open `http://127.0.0.1`, not a `file://` page)
- An LLM key for xAI Grok, or a local OpenAI-compatible endpoint such as Ollama

## Install

1. Clone this repository.
2. Create a virtual environment: `python3 -m venv .venv`
3. Activate it: `source .venv/bin/activate`
4. Install Python packages: `pip install -r requirements.txt`
5. Fetch Bootstrap once: `python3 tools/fetch_bootstrap.py`

If `static/css/bootstrap.min.css` is missing, `python3 -m app.server` prints a message and exits.

## Run

1. Start the server: `python3 -m app.server`
2. Open the printed URL in Safari, for example `http://127.0.0.1:8000/`.

The process binds to `server.bind` in `conf.yaml`. It refuses `0.0.0.0`.

On first start the process creates:

`~/Library/Application Support/Desktopper/`

It copies `.env.example` to `.env` and `config.yaml.example` to `conf.yaml` only if those files are absent. It does not overwrite files that already exist.

Override the appdir with `DESKTOPPER_APPDIR`. Tests must set that variable to a temporary directory.

## Config

| File | Role |
| --- | --- |
| Repo `.env.example` | Template. Live copy is `appdir/.env`. Holds `LLM_API_KEY` (or `XAI_API_KEY` for xAI). |
| Repo `config.yaml.example` | Template. Live copy is `appdir/conf.yaml`. Holds bind, port, LLM provider, model, timeouts, timezone, log knobs. |

Do not put the API key in YAML. Do not commit live `.env` or `conf.yaml`. The server does not serve those files over HTTP.

Edit knobs in Application Support, then restart the process.

Named LLM providers live under `llm.provider` in `conf.yaml`.

- `xai` uses `https://api.x.ai/v1` and defaults to `grok-4.6`.
- `openai_compatible` uses the URL you set. Local Ollama is valid.

Put the key in `.env` only.

## Use

Home (`/`) is the generated app: lists, forms, related child lists, and search. It has no chat box.

Ops (`/ops`) is where you describe changes. The LLM returns a JSON schema diff. The host validates and applies it. After a successful change, refresh the App tab. Home does not live-update.

The runtime system prompt is `FINAL_SYSTEM_PROMPT` in `app/system_prompt.py`. Files under `docs/cache/*-PROMPT.md` are design drafts only; the server does not read them.

The navbar **Ops** link uses `href="/ops"` and `target="_blank"`. You must click it. The app does not open Ops by itself and does not redirect `/` to `/ops`.

Hash routes: `#list/contacts` and `#form/contacts/1`.

### Screen language

| Feature | Meaning |
| --- | --- |
| Related | Child rows on a parent form, with inline add |
| Belongs-to | Bound parent fk shown as a link back to the parent |
| Scopes | Named list filters such as All / Open / Done |
| Groups | Labeled field sections on long forms |
| Empty | Optional copy when a list or related block has no rows |
| Lookup vs primary | Catalogs use `"role": "lookup"` and appear under Lookups. Global search skips them. `app.home` must be a primary list. Join lists use `"nav": false`. |

Optional seed without Ops:

1. Start the server.
2. Run `python3 tools/seed_schema.py`
3. Refresh Safari.

### Hooks

CRUD hooks are arbitrary Python that runs on **create**, **update**, or **delete**. **Startup** hooks run once when the Python server starts. Files live in `appdir/hooks/`. The registry is `appdir/hooks.json`.

- **Create or change via Ops:** describe behavior in the intent box (for example, “when I create a note, write the body to exports”). The LLM returns `add_hooks` or `update_hooks` in the spec diff.
- **Edit manually:** on the Ops page, use the Hooks table — Edit, change code, Save. Enable, Disable, or Delete from the same panel.
- **Transaction:** if a CRUD hook raises, the row change rolls back. Startup hook errors are logged; the server still starts.

Hook files must define `run(ctx)`. CRUD hooks use `ctx.row`, `ctx.conn`, and related fields. Startup hooks use `ctx.appdir` and `ctx.cfg`.

### Reminders and scheduling

Reminders fire on a schedule (cron-like or one-shot). The background scheduler runs in the Python process and writes **notices** when a reminder is due. On Home, the navbar badge shows unread notices; layout widgets can list them with snooze and dismiss actions.

- **Create or change via Ops:** describe the reminder in the intent box (for example, “remind me every Monday to review open tasks”). The LLM returns `add_reminders` or `update_reminders` in the spec diff.
- **Ops panel:** use the Reminders table to enable, disable, edit, or delete reminders directly.
- **API:** `GET/POST/PATCH/DELETE /api/reminders` plus `/snooze` and `/dismiss` on individual reminders.

### Formulas and rules

**Formulas** are named expressions (aggregates, dates, row math) declared in `add_formulas`. List and layout views can reference them; row formulas run on read with grant-aware column hiding.

**Rules** run on write or on a schedule (`add_rules`). They can send email, insert notices, or patch rows when conditions match.

Describe both in Ops intent; there is no separate Ops editor for formulas or rules.

### Auth

Users and roles live in the host database. Column **grants** in the schema hide fields per role. Home has a **Login** control in the navbar (`POST /api/login`, session cookie). Unauthenticated reads use the default guest role.

On first run the host creates one **owner** account from `auth.owner` in `conf.yaml` (see `config.yaml.example`: default name and password `admin`). Override with `DESKTOPPER_OWNER_NAME` or `DESKTOPPER_OWNER_PASSWORD` in the appdir `.env`. If no password is configured, the server prints a one-time random password at startup.

Create additional users on Ops (**Users** panel, owner session required) or with `POST /api/users`. List users with `GET /api/users` (owner only).

### CSV import

**Import profiles** map CSV columns to tables (`add_import_profiles`). When profiles exist, Home shows a CSV import control. Upload hits `POST /api/import/{profile_id}` with multipart form field `file`.

### Sync

Peer sync logs row changes to `_sync_events`. On Ops, **Sync export** writes events to the appdir; **Sync import** applies a JSON batch from another replica (`GET /api/sync/export`, `POST /api/sync/import`). Conflict resolution is last-write-wins on configured tables.

### Layouts

`add_layouts` defines the home dashboard: widgets such as **metric**, **notices**, **reminders**, **text**, **table** links, **kanban**, and **calendar**. Home renders the layout named by `app.home` when it points at a layout id instead of a list screen.

### Reset local data

To wipe schema and rows but keep secrets and knobs, stop the server and delete these under the appdir:

- `app.sqlite` (and `app.sqlite-wal` / `app.sqlite-shm` if present)
- `schema.json`
- `schema.json.bak`
- `migrations/`

Keep `.env` and `conf.yaml`. You may also delete `desktopper.jsonl` if you want a clean log.

## Tests

Prefer the project virtualenv:

```
.venv/bin/python -m unittest discover -s tests -v
```

Useful focused runs:

```
.venv/bin/python -m unittest tests.test_hooks tests.test_screens tests.test_slice7 tests.test_slice8 tests.test_final -v
```

## Layout

```
app/           Python (config, engine, intent, LLM, CRUD, search, Flask)
static/        Frozen HTML, CSS, JS
tools/         Bootstrap fetch and optional seed
tests/
.env.example
config.yaml.example
requirements.txt
LICENSE
```

User data, schema, SQLite, and logs go in the Application Support appdir, not in git.

## License

MIT. See [LICENSE](LICENSE). Copyright 2026 Rodney Degracia.
