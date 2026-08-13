from quirebase.models import Item, Project, ProjectItem, ProjectMember, User
from quirebase.permissions import can_read_item


def test_item_access_is_owner_or_project_membership(db):
    owner = User(username="owner", password_hash="x")
    member = User(username="member", password_hash="x")
    outsider = User(username="outsider", password_hash="x")
    db.add_all([owner, member, outsider])
    db.flush()
    item = Item(title="Paper", created_by=owner.id)
    project = Project(name="Lab", created_by=owner.id)
    db.add_all([item, project])
    db.flush()
    db.add_all([
        ProjectItem(project_id=project.id, item_id=item.id),
        ProjectMember(project_id=project.id, user_id=member.id, role="viewer"),
    ])
    db.commit()

    assert can_read_item(db, owner, item.id)
    assert can_read_item(db, member, item.id)
    assert not can_read_item(db, outsider, item.id)
