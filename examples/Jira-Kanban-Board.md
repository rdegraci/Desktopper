# Ops prompts: Jira-style board

Use these as **separate Ops pastes**, in order. Wait for each to apply successfully before the next. After each apply, refresh Home.

There are **4** prompts: 3 required, plus 1 optional polish.

After the board is live, each issue form is addressable as
`#form/issues/<id>` (for example `http://127.0.0.1:8000/#form/issues/1`).
Machine readers can fetch the same row as JSON from
`GET /api/tables/issues/<id>`.

## How to run it

1. Start Desktopper, open **Ops** (or load this file from **Packs**).
2. Paste Prompt 1 → apply → refresh Home → create a project and a few issues.
3. Prompt 2 → apply → check issue list filters.
4. Prompt 3 → apply → refresh Home → use the board (drag status, click to edit in a modal).
5. Prompt 4 if you want form grouping.

---

## Prompt 1 — Core model (tables + screens only)

Paste this first on an empty (or fresh) schema:

```text
Build a lightweight Jira-style issue tracker called Board.

Tables:
1) projects — name (required text), key (required text, short project key),
   description (textarea, optional)
2) issues — summary (required text), description (textarea, optional),
   issue_type (select: story, bug, task, epic),
   status (select: to_do, in_progress, in_review, done),
   priority (select: lowest, low, medium, high, highest),
   assignee (optional text),
   project_id (required foreign key to projects, display the project name)

Screens:
- List and form for projects. On the project form, show related issues
  filtered by project_id, with inline add. Empty copy: "No issues yet. Add one."
- List and form for issues. On the issue form, show the project as a
  belongs-to link back to the project.
- Set app title to Board. Set home to the projects list for now.
- Issue list empty copy: "No issues yet. Add one from a project or here."

Do not add layouts, formulas, rules, or reminders in this step.
```

If Ops **proposes** instead of applying, review the diff, then say `apply` (or confirm in the UI) when it looks right.

---

## Prompt 2 — List scopes (by status)

```text
On the issues list, add scopes:
- To Do: status = to_do
- In Progress: status = in_progress
- In Review: status = in_review
- Done: status = done

Keep the host All filter. Do not add new tables.
```

(These scopes mirror the kanban columns so the list and board stay aligned.)

---

## Prompt 3 — Board home + open-issue metric

```text
Add a home dashboard layout called issue_board titled "Issue board".

Include:
1) A metric for count of issues whose status is to_do, in_progress, or
   in_review (exclude done). Label it "Open issues".
2) A full-width kanban of issues by status, title_column summary.

Add a layout screen for that board and set app.home to that layout screen
so Home opens on the board.

Do not add reminders or rules yet.
```

After this, Home should show status columns (including empty ones); drag moves
`status`, click opens the issue edit modal.

---

## Prompt 4 — Optional polish (only if you want it)

```text
On the issues form, group fields:
- Details: summary, description, issue_type, priority, assignee
- Workflow: status, project_id

On the projects list, empty copy: "No projects yet. Add one."
```

---

## If Ops goes sideways

- Say: `Only tables and screens; no layouts yet.` (for Prompt 1)
- Or: `Reuse the existing issues table; do not recreate it.`
- Prefer **propose** on big first diffs, then apply once the FK/`related` block looks correct.
