# Rules how-to

This guide explains **business rules** in Desktopper: what they do, how to
add them in Ops, and how they differ from reminders, layouts, and hooks.

For day-to-day Ops use, see the [Operator guide](OPERATOR-GUIDE.md).

## What a rule is

A rule is a small automation in `schema.json`. It watches rows on one table.
When its condition matches, it runs one or more actions.

Rules do **not** draw UI widgets. They change data or create notices. Layouts
(`add_layouts`) place widgets such as metrics, kanban, and notices on a screen.

| Piece | Role |
| --- | --- |
| `id` | Snake_case name (for example `nag_delivered`) |
| `enabled` | When `false`, the host skips the rule |
| `trigger` | `on_write` or `schedule` |
| `table` | Primary table the rule binds to |
| `when` | Boolean expression tree (must match the row) |
| `then` | Non-empty list of actions |

## Rules vs reminders vs hooks

| Feature | When to use |
| --- | --- |
| **Rule** | “When row data looks like X, notify me or update a column” |
| **Reminder** | Wall-clock nag (once, daily, weekly, interval) with no row `when` tree |
| **Hook** | Custom Python on create/update/delete or at startup |

Prefer a rule for data nags. Prefer a reminder for “ping me at 9am.” Prefer a
hook only when the four rule actions are not enough.

## How to add a rule

1. Open **Ops** (`/ops`).
2. Describe the nag in ordinary language. Example: “When a story stays in
   delivered, notify me to accept or reject it.”
3. Let Ops **propose**, then **apply** (or apply if the host auto-applies a
   safe diff).
4. Confirm notices on **Home** (navbar badge and notices widget, if present).

Add tables and columns first if the rule needs them. Empty-schema tip: create
list/form screens in one intent, then add rules in a later intent.

Create and change `when` / `then` through the Ops conversation (`add_rules`).
There is no visual rule builder.

## Manage on Ops (Business rules panel)

On Ops, open **Business rules** (after Reminders, before Hooks):

| Action | How |
| --- | --- |
| List | Id, table, trigger, short when/then summary |
| Enable / Disable | Toggle without rewriting the expression |
| Delete | Confirm, then hard-remove from `schema.rules` |
| Inspect | **JSON** expands read-only `when` / `then` |

The panel refreshes after a successful Ops apply. Create still happens in the
conversation above.

## Triggers

### `on_write`

Runs after a normal **create or update** of a row on that table (CRUD path).
It does not run on delete.

```json
"trigger": { "kind": "on_write" }
```

Omit `every_seconds`.

The host evaluates `when` on the row **after** the write. It is not a
transition detector: any matching update can fire the rule again (subject to
notice dedupe for `notify`).

### `schedule`

The built-in job `run_rules` runs on an interval (default every 60 seconds)
while the server is up. On each run it evaluates every enabled rule with
`trigger.kind` `schedule`, scans that rule’s table (up to 200 rows per rule
per tick), and runs actions for matching rows.

```json
"trigger": { "kind": "schedule", "every_seconds": 3600 }
```

`every_seconds` is part of the Ops schema contract (integer; prompt asks for
minimum 60). The schedule **job** cadence is what drives evaluation today;
repeat `notify` spam is limited by notice dedupe (below), not by per-rule
throttling on `every_seconds`.

Scheduled rules only run while the server process is up. If the process stops,
work waits until the next job fire after restart.

## Actions (`then`)

Allowed kinds:

| Kind | Effect |
| --- | --- |
| `notify` | Insert a notice (title, body). Preferred for nags |
| `set_column` | Update one column on the matched row |
| `create_row` | Insert a row into another table |
| `email` | Send email when SMTP is configured; otherwise may fall back to a notice |

You may put several actions in one rule’s `then` list. They run in order.

**Notify dedupe:** the host skips a new notice when an **unread** notice already
exists for the same rule id and row id within the last **24 hours**. That
limits spam from schedule ticks and repeat on_write matches.

**Email:** set `SMTP_HOST` (and usually `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`) in the environment. Use `email` only when the user asked for
email. Prefer `notify` for in-app nags.

## Expression `when`

`when` is the same expression language as formulas. It must evaluate to a
boolean for the current row.

