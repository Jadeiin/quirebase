---
status: accepted
---

# Account deactivation and owner reassignment

This specifies [ADR 0016](../adr/0016-account-deactivation-and-owner-reassignment.md).
It covers User deactivation, ordinary owner transfer and explicit instance-governance reassignment.

## Invariant and motivation

User provisioning creates an ordinary Workspace with an active owner membership. Requiring handover
before deactivation prevented administrators from immediately containing a new or compromised User.
Account activity controls effective access independently of the structural ownership assignment.

The invariant is:

- Every surviving Workspace has exactly one current owner membership.
- That membership has `state=active` and `terminated_at IS NULL`.
- The owner's User may be inactive. Effective authority still requires an active User and active
  current membership, followed by the existing resource-action decision.
- Creating a Workspace or assigning a new owner requires an active receiving User.

A membership CHECK and partial unique indexes enforce the row-level owner constraints.

## User deactivation and reactivation

Accounts owns User status, current administrator authorization, Login Session revocation,
Audit and transaction completion. Workspaces owns coordination with current membership
Workspace roots. Keep that operation behind the Workspaces interface rather than exposing generic
lock loaders to Accounts.

Deactivation must:

1. Acquire the existing User locks and recheck the acting administrator's authority.
2. Retain the Workspaces-owned fence over every current membership Workspace, in stable UUID order.
3. Permit existing owner memberships and set `User.active=False`.
4. Delete the User's Login Sessions and record `admin.user.status_update` in the same transaction.

Existing protections against self-deactivation remain. Authentication, API Token verification and
durable finalizers must continue rejecting inactive Users. Existing API Tokens remain unusable while
the User is inactive; deactivation does not acquire the separate semantics of permanent token
revocation. Existing workflows must reauthorize before canonical writes.

Deactivation preserves Workspace records, owner assignments, membership generations, participation,
content and explicit governance freezes. Other active members retain their existing permissions.
A Workspace whose only member is its inactive owner naturally has no effective User access.

Reactivation enables authority according to current memberships and policy. It does not reverse an
intervening ownership reassignment or recreate terminated memberships or cleared Project selections.

For offboarding, deactivate the User first, then explicitly reassign its Workspaces where handover
is needed. Reassignment by itself does not deactivate the previous owner or remove its retained
admin membership.

Owner read models and diagnostics must validate the structural owner membership independently of
User activity. Administrative projections expose the owner's account status as a governance fact.
Ordinary authentication and active-member filtering continue requiring active Users.

## Explicit administrator reassignment

Workspaces owns `reassign_workspace_owner` in its governance implementation and exports the use case
through its facade. Access owns the System action `workspace_governance.reassign_owner`, granted
to instance administrators through the canonical policy bundle. The caller need not be a Workspace
member. This is an explicit grant of ownership to the selected receiving User.

HTTP operation:

```text
POST /api/v1/admin/workspaces/{workspace_id}/owner
{
  "new_owner_user_id": "<UUID>",
  "expected_owner_user_id": "<UUID>",
  "reason": "<10–1000 characters>"
}
```

Return the updated `AdminWorkspaceView`, including owner identity and account status. Adapters parse
the request; Workspaces owns authorization, target validation, membership changes, Audit and commit.
The current owner must match `expected_owner_user_id` under the root lock. A different current owner
returns a conflict and requires refreshing the form. A repeated request after a successful change
may therefore return a conflict; it must not repeat access changes or overwrite a different owner.
When the expected current owner is already the requested target, return an unchanged result without
another reassignment event.

Receiving User rules:

| Receiving User's membership | Result |
| --- | --- |
| Current active membership | Promote that membership to owner |
| Current suspended membership | Reactivate and promote that membership; audit both effects |
| No current membership | Create a new active owner membership |
| Previously terminated membership | Create a new membership generation; preserve historical rows |
| Inactive or missing User | Reject the operation |

The confirmation explicitly states that the selected User will gain Workspace owner access. Admission
or reactivation retires pending Workspace Invitations for that User using the existing invitation
invalidation rules. A new membership generation restores no former ProjectParticipant selections;
reactivation retains the existing generation's stored selections, following current membership rules.

Demote the previous owner to Workspace admin, matching ordinary ownership transfer. Its account and
membership state otherwise remain unchanged. The executing administrator gains content access only
when explicitly selected as the receiving owner and recorded as such.

Lifecycle rules:

| Workspace state | Reassignment |
| --- | --- |
| Active and unfrozen | Allowed |
| Archived and unfrozen | Allowed through this explicit governance operation; retain archive state |
| Administratively frozen | Blocked; administrator explicitly unfreezes before reassignment |
| Physically deleted | Not found |

