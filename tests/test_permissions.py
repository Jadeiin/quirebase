import pytest

from quirebase.access.items import can_read_item
from quirebase.models import Item, Project, ProjectItem, ProjectMember, User


@pytest.mark.anyio
async def test_item_access_is_owner_or_project_membership(async_db):
    db = async_db
    owner = User(username="owner", password_hash="x")
    member = User(username="member", password_hash="x")
    outsider = User(username="outsider", password_hash="x")
    db.add_all([owner, member, outsider])
    await db.flush()
    item = Item(title="Paper", created_by=owner.id)
    project = Project(name="Lab", created_by=owner.id)
    db.add_all([item, project])
    await db.flush()
    db.add_all([
        ProjectItem(project_id=project.id, item_id=item.id),
        ProjectMember(project_id=project.id, user_id=member.id, role="viewer"),
    ])
    await db.commit()

    assert await can_read_item(db, owner, item.id)
    assert await can_read_item(db, member, item.id)
    assert not await can_read_item(db, outsider, item.id)
