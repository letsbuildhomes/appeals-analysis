# Instructions for agents

Read [docs/CONTEXT.md](docs/CONTEXT.md) before working here, especially "How
the user works".

## Secrets

`.env` holds the API keys. Never read, print, search, copy or source it, and
never print the environment (`env`, `printenv`, `set`). The code loads `.env`
itself whenever an `appeals` command runs, so nothing else needs it. To check
that keys are present, run `make doctor`, which reports only whether each key
is set. If a task seems to need a key's value, stop and ask the user.

## Improvement passes

After every pass against the answer key, report with the post-experiment assessment in
[docs/IMPROVING.md](docs/IMPROVING.md), in its order and format.
