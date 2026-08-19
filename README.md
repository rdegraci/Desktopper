# Desktopper

A local Python app for macOS. You describe an information model in ordinary language. An LLM proposes an additive SQLite schema. Safari shows list and form screens from that schema.

The model does not write HTML, JavaScript, or SQL. Flask serves a frozen shell. Data and secrets live under Application Support.

There is no Node.js runtime and no npm.

## Status

The MVP is under construction. Slice 1 is in the tree: Flask, appdir config, JSON logs, home page, and Ops page.

Later slices add a one-time Bootstrap download, the schema engine, CRUD, search, the home renderer, and Ops chat with the LLM.

## Requirements

- macOS
- Python 3.11 or newer
- Safari (open `http://127.0.0.1`, not a `file://` page)
- An OpenAI-compatible LLM endpoint when you reach the intent slice (local Ollama is valid)

## Install

1. Clone this repository.
2. Create a virtual environment: `python3 -m venv .venv`
3. Activate it: `source .venv/bin/activate`
4. Install Python packages: `pip install -r requirements.txt`
5. Fetch Bootstrap once: `python3 tools/fetch_bootstrap.py`

Step 5 lands in a later slice. Until that script exists, `python3 -m app.server` prints a message and exits if `static/css/bootstrap.min.css` is missing.

## Run

1. Start the server: `python3 -m app.server`
2. Open the printed URL in Safari, for example `http://127.0.0.1:8000/`.

The process binds to `server.bind` in `conf.yaml`. It refuses `0.0.0.0`.

On first start the process creates:

`~/Library/Application Support/Desktopper/`

It copies `.env.example` to `.env` and `config.yaml.example` to `conf.yaml` only if those files are absent. It does not overwrite files that already exist.

Tests must set `DESKTOPPER_APPDIR` to a temporary directory.

## Config

| File | Role |
| --- | --- |
| Repo `.env.example` | Template. Live copy is `appdir/.env`. Holds `LLM_API_KEY`. |
| Repo `config.yaml.example` | Template. Live copy is `appdir/conf.yaml`. Holds bind, port, LLM URL, model, timeouts, timezone, log knobs. |

Do not put the API key in YAML. Do not commit live `.env` or `conf.yaml`. The server does not serve those files over HTTP.

Edit knobs in Application Support, then restart the process.

## Use

Home (`/`) is the generated app: lists, forms, and search. It has no chat box.

The navbar **Ops** link uses `href="/ops"` and `target="_blank"`. You must click it. The app does not open Ops by itself and does not redirect `/` to `/ops`.

Ops (`/ops`) is where you talk to the LLM (when that slice is present). After a successful schema change, refresh the home tab. Home does not live-update.

## Tests

```
python3 -m unittest tests.test_slice1 -v
```

## Layout

```
app/           Python (config, log, Flask)
static/        Frozen HTML, CSS, JS
tools/         One-time vendor fetch
tests/
.env.example
config.yaml.example
requirements.txt
LICENSE
```

User data, schema, SQLite, and logs go in the Application Support appdir, not in git.

## License

MIT. See [LICENSE](LICENSE). Copyright 2026 Rodney Degracia.
