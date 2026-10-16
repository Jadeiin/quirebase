# commonmeta-py 0.309 conversion reproductions

This bundle isolates five conversion defects from Inquiro and Quirebase: RIS value truncation
at hyphens, the RIS `TI` title alias, CSL local keys overriding bibliographic identifiers,
CSL date ranges inventing exact dates, and versioned Software becoming a CSL book.
It targets the installed, pinned 0.309 release; it makes no claim about other releases.

`test_conversions.py` imports only commonmeta, pytest and the Python standard library.
Against unmodified 0.309, the result is **17 failed, 3 passed**. With `conversions.patch`
applied to an isolated copy of that package, **20 passed**. The patch changes upstream
readers/writers directly; it is a review proposal, not a runtime dependency override.
No upstream issue or pull request has been published. The upstream project's full suite
has not been run against this proposal.

From the Quirebase repository root, reproduce the failures with:

```sh
uv run pytest -q docs/upstream/commonmeta-py-0.309/test_conversions.py
```

In a separate checkout of the matching commonmeta-py source, apply the patch from its root:

```sh
git apply --check /absolute/path/to/conversions.patch
git apply /absolute/path/to/conversions.patch
```

Run the independent tests with that checkout installed or on `PYTHONPATH`. For this session,
the isolated copy and red/green logs are under `.cache/commonmeta-checks/` (not committed).
The test file is outside Quirebase's normal pytest collection because its purpose is to
fail against the currently pinned upstream release.

Until a tested upstream release is adopted, Inquiro's `_commonmeta_adapters.py` supplies
temporary input normalization and semantic guards. It normalizes `TI`, distinguishes CSL
record keys from bibliographic IDs, and reduces date ranges to shared year/month precision.
RIS records with hyphenated values or continuation lines are explicitly rejected rather
than corrupted; valid sibling records remain importable. Versioned Software retains its
Work type in storage and Commonmeta, while CSL conversion returns a format error.
The production dependency is unchanged and this patch is not applied to `.venv`.

Remove each corresponding adapter or guard only after a dependency release passes these
standalone tests and Inquiro's import/export regressions. Keep Item draft state, selection
of sync sources, authorization, persistence and ImportBatch idempotency in Quirebase.
