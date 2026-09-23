from __future__ import annotations

from unittest.mock import AsyncMock

import pymupdf
import pytest
from inquiro import CandidatePage, CandidateRecord, Identifier
from sqlalchemy import func, select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.core.errors import PermissionDenied, WorkspaceMembershipRequired
from quirebase.library.discovery import DiscoveryClause, search_candidate_records
from quirebase.library.imports import stage_identifier_import_batch, stage_pdf_import_batch
from quirebase.models import ImportBatch, User, WorkspaceMember, WorkspaceMemberState, WorkspaceRole


async def _member(async_db):
    owner = User(username="io-owner", password_hash="unused")
    member = User(username="io-member", password_hash="unused")
    async_db.add_all([owner, member])
    await async_db.flush()
    await provision_initial_workspace(async_db, owner)
    await provision_initial_workspace(async_db, member)
    membership = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=member.id,
        role=WorkspaceRole.editor,
        invited_by=owner.id,
    )
    async_db.add(membership)
    await async_db.commit()
    return member, membership.id, fixture_workspace_id(owner)


@pytest.mark.anyio
async def test_identifier_import_rechecks_create_after_provider_io(
    async_db, async_session_factory, monkeypatch
):
    member, membership_id, workspace_id = await _member(async_db)

    async def lookup(_identifier, _provider, _settings):
        async with async_session_factory() as governor_db:
            membership = await governor_db.get(WorkspaceMember, membership_id)
            assert membership is not None
            membership.role = WorkspaceRole.viewer
            await governor_db.commit()
        return CandidateRecord(
            provider="crossref",
            identifier=Identifier("doi", "10.1000/revoked"),
            title="Revoked import",
        )

    monkeypatch.setattr("quirebase.library.imports.lookup_candidate", lookup)
    with pytest.raises(PermissionDenied):
        await stage_identifier_import_batch(async_db, member, workspace_id, "10.1000/revoked")
    assert await async_db.scalar(select(func.count()).select_from(ImportBatch)) == 0


@pytest.mark.anyio
async def test_pdf_import_rechecks_create_and_cleans_staged_object(
    async_db, async_session_factory, monkeypatch
):
    from quirebase.documents.revisions import stage_pdf

    member, membership_id, workspace_id = await _member(async_db)
    document = pymupdf.open()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()
    objects_before = set(get_settings().object_dir.rglob("*.pdf"))

    async def stage_then_revoke(db, source, filename, max_bytes):
        staged = await stage_pdf(db, source, filename, max_bytes)
        async with async_session_factory() as governor_db:
            membership = await governor_db.get(WorkspaceMember, membership_id)
            assert membership is not None
            membership.state = WorkspaceMemberState.suspended
            await governor_db.commit()
        return staged

    monkeypatch.setattr("quirebase.library.imports.stage_pdf", stage_then_revoke)
    with pytest.raises(WorkspaceMembershipRequired):
        await stage_pdf_import_batch(
            async_db, member, workspace_id, [(pdf_bytes, "revoked.pdf")], max_bytes=100_000
        )
    assert await async_db.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert set(get_settings().object_dir.rglob("*.pdf")) == objects_before


@pytest.mark.anyio
async def test_discovery_rechecks_membership_before_local_matching(
    async_db, async_session_factory, monkeypatch
):
    member, membership_id, workspace_id = await _member(async_db)

    async def search(_query, _settings):
        async with async_session_factory() as governor_db:
            membership = await governor_db.get(WorkspaceMember, membership_id)
            assert membership is not None
            membership.state = WorkspaceMemberState.suspended
            await governor_db.commit()
        candidate = CandidateRecord(
            provider="crossref",
            identifier=Identifier("doi", "10.1000/existing"),
            title="Candidate",
        )
        return CandidatePage("crossref", (candidate,), 1, 1, 10)

    match = AsyncMock()
    monkeypatch.setattr("quirebase.library.discovery.search_candidates", search)
    monkeypatch.setattr(
        "quirebase.library.discovery.get_matching_accessible_item_identifiers", match
    )
    with pytest.raises(WorkspaceMembershipRequired):
        await search_candidate_records(
            async_db,
            member,
            workspace_id,
            "crossref",
            (DiscoveryClause("title", "and", "candidate"),),
            settings=get_settings(),
        )
    match.assert_not_awaited()