Archive support is a documented exception to ordinary archived membership-mutation restrictions.
Reassignment never restores or unfreezes a Workspace as a side effect. Existing owner-initiated
transfer keeps its current membership, target and lifecycle checks.

## Concurrency and Audit

The lock-based concurrent outcomes in this section apply to PostgreSQL, following
[ADR 0011](../adr/0011-unified-business-concurrency.md). SQLite uses the single-host, single-worker
profile with ordinary transaction semantics.

Lock the acting administrator and receiving User in stable UUID order before acquiring the Workspace
root. Recheck current administrator authority and receiving User activity while retaining those User
guards. Under the exclusive Workspace root lock, load and validate the single current owner, compare
the expected owner, then change memberships and invalidate affected invitations atomically.

Accounts retains its User-before-Workspace order for deactivation. No new command acquires a User
lock after locking a Workspace. Keep the existing ordinary transfer order and reload authority under
its root lock.

Required outcomes include:

- If receiver deactivation commits first, subsequent reassignment rejects that inactive receiver.
- If reassignment commits first, subsequent receiver deactivation succeeds and leaves a structurally
  valid owner membership with no effective authority for that inactive User.
- Concurrent ordinary transfer and administrator reassignment serialize on the root. Reassignment
  rejects an unexpected current owner; ordinary transfer rechecks its actor's current authority.
- Concurrent deletion, membership admission, termination and actor-role revocation preserve the
  same root, membership-generation and fresh-authorization contracts.

Record `admin.workspace.owner_reassign` with the administrator, Workspace, previous owner, new owner,
receiving membership identity, admission/reactivation effect and required reason. Commit that Audit
Event with all membership changes. Keep ordinary `workspace.ownership.transfer` and account-status
Audit semantics distinct. No-op reassignment creates no new reassignment event.

## Administrative UI and module ownership

The Users page permits deactivation even when the User owns Workspaces. It explains the immediate
loss of account access without performing automatic Workspace handover.

The Workspaces administration page shows owner username and account status and provides an explicit
reassignment action. The form selects an active User and requires a reason. It submits the displayed
current owner as the expected owner. On conflict, refresh the current facts and preserve the draft
for an explicit retry. Keep the open form's Workspace row visible even if a directory filter stops
matching after refresh; closing the form restores ordinary filtering. Render actions from
server-provided decisions or choices.

| Module | Responsibility |
| --- | --- |
| Accounts | User status, account authentication and session invalidation |
| Workspaces | Membership fencing, ownership invariant, reassignment and owner projections |
| Access | System action and unchanged ordinary Workspace policy |
| Audit | Event construction and immutable reassignment provenance |
| Web / frontend | HTTP projection, account and Workspace governance forms and conflict handling |

Use existing dependency directions. Accounts calls the Workspaces-owned deactivation cooperation
operation; Workspaces must not import Accounts to read User activity from shared mappings. The Web
adapter calls owned facade use cases. Administrator operations remain outside the curated MCP toolset.

## Verification

Run the following acceptance cases against SQLite and PostgreSQL where applicable:

- Create a User through administration and invitation acceptance, then deactivate it immediately.
  Both flows succeed without modifying the provisioned Workspace's ownership or content.
- Inactive owners remain visible in Workspace read models and pass structural diagnostics; their
  sessions, API requests, MCP requests and durable finalizers cannot retain effective authority.
- Other active members retain their authorized reads and writes. Reactivation restores only current
  authority, including after ownership has been reassigned.
- Ordinary owner membership suspension/termination remains prohibited; new owner assignment to an
  inactive User remains prohibited.
- Administrator reassignment covers active, suspended, absent and terminated receiving memberships;
  preserves exactly one owner; handles stale expectations and no-op requests; and audits each effect.
- A non-member administrator assigning another User gains no content membership or ordinary content
  access. Unauthorized actors and stale administrator authority cannot reassign ownership.
- Archived and frozen Workspace behavior matches the table above, with no implicit lifecycle change.
- Controlled PostgreSQL schedules cover deactivation versus transfer/reassignment/finalization,
  simultaneous reassignments and administrator revocation. A successful transfer permits subsequent
  deactivation while preserving structural ownership.
- Browser tests cover independent User and Workspace management, inactive-owner presentation,
  explicit access-grant confirmation, conflict recovery and narrow layouts.

Keep the existing database initialization, doctor, schema parity, import contracts, generated API,
localization and frontend bundle checks.
