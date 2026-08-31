import contextlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier, BrokenBarrierError

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from quirebase.core.config import Settings
from quirebase.core.storage import LocalObjectStore
from quirebase.documents.revisions import create_attachment, delete_unreferenced_objects
from quirebase.models import Attachment, AttachmentRole, Item, User


def test_content_addressed_pdf_storage_is_idempotent(tmp_path):
    store = LocalObjectStore(Settings(data_dir=tmp_path))
    content = b"%PDF-1.4\nminimal"
    first = store.put_pdf(BytesIO(content), 100)
    second = store.put_pdf(BytesIO(content), 100)

    assert first == second
    assert store.path(first[0]).read_bytes() == content


def test_storage_rejects_non_pdf_and_oversize(tmp_path):
    store = LocalObjectStore(Settings(data_dir=tmp_path))
    with pytest.raises(ValueError, match="not a PDF"):
        store.put_pdf(BytesIO(b"hello"), 100)
    with pytest.raises(ValueError, match="size limit"):
        store.put_pdf(BytesIO(b"%PDF-" + b"x" * 20), 10)


def test_staged_object_cleanup_does_not_leave_per_object_directories(tmp_path):
    store = LocalObjectStore(Settings(data_dir=tmp_path))
    key, _digest, _size, lease = store.put_staged_pdf(
        BytesIO(b"%PDF-1.4\nminimal"),
        100,
    )

    lease.release()
    store.delete(key)

    assert not store.path(key).parent.exists()
    assert not list(store.settings.object_dir.rglob("leases"))
    assert len([path for path in store.settings.object_dir.rglob("*") if path.is_dir()]) <= 1


def test_database_fixture_isolates_the_default_object_store(db, tmp_path):
    store = LocalObjectStore()

    assert store.settings.data_dir == tmp_path / "data"


def test_attachment_upload_lease_prevents_concurrent_cleanup(db, monkeypatch):
    user = User(username="attachment-uploader", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(title="Attachment lease", created_by=user.id)
    db.add(item)
    db.commit()
    original_commit = db.commit
    store = LocalObjectStore()

    def commit_while_cleanup_runs():
        object_path = next(store.settings.object_dir.glob("*/*/*.bin"))
        object_key = str(object_path.relative_to(store.settings.object_dir))
        with Session(db.bind) as concurrent_db:
            deleted = delete_unreferenced_objects(concurrent_db, (object_key,))
        assert deleted == ()
        assert object_path.exists()
        original_commit()

    monkeypatch.setattr(db, "commit", commit_while_cleanup_runs)

    attachment = create_attachment(
        db,
        user,
        item.id,
        BytesIO(b"same bytes as a concurrently deleted attachment"),
        "supplement.txt",
        "text/plain",
    )

    assert store.path(attachment.object_key).exists()


def test_concurrent_graphical_abstract_uploads_are_serialized(db):
    user = User(username="concurrent-attachment-uploader", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(title="Concurrent graphical abstract", created_by=user.id)
    db.add(item)
    db.commit()

    current_role_reads = Barrier(2)

    class SynchronizedRoleReadSession(Session):
        def scalar(self, statement, *args, **kwargs):
            if (
                getattr(statement, "is_select", False)
                and Attachment.__table__ in statement.get_final_froms()
            ):
                with contextlib.suppress(BrokenBarrierError):
                    current_role_reads.wait(timeout=0.25)
            return super().scalar(statement, *args, **kwargs)

    factory = sessionmaker(
        db.bind,
        class_=SynchronizedRoleReadSession,
        expire_on_commit=False,
    )

    def upload(index: int) -> str:
        with factory() as worker_db:
            worker_user = worker_db.get(User, user.id)
            assert worker_user is not None
            attachment = create_attachment(
                worker_db,
                worker_user,
                item.id,
                BytesIO(b"\x89PNG\r\n\x1a\n" + bytes([index])),
                f"abstract-{index}.png",
                "image/png",
                role=AttachmentRole.graphical_abstract,
            )
            return attachment.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        attachment_ids = tuple(executor.map(upload, range(2)))

    attachments = db.scalars(
        select(Attachment).where(Attachment.id.in_(attachment_ids))
    ).all()
    assert len(attachments) == 2
    assert sum(record.role == AttachmentRole.graphical_abstract for record in attachments) == 1
