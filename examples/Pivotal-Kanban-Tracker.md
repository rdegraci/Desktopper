# Ops prompts: Tracker-style app

Use these as **separate Ops pastes**, in order. Wait for each to apply successfully before the next. After each apply, refresh Home.

There are **4** prompts: 3 required, plus 1 optional polish.

## How to run it

1. Start Desktopper, open **Ops**.
2. Paste Prompt 1 → apply → refresh Home → create a project and a few stories.
3. Prompt 2 → apply → check story list filters.
4. Prompt 3 → apply → refresh Home → use the board (drag/click).
5. Prompt 4 if you want form grouping.

---

## Prompt 1 — Core model (tables + screens only)

Paste this first on an empty (or fresh) schema:

```text
Build a lightweight Pivotal Tracker–style app called Tracker.

Tables:
1) projects — name (required text), description (textarea, optional)
2) stories — title (required text), description (textarea, optional),
   story_type (select: feature, bug, chore, release),
   state (select: unstarted, started, finished, delivered, accepted, rejected),
   points (integer number, optional, nullable),
   project_id (required foreign key to projects, display the project name)

Screens:
- List and form for projects. On the project form, show related stories
  filtered by project_id, with inline add. Empty copy: "No stories yet. Add one."
- List and form for stories. On the story form, show the project as a
  belongs-to link back to the project.
- Set app title to Tracker. Set home to the projects list for now.
- Story list empty copy: "No stories yet. Add one from a project or here."

Do not add layouts, formulas, rules, or reminders in this step.
```

If Ops **proposes** instead of applying, review the diff, then say `apply` (or confirm in the UI) when it looks right.

---

## Prompt 2 — List scopes (icebox / backlog / current / done)

```text
On the stories list, add scopes:
- Icebox: state = unstarted
- Started: state = started
- Finished: state = finished
- Delivered: state = delivered
- Accepted: state = accepted
- Rejected: state = rejected

Keep the host All filter. Do not add new tables.
```

(Pivotal’s Icebox/Backlog/Current are planning buckets; here we map filters to **story state**, which matches Desktopper scopes and the kanban column.)

---

## Prompt 3 — Board home + points metric

```text
Add a home dashboard layout called story_board titled "Story board".

Include:
1) A metric for total story points still open: sum of points on stories
   whose state is unstarted, started, finished, or delivered
   (exclude accepted and rejected). Label it "Open points".
2) A full-width kanban of stories by state, title_column title.

Add a layout screen for that board and set app.home to that layout screen
so Home opens on the board.

Do not add reminders or rules yet.
```

After this, Home should show empty status columns; drag moves `state`, click opens the story edit modal.

---

## Prompt 4 — Optional polish (only if you want it)

```text
On the stories form, group fields:
- Details: title, description, story_type, points
- Workflow: state, project_id

On the projects list, empty copy: "No projects yet. Add one."
```

---

## If Ops goes sideways

- Say: `Only tables and screens; no layouts yet.` (for Prompt 1)
- Or: `Reuse the existing stories table; do not recreate it.`
- Prefer **propose** on big first diffs, then apply once the FK/`related` block looks correct.