Common ops: `eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `and`, `or`, `not`, `col`,
`lit`, `now`.

Example: state equals delivered:

```json
"when": {
  "op": "eq",
  "left": { "op": "col", "column": "state" },
  "right": { "op": "lit", "value": "delivered" }
}
```

## Examples

### Schedule nag (overdue task)

Ops intent: “Every hour, notify me about open tasks past due.”

```json
{
  "id": "nag_overdue",
  "enabled": true,
  "trigger": { "kind": "schedule", "every_seconds": 3600 },
  "table": "tasks",
  "when": {
    "op": "and",
    "args": [
      {
        "op": "lt",
        "left": { "op": "col", "column": "due_on" },
        "right": { "op": "now" }
      },
      {
        "op": "neq",
        "left": { "op": "col", "column": "status" },
        "right": { "op": "lit", "value": "done" }
      }
    ]
  },
  "then": [
    {
      "kind": "notify",
      "title": "Overdue task",
      "body": "A task is past due."
    }
  ]
}
```

### On-write notify (Tracker story)

Ops intent: “When a story moves to delivered, notify me.”

```json
{
  "id": "nag_on_delivered",
  "enabled": true,
  "trigger": { "kind": "on_write" },
  "table": "stories",
  "when": {
    "op": "eq",
    "left": { "op": "col", "column": "state" },
    "right": { "op": "lit", "value": "delivered" }
  },
  "then": [
    {
      "kind": "notify",
      "title": "Story delivered",
      "body": "Accept or reject this story."
    }
  ]
}
```

### Several actions in one rule

Put related steps in one `then` list:

```json
"then": [
  {
    "kind": "set_column",
    "column": "status",
    "value": { "op": "lit", "value": "overdue" }
  },
  {
    "kind": "notify",
    "title": "Marked overdue",
    "body": "Status set to overdue."
  }
]
```

## Can rules chain?

**No workflow chain.** Rules do not call other rules. There is no “next rule”
field.

| Pattern | Supported? |
| --- | --- |
| Several actions in one `then` | Yes |
| Rule A fires Rule B | No |
| Explicit dependency graph | No |

`set_column` and `create_row` from a rule use a direct SQL path. They do **not**
re-enter the normal CRUD path, so they do not re-trigger `on_write` rules.
Keep related steps in one rule.

## Disable or delete a rule

**Disable** (temporary mute): ask Ops to stop the nag, or click **Disable** on
the Business rules panel. The host sets `enabled` to `false` (`disable_rules`
or `PATCH /api/rules/<id>` with `{ "enabled": false }`). The rule stays in
schema.

Example intent: “Disable the nag_delivered rule.”

**Enable** again: click **Enable** on the panel (`PATCH` with
`{ "enabled": true }`). There is no separate `enable_rules` intent key; ask
Ops in plain language or use the panel.

**Delete** (remove from schema): ask Ops to delete or remove the rule, or click
**Delete** on the panel (confirm). The host uses `remove_rules` or
`DELETE /api/rules/<id>`. Past notices that stored the rule id stay.

Prefer disable when you may turn the nag back on. Prefer delete when the rule
is wrong or no longer wanted.

## Notices and the Home UI

`notify` writes to host notices. Unread notices show on the Home navbar badge.
A layout may include a `notices` widget so the list appears on a dashboard.

A rule never adds a kanban, metric, or other widget. Use Ops layouts for that.

## Limits and pitfalls

- Rules need a valid `table` that already exists in schema.
- Schedule evaluation follows the `run_rules` job (default every 60 seconds),
  not a separate per-rule timer.
- Scheduled scan: up to 200 rows per rule per `run_rules` tick.
- Server must be running for schedule triggers and the `run_rules` job.
- Do not expect rule actions to cascade into other `on_write` rules.
- Prefer `notify` over `email` unless SMTP is configured and requested.
- Author `when` / `then` via Ops intent; use the Business rules panel to manage
  enable, disable, and delete.

## Related files

| Path | Role |
| --- | --- |
| `app/rules.py` | Validate, run, list/toggle/delete helpers, apply rule diffs |
| `app/system_prompt.py` | Ops LLM contract for `add_rules` / `disable_rules` / `remove_rules` |
| `app/jobs.py` | Built-in `run_rules` schedule job |
| `static/ops.html` / `static/js/ops.js` | Business rules panel |
| `docs/OPERATOR-GUIDE.md` | Ops, reminders, notices overview |
| `docs/cache/THIN-RULES.md` | Design note (panel now shipped) |
