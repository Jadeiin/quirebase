# inquiro

Academic metadata discovery, multi-provider search, bibliography interchange, and CSL citation engine.

Provider lookup and Search use one synchronous runtime:

```python
from inquiro import ProviderRuntime, SearchClause, SearchQuery

with ProviderRuntime() as providers:
    candidate = providers.lookup("10.1038/s41586-019-1666-5")
    page = providers.search(
        SearchQuery(
            provider="crossref",
            clauses=(SearchClause("title", "and", "machine learning"),),
        )
    )
```

The runtime owns the fixed Provider catalog, identifier parsing, credentials and bounded HTTP
transport. Results are immutable `CandidateRecord` values. Tests can inject `MockExchange` through
`ProviderRuntime.with_exchange`; concrete Provider Implementations and registrations are private.

Bibliography and citation functionality has separate Module Interfaces under
`inquiro.bibliography` and `inquiro.citations`.
