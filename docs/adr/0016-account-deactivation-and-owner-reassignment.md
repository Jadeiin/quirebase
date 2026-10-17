---
status: accepted
---

# Separate User deactivation from Workspace ownership

User provisioning creates an ordinary Workspace whose owner previously could not be deactivated,
so an instance administrator could not immediately disable a newly created or compromised User.
Quirebase retains the unique current owner membership while allowing its User to be inactive,
and provides an explicit, reason-required instance governance operation to reassign ownership.
Account activity controls effective authority; ownership records the current governance assignment.

This revises ADR 0013's requirement that every surviving Workspace have an owner with an active
account. The owner membership remains active and non-terminated, and every effective grant still
requires an active User. New ownership assignments require an active receiving User.

The operation, authorization, lifecycle rules, concurrency contract and verification are
specified in [Account deactivation and owner reassignment](../architecture/account-deactivation-and-owner-reassignment.md).

## Considered options

- Requiring handover before deactivation leaves security containment dependent on a successor.
- Automatically assigning every disabled User's Workspaces to the acting administrator changes
  content access as a side effect of disabling credentials.
- Special rules for provisioned Workspaces conflict with their ordinary Workspace semantics and
  become ambiguous after those Workspaces gain content or members.

## Consequences

An inactive owner is a valid governance assignment and an administrator-visible recovery concern.
Other active members retain their existing authority. The explicit reassignment operation can admit
or reactivate its selected receiving User as owner; it records that access change and its reason in
Audit. This grants no implicit content access to the administrator executing the operation.
