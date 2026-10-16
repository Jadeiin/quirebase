# Export preference storage

The Svelte frontend stores export defaults in `localStorage`, isolated by User ID.
The storage adapter is `frontend/src/lib/export-preferences.ts`; Account settings writes
preferences, while Library and Item export actions read them. A format selected for one
export does not replace the saved Account defaults.

Preferences are optional browser state, not server settings. They do not synchronize across
devices and cannot establish authorization or determine which export options the API accepts.

## Current v1 contract

The account key is:

```text
quirebase:export-preferences:v1:account:<userId>
```

Its JSON value contains only the current supported options:

```json
{
  "schemaVersion": 1,
  "citation": {
    "format": "csl",
    "includeAbstract": true,
    "preserveCase": false,
    "encoding": "unicode",
    "doiPolicy": "include",
    "urlPolicy": "include",
    "excludedFields": "",
    "sortBy": "input",
    "citationKeyFormula": "auth.capitalize + year + shorttitle(1).capitalize",
    "citationKeyForceAscii": true
  },
  "document": {
    "includeAnnotations": false,
    "includeSupplements": false
  }
}
```

Supported formats are `csl`, `bibtex`, `ris`, `csl-json` and `commonmeta`. Sort order is
`input`, `citation_key`, `author`, `year` or `title`. The current alpha design changes v1 directly;
there are no previous-version readers, field aliases, migration paths or fallback keys.

BibTeX supports Unicode text or LaTeX character commands (`encoding: unicode|latex`) and
title case protection (`preserveCase`). Both representations escape TeX-special text and retain
inline math; characters without a known LaTeX representation remain Unicode.
DOI policies are `include|omit`; URL policies are `include|omit|omit_when_doi`. These apply to
BibTeX, RIS, CSL-JSON and rendered CSL bibliographies. `omit_when_doi` tests the original Work's
valid DOI, independently of whether the DOI is included in the output.

`excludedFields` contains comma- or whitespace-separated native field names. Library and Item
requests send the resulting list only for BibTeX and CSL-JSON. Exclusions are case-insensitive;
required identity and type fields cannot be excluded. RIS does not support generic exclusions.
Rendered CSL bibliographies follow their style's sorting. Commonmeta exports preserve the
complete Work, including descriptions and identifiers, regardless of presentation preferences.

Citation Styles belong to a Workspace. Their preference is stored separately as a raw string:

```text
quirebase:export-preferences:v1:account:<userId>:workspace:<workspaceId>:citation-style
```

The account JSON does not contain `style`. Reading without a Workspace uses `apa`; reading
with a Workspace uses that Workspace's stored style or `apa`. Other export defaults are
shared across the User's Workspaces. Account settings checks the selected style against
the corresponding Workspace catalog and resets unavailable styles to `apa`.

## Validation and failure handling

Reads start with a fresh copy of the defaults. The account payload must be an object with
`schemaVersion: 1` and citation/document objects. Only recognized, correctly typed fields
are loaded: booleans remain booleans, enumerated values must be supported, Citation Key
formulas are limited to 1,000 characters, excluded-field text to 8,192 characters and style keys
to 240 characters. The export API separately limits exclusions to 100 native field names of at
most 80 characters each. Unknown fields
are ignored and missing or invalid values use defaults. Reading does not rewrite storage.

Account settings hydrates before saving changes. Only a successfully validated Citation Key
formula and ASCII option replace their saved values. Export requests still validate those
options independently. Stored Item Citation Keys remain authoritative; generated export
keys apply to Items without one, and output keys are disambiguated within each bibliography.

JSON parsing and storage access are contained by the adapter. Unreadable or malformed values
use defaults; a write failure returns `false` without interrupting export controls. Browser
storage can be cleared or unavailable, so export correctness never depends on persistence.

Reset writes current defaults, including `apa` for the selected Workspace. It does not clear
other Workspaces' Citation Style choices. Only low-sensitivity export options belong here;
Item content, queries, credentials and session tokens must not be stored in these preferences.
