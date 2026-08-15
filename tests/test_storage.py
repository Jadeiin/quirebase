from io import BytesIO

import pytest

from quirebase.core.config import Settings
from quirebase.core.storage import LocalObjectStore


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
