# Export preference storage

The Svelte frontend stores export defaults in `localStorage`, isolated by User ID.
The [storage adapter](../../frontend/src/lib/export-preferences.ts) defines fields, defaults and
validation. Account settings writes preferences, while Library and Item export actions read them. A format selected for one
export does not replace the saved Account defaults.

Preferences are optional browser state, not server settings. They do not synchronize across
devices and cannot establish authorization or determine which export options the API accepts.

## Current v1 contract

The account key is:

```text
quirebase:export-preferences:v1:account:<userId>
```

The JSON envelope has `schemaVersion: 1` with `citation` and `document` objects. It stores
bibliography format, rendering options, Citation Key preferences and document inclusion flags.
Supported format semantics are defined in the [interchange contract](item-metadata-json.md#interchange-support-and-measured-limitations).

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
to 240 characters. Unknown fields are ignored and missing or invalid values use defaults. Reading
does not rewrite storage.

Account settings hydrates before saving changes. Only a successfully validated Citation Key
formula and ASCII option replace their saved values. Export requests still validate those
options independently. Stored Item Citation Keys remain authoritative; generated export
keys apply to Items without one, and output keys are disambiguated within each bibliography.

JSON parsing and storage access are contained by the adapter. Unreadable or malformed values
use defaults; a write failure returns `false` without interrupting export controls.

Reset writes current defaults, including `apa` for the selected Workspace. It does not clear
other Workspaces' Citation Style choices. Only low-sensitivity export options belong here;
Item content, queries, credentials and session tokens must not be stored in these preferences.
