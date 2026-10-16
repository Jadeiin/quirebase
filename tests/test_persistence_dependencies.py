"""Characterize pinned dependency behavior, independently of application safety."""

from __future__ import annotations

from advanced_alchemy.types import FileObject
from advanced_alchemy.types.file_object.backends.obstore import ObstoreBackend
from obstore.store import MemoryStore


def test_file_object_equality_omits_persisted_descriptor_metadata():
    backend = ObstoreBackend(key="documents", fs=MemoryStore())
    original = FileObject(
        backend=backend,
        filename="aa/bb/descriptor.pdf",
        size=10,
        metadata={"original_name": "original.pdf"},
    )
    changed = FileObject(
        backend=backend,
        filename="aa/bb/descriptor.pdf",
        size=10,
        metadata={"original_name": "renamed.pdf"},
    )
    assert original == changed
    assert original.to_dict() != changed.to_dict()
