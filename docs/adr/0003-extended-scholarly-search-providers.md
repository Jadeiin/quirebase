# ADR 0003: extended scholarly metadata and search providers (PMC, NASA ADS, IEEE Xplore)

Status: accepted.

Following ADR 0001's requirement that deferred external integrations be bounded, credentialed, and documented through dedicated ADRs, Quirebase adds PubMed Central (PMC), NASA Astrophysics Data System (NASA ADS), and IEEE Xplore to its fixed provider allowlist for metadata lookup and online search.

## Bounded Architecture & Security Invariants

1. **Fixed HTTPS Endpoints**: Connections are restricted strictly to official provider endpoints (`https://eutils.ncbi.nlm.nih.gov`, `https://api.adsabs.harvard.edu`, `https://ieeexploreapi.ieee.org`). Redirects remain forbidden.
2. **Credential Gating**: NASA ADS requires `QUIREBASE_NASA_ADS_TOKEN` (Bearer token); IEEE Xplore requires `QUIREBASE_IEEE_API_KEY` (query parameter); PMC accepts optional `QUIREBASE_NCBI_API_KEY` and contact email for rate-limit tiering. Searches against credentialed sources fail cleanly with descriptive configuration errors when keys are absent.
3. **Identifier Scoping**: NASA ADS uses `bibcode` and IEEE Xplore uses `article_number`. Both require explicit provider specification on metadata lookup to avoid ambiguous collisions in automatic identifier detection.
4. **Search Query Sanitization**: All provider queries are mapped from structured `SearchClause` filters with dialect-appropriate boolean operators and field prefixes.
5. **No Direct Import**: Search results are candidate summaries only. Selecting a result triggers identifier resolution and enters the mandatory preview-before-commit flow.
6. **Auditing**: Provider lookups and searches are audited without recording query terms or user search text.
