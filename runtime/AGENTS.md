# Maltose Repository Instructions

## Project Context

Maltose is a local voice assistant with wake-word detection, speech
recognition, speaker identity, TaskBrain orchestration, Memory, and an
optional Document Knowledge Base (KDB).

## Repository Boundaries

- `maltose/`: production Python package. Runtime code belongs here.
- `dev/`: development-only plans, architecture decisions, progress notes,
  development agents, and developer tools. Start with [dev/README.md](dev/README.md)
  and [dev/major_plan.md](dev/major_plan.md).
- `data/`: local runtime state and indexes. It is generated/persistent data,
  not source code.
- `data/logs/knowledge.log`: background KDB watcher log when started via
  `./start`; inspect with `tail -f` when diagnosing indexing.
- `documents/`: user-owned original documents. This is the KDB source of truth.
- `models/`: downloaded model files and model caches.
- `recordings/`: local audio artifacts.
- `tests/`: automated tests; use temporary directories for test state.

## Development Workflow

Before a substantial change:

1. Read this file.
2. Read `dev/README.md` and `dev/major_plan.md`.
3. Locate the relevant feature plan under `dev/features/`.
4. Check existing tests and preserve unrelated user changes.

After a change:

1. Add or update tests proportional to the risk.
2. Run the focused tests, then the relevant full suite.
3. Run `git diff --check`.
4. Update the feature plan's status, verification result, and next step.

## KDB Rules

- Original files under `documents/` are the source of truth.
- Metadata, vectors, summaries, and queue state are indexes or operational
  state; they must not replace original files.
- KDB storage must remain separate from Memory storage.
- Reads must stay inside the configured document root.
- Prefer `uv run` for project commands.
- Do not commit local credentials, user documents, runtime databases, model
  caches, or recordings.

## Documentation Rules

- Markdown is the development documentation source of truth.
- Keep `dev/major_plan.md` high-level; put implementation details in the
  relevant feature plan.
- Record significant architecture changes as ADRs under `dev/decisions/`.
