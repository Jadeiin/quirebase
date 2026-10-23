# Business concurrency testing

The contracts come from [ADR 0011](../adr/0011-unified-business-concurrency.md) and the
current Workspace model in [ADR 0013](../adr/0013-workspaces-as-data-governance-and-acl-boundaries.md).
Workspace membership owns authority; Projects have no owner. Short synchronous commands use
their admission boundary; durable finalizers reauthorize before publishing canonical state.
An explicit conflict is an allowed result. Tests must not assume that every competing request succeeds.

## Conflict matrix

The machine-readable invariant registry is [concurrency_cases.json](../../tests/concurrency_cases.json).
Tests identify their contract with `@pytest.mark.concurrency_case("id")`. The report lists actual
parameterized node IDs, so a passed selected schedule does not imply all possible orders are covered.

The registry covers authentication/revocation, governance and membership generations, Project
participation, association idempotency, metadata/Annotation versions, Import replay and durable
finalization. Generated coverage reports map each invariant to the collected parameterized tests;
use those reports for the current schedules and results.

The root-deletion tests directly hold/delete parent rows to control the database cascade, then invoke
public business mutations. The metadata and import tests inspect final state through public Library,
Search and Audit interfaces. They use native PostgreSQL search tables rather than mocking Search.

The report's `evidence_enabled` flag distinguishes scenarios using the shared harness from tests
with local synchronization. Those results are included in the matrix but do not gain SQL/lock
evidence automatically. The upload-finalizer guard tests exercise a private authorization helper;
neither those tests nor the in-memory durable client prove crash recovery through a real DBOS restart.

`test_durable_recovery.py` separately exercises real process death with DBOS. It stops the PDF
Import executor after completed extraction/database checkpoints, changes live descriptor metadata
and runs production recovery in a fresh process. It then stops a confirmation process after its
canonical commit, before returning a response, and retries confirmation from another process.
The test checks original durable input semantics, checkpoint reuse, stable Item identity, one
successful Audit/side-effect set, file ownership transfer and rejected-object cleanup. Both database
variants use fresh migrations and isolated databases; PostgreSQL requires database-creation rights.
This covers these selected boundaries, rather than every finalizer or cleanup crash schedule.

## Run and reproduce

Use a **dedicated disposable PostgreSQL database**. These fixtures create and drop application tables.
Do not point them at an application database. PostgreSQL is the supported multi-worker database;
SQLite tests cannot establish row-lock correctness.

```sh
export QUIREBASE_TEST_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/quirebase_test
uv sync --extra postgres --frozen
uv run pytest -q tests/test_postgres_concurrency.py tests/test_concurrency_harness.py \
  tests/test_concurrency_reporting.py \
  --concurrency-report-dir=concurrency-results --junitxml=concurrency-results/junit.xml

# Replay the exact parameterized schedule from coverage.json or a failure artifact.
uv run pytest -q \
  'tests/test_postgres_concurrency.py::test_concurrent_metadata_replacements_reject_stale_version[alpha-first]' \
  --concurrency-report-dir=concurrency-results

# Real process death, checkpoint recovery and lost confirmation responses.
uv run pytest -q tests/test_durable_recovery.py
```

Without the PostgreSQL URL, database cases skip. A skipped case is never counted as passing coverage.
`shared_postgres` serializes destructive schema fixtures across pytest workers with an advisory lock;
the competing transactions inside a test remain independent and concurrent.

## Shared interleaving harness

`postgres_race.session("actor")` owns a separate Session and pins its connection across commits.
`start()` owns the competing task; `join()` observes its outcome with a bounded wait.
`wait_blocked("waiter", "holder")` waits for that **direct** edge in `pg_blocking_pids`, rather than
assuming SQL has started after a fixed sleep. PostgreSQL can queue a second contender behind the first
contender's tuple lock, giving `second → first → holder`; assert the actual edges explicitly.
Use bounded Events for an application-level checkpoint, and `note()` to label its release.

Place business assertions inside a named verification Session when a live failure snapshot matters.
Unexpected Session errors, pytest failures and harness timeouts capture evidence before Session
cleanup or task cancellation. A failure detected only after all actors have closed still retains
their SQL/wait trace, but its activity snapshot may contain no live actors.

On failure the harness writes `failures/<node-hash>-<worker>.json` containing the node ID, named
backend PIDs, elapsed SQL/transaction/wait trace, original exception type and SQLSTATE, server version/isolation,
`pg_stat_activity` and `pg_locks`. The first failure and first snapshot survive subsequent cleanup
errors. Collection is bounded and diagnostic errors do not replace the business failure. The trace
omits bound parameters, connection URLs and exception-message parameter dumps; PostgreSQL's current
query text can still contain SQL literals. Use synthetic inputs for these artifacts.

Every owned task is cancelled and awaited before schema teardown. Forgetting to join an operation
fails the test. Actor connections also have lock/statement/idle-transaction limits. Harness tests
verify actual blocking, PID stability after commit, timeout cleanup, pytest failure capture,
parameter omission and a real deadlock's SQLSTATE `40P01`.

## CI coverage

The PostgreSQL CI job runs database contracts, JSON query contracts and controlled
concurrency scenarios on PostgreSQL 18. A separate step checks PostgreSQL migrations and durable
recovery, followed by fresh initialization and doctor checks. SQLite variants, general business
tests and HTTP tests run in the SQLite matrix; the PostgreSQL job does not build the frontend.
It uploads coverage JSON/Markdown, JUnit and any failure snapshots, including when tests fail.
The separate nightly/manual replay workflow runs five rounds on five isolated databases and retains
each round's artifacts for 14 days.
These repeat controlled schedules; they do not generate random interleavings.

Browser E2E also covers a PDF source refresh completing during a private draft's Save click.
The ordinary post-switch edit scenario waits for the selected source response and verifies the
actual PATCH body. CI retains failed browser traces/screenshots and repeats these two PDF scenarios
five times (30 on manual runs). Inspect the trace's DOM, input events and request body before attributing
an intermittent missing-text failure to a persistence race.

For a new failure, first identify the violated contract, operation pair and observed wait/commit
order. Minimize it into a deterministic regression. Repair the owning aggregate's lock order, CAS
predicate or database constraint; do not add blanket retries or a universal lock graph.
