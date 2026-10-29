---
title: Develop and maintain documentation
description: Start a development checkout, find the engineering contracts, and submit behavior and documentation changes together.
---

Product pages explain user and operator tasks. `GLOSSARY.md`, ADRs, and architecture contracts define
the engineering vocabulary and invariants. Read the relevant contract before changing behavior.

## Start the development application

With Git, Python 3.12+, uv 0.13.5+, and Bun 1.4.4 available:

```sh
git clone https://github.com/Jadeiin/quirebase.git
cd quirebase
./scripts/dev.sh
```

The script installs dependencies, initializes development data, creates the initial `admin` User with
password `quirebase-dev` on first setup, and starts these local services:

| Service | Default address or role |
| --- | --- |
| Vite | `http://127.0.0.1:5173`, browser application with HMR |
| FastAPI | `http://127.0.0.1:9060`, HTTP API |
| Worker | Durable background processing using the same development data |

This is a development setup with known initial credentials. Deployment uses the separate
[installation procedure](/administration/deployment/) and an administrator-chosen password.
The [repository README](https://github.com/Jadeiin/quirebase/blob/main/README.md#development) lists
manual setup and `QUIREBASE_DEV_*` overrides.

## Run repository checks

Install hooks with:

```sh
uv run --frozen prek install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
```

The backend test suite needs the built application assets, even if you normally use Vite for HMR.
Before running it or relying on the pre-push hook:

```sh
bun install --cwd frontend --frozen-lockfile
bun run --cwd frontend build
uv run ruff check .
uv run mypy src/quirebase
uv run pytest -q -m "not oa" -n 4 --dist loadscope
```

Follow [Testing](https://github.com/Jadeiin/quirebase/blob/main/docs/TESTING.md) for PostgreSQL,
concurrency, optional dependencies, and the separate open-access PDF corpus.

## Preview and check the documentation

The docs project also requires Node.js 22.23.4+ and its own locked Bun dependencies:

```sh
uv sync --frozen
bun install --cwd site --frozen-lockfile
bun run --cwd site dev
```

Open the URL Astro reports. You do not need to initialize a database or run the application frontend
to author docs. After editing:

```sh
bun run --cwd site check
bun run --cwd site build
bun run --cwd site preview
```

Use the built preview to test Pagefind search; the development server does not build its search
index. Checks validate paired English/Chinese source pages, content/schema, internal links, and final
HTML assets and API coverage. The [maintenance guide](https://github.com/Jadeiin/quirebase/blob/main/site/README.md)
explains the authoring policy and artifact-only CI. GitHub Pages publication is a later, separate change.

## Put each change in its owned document

| You changed | Update |
| --- | --- |
| A user workflow or UI label | The English and Chinese task guides |
| Operator configuration, deployment, or recovery | The corresponding operator procedures |
| Route descriptions or schema constraints | FastAPI source, which generates API Reference |
| Domain terms or relationships | [Glossary](https://github.com/Jadeiin/quirebase/blob/main/GLOSSARY.md) |
| Architecture and invariants | [ADRs](https://github.com/Jadeiin/quirebase/tree/main/docs/adr) and [contracts](https://github.com/Jadeiin/quirebase/tree/main/docs/architecture) |

[Module ownership](https://github.com/Jadeiin/quirebase/blob/main/docs/architecture/modules.md) defines
capability/dependency boundaries. [Agent guidance](https://github.com/Jadeiin/quirebase/blob/main/AGENTS.md)
contains repository-specific instructions, including migration generation. Do not duplicate an API
parameter table in a hand-maintained guide; describe a complete task and link to generated reference.
