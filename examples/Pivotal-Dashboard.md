# Ops prompts: Tracker dashboard upgrade

Use as a **separate Ops paste** after the Tracker core pack
(`Pivotal-Kanban-Tracker.md`) has been applied. Wait for apply, then refresh Home.

There is **1** required prompt.

## How to run it

1. Confirm projects, stories, `open_points`, and `story_board` already exist.
2. Open **Ops**, paste Prompt 1 → apply → refresh Home.
3. Home should show a screen titled **Dashboard** with a metric strip, kanban,
   projects table, and notices.

---

## Prompt 1 — Upgrade home Dashboard

```text
Upgrade the existing home dashboard layout story_board (keep id story_board
and story_board_screen). Reuse the open_points formula. Do not add new tables
or recreate projects/stories.

Add formulas (only if missing):
1) story_count_icebox — count of stories where state = unstarted
2) story_count_started — count of stories where state = started
3) story_count_delivered — count of stories where state = delivered
4) accepted_points — sum of points on stories where state = accepted

Replace story_board rows with this dashboard:

Row 1 (metrics, equal spans):
- Open points (existing open_points)
- Icebox (story_count_icebox)
- Started (story_count_started)
- Delivered (story_count_delivered)
- Accepted points (accepted_points)

Row 2:
- Full-width kanban of stories by state, title_column title

Row 3:
- span 8: table widget for projects (use the projects list screen if needed)
- span 4: notices widget

Keep app.home on story_board_screen. Set the user-facing title of both the
layout and the layout screen to "Dashboard" (keep ids story_board and
story_board_screen unchanged).
Do not add rules or reminders.
```

After this, Home should show **Dashboard** with the metric strip, drag/click
kanban, projects, and notices.

---

## If Ops goes sideways

- Say: `Update the existing story_board layout in place; do not add a second dashboard.`
- Or: `Reuse the existing open_points formula; do not recreate projects or stories.`
- Or: `Only change the layout and screen titles to Dashboard; keep the same widgets.`
- Prefer **propose** if the diff replaces the layout, then apply once the formula ids and widgets look correct.
