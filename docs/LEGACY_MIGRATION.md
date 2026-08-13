# Read-only legacy migration

Create and verify a backup of both installations first. Initialize Quirebase and create the account that will own imported records. Then run a preflight without `--commit`:

```sh
quirebase migrate-legacy --database /old/data/database/main.sq3 --data-dir /old/data --owner admin --report migration.json
```

The source SQLite database is opened with `mode=ro`; source files are only read. Review missing/corrupt PDFs and unsupported-field warnings, then repeat with `--commit`. The importer copies PDFs through the content-addressed store, queues extraction, maps items, authors, keywords, DOI, tags, projects and discussions, and records source fingerprints so rerunning does not duplicate items or projects. Legacy password hashes are deliberately not imported; imported ownership is assigned to the selected existing account.

After the worker drains its queue, run `quirebase reindex` and `quirebase doctor`, compare counts, manually sample PDFs and metadata, and retain the old installation read-only until acceptance is signed off.
