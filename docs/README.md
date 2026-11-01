# Engineering documentation

Public task guides and the help center live in the independent [documentation site](../site/README.md).
Keep domain definitions, design decisions, implementation contracts, and agent guidance here or in
their existing root files; public developer guides link to them rather than turning them into user
manuals.

- [Glossary](../GLOSSARY.md): canonical domain terms and relationships.
- [ADRs](adr/): architecture decisions and their status.
- [Architecture contracts](architecture/modules.md): module ownership and detailed behavior.
- [Deployment and operations](DEPLOYMENT.md): detailed operator contracts and upgrade transitions.
- [Import and Discovery](METADATA_LOOKUP.md): existing workflow reference.
- [Testing](TESTING.md): verification commands and test environments.
- [Agent guidance](agents/domain.md): repository conventions.
- [Research](research/): investigations and evaluated options.

Update the public guide when a user task changes, and update the relevant engineering contract when
its invariants change. Neither replaces the other. API route and field reference is generated from
FastAPI during the site build.
