# PROTOTYPE — ORM ownership layouts

Question: does moving SQLAlchemy mappings into capability packages improve locality enough to
justify the metadata aggregator and cross-capability relationship coupling, or should Quirebase
keep one centralized persistence mapping and enforce conceptual ownership separately?

This directory is throwaway evidence for issue #9. It is not production code.

Run the executable comparison with:

```bash
uv run python prototypes/issue-9-orm-layouts/measure.py
```

Open `comparison.html` directly for the guided decision walkthrough.
