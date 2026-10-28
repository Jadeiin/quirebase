---
title: Develop and contribute
description: Run a source checkout and find the repository's engineering contracts.
---

The product guides describe supported tasks. Repository documents hold the domain vocabulary,
architecture decisions, implementation contracts, and testing conventions.

## Run a development checkout

Install Python 3.12+, uv 0.13.5+, and Bun 1.4+, then clone the repository and start development:

```sh
git clone https://github.com/Jadeiin/quirebase.git
cd quirebase
./scripts/dev.sh
```

The script prepares dependencies, initializes a development database, provisions the initial `admin`
User with password `quirebase-dev`, and starts Vite at `http://127.0.0.1:5173`, FastAPI at
`http://127.0.0.1:9060`, and a worker. Use this local development setup with disposable data.
See the [repository README](https://github.com/Jadeiin/quirebase/blob/main/README.md#development)
for manual setup and environment overrides.

## Read the engineering contracts

- [Domain glossary](https://github.com/Jadeiin/quirebase/blob/main/GLOSSARY.md): canonical terms and relationships.
- [Module ownership](https://github.com/Jadeiin/quirebase/blob/main/docs/architecture/modules.md): capability owners and dependency boundaries.
- [ADRs](https://github.com/Jadeiin/quirebase/tree/main/docs/adr): accepted architectural choices.
- [Architecture contracts](https://github.com/Jadeiin/quirebase/tree/main/docs/architecture): detailed behavior and concurrency rules.
- [Testing](https://github.com/Jadeiin/quirebase/blob/main/docs/TESTING.md): checks, fixtures, and integration environments.
- [Agent guidance](https://github.com/Jadeiin/quirebase/blob/main/AGENTS.md): repository-specific instructions, including migrations.

Use the glossary's terms in code, tests, and docs. Read the relevant decisions before changing
business behavior. Generate migrations through the repository's configured Alembic command.

## Maintain documentation with behavior

When a change affects a user task, update its guide in `site/src/content/docs/` in the same change.
Update architecture contracts when their invariants change. Put route descriptions and field
constraints in FastAPI so generated API Reference stays authoritative.

The documentation is an independent Starlight project. Run `bun install --cwd site --frozen-lockfile`
and `bun run --cwd site dev` from the repository root. A documentation build exports OpenAPI from the
source without starting a web server or initializing a database.

See the [documentation maintenance guide](https://github.com/Jadeiin/quirebase/blob/main/site/README.md)
for checks, translations, and static deployment.
