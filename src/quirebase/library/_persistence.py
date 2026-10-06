"""Library-owned repositories shared by its commands and read models."""

from quirebase.core.persistence import Repository, Service
from quirebase.models import Author, ImportBatch, Item, ItemAuthor


class ItemRepository(Repository[Item]):
    model_type = Item


class ItemService(Service[Item]):
    repository_type = ItemRepository


class ImportBatchRepository(Repository[ImportBatch]):
    model_type = ImportBatch


class ImportBatchService(Service[ImportBatch]):
    repository_type = ImportBatchRepository


class AuthorRepository(Repository[Author]):
    model_type = Author


class ItemAuthorRepository(Repository[ItemAuthor]):
    model_type = ItemAuthor
