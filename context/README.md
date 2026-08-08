# context/

Durable project context for Cobalt. This directory is for notes that should
survive across sessions — the intent behind the project, decisions already made,
and conventions to follow. Code explains *what*; this explains *why*.

| File | Contents |
| --- | --- |
| `project.md` | The spec: what Cobalt is meant to be, in full. |
| `updated-context.md` | Source of truth for *what* gets tracked — every metric, ticker, and relationship chain. Written by the user. |
| `conventions.md` | Rules for how code in this repo is written. |
| `status.md` | What exists today and what's next. Update as work lands. |
| `docker.md` | How the app is containerised, what is deliberately not a container, and the host quirks that bite. |
| `etl-plan.md` | Source per tracked series, the gaps with no free source, and the deduplication decisions. |

Keep entries short and factual. If something here contradicts the code, the code
wins — fix the note.
