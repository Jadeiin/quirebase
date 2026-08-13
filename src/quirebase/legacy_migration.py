from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AuditEvent,
    DiscussionMessage,
    FileRevision,
    Item,
    ItemTag,
    Job,
    LegacyImportMap,
    Project,
    ProjectItem,
    ProjectMember,
    Tag,
    User,
)
from .pdf_service import job_payload, validate_pdf_container
from .search import search_index
from .storage import LocalObjectStore


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    required = {
        "items", "primary_titles", "authors", "items_authors", "keywords", "items_keywords", "uids", "tags", "items_tags"
    }
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = required - tables
    if missing:
        connection.close()
        raise ValueError(f"legacy database is missing tables: {', '.join(sorted(missing))}")
    return connection


def _legacy_pdf(data_dir: Path, item_id: int) -> Path:
    basename = str(item_id).zfill(9)
    return data_dir / "pdfs" / basename[:3] / basename[3:6] / f"{basename}.pdf"


def migrate_legacy(
    db: Session,
    legacy_database: Path,
    legacy_data_dir: Path,
    owner: User,
    *,
    commit: bool = False,
) -> dict:
    source = hashlib.sha256(legacy_database.read_bytes()).hexdigest()
    report: dict[str, object] = {
        "source_fingerprint": source,
        "items": 0,
        "pdfs": 0,
        "tags": 0,
        "projects": 0,
        "discussions": 0,
        "skipped": [],
        "warnings": ["Legacy accounts and password hashes are not imported; ownership is assigned to the selected account."],
        "committed": commit,
    }
    connection = _connect_read_only(legacy_database)
    try:
        rows = connection.execute(
            """
            SELECT i.*, pt.primary_title,
              (SELECT group_concat(name, '; ') FROM (
                SELECT trim(coalesce(a.last_name, '') || CASE WHEN a.first_name IS NULL OR a.first_name='' THEN '' ELSE ', ' || a.first_name END) name
                FROM items_authors ia JOIN authors a ON a.id=ia.author_id WHERE ia.item_id=i.id ORDER BY ia.position
              )) authors_text,
              (SELECT group_concat(k.keyword, '; ') FROM items_keywords ik JOIN keywords k ON k.id=ik.keyword_id WHERE ik.item_id=i.id) keywords_text,
              (SELECT u.uid FROM uids u WHERE u.item_id=i.id AND lower(u.uid_type)='doi' LIMIT 1) doi_text
            FROM items i LEFT JOIN primary_titles pt ON pt.id=i.primary_title_id ORDER BY i.id
            """
        ).fetchall()
        report["items"] = len(rows)
        if not commit:
            report["pdfs"] = sum(_legacy_pdf(legacy_data_dir, row["id"]).is_file() for row in rows)
            return report
        item_map: dict[int, str] = {}
        newly_imported: set[int] = set()
        for row in rows:
            existing = db.scalar(
                select(LegacyImportMap).where(
                    LegacyImportMap.source_fingerprint == source,
                    LegacyImportMap.entity_type == "item",
                    LegacyImportMap.legacy_id == str(row["id"]),
                )
            )
            if existing:
                item_map[row["id"]] = existing.new_id
                cast_skipped = report["skipped"]
                cast_skipped.append(f"item {row['id']}: already imported")
                continue
            item = Item(
                title=row["title"], abstract=row["abstract"], publication_date=row["publication_date"],
                publication_title=row["primary_title"], authors=row["authors_text"], keywords=row["keywords_text"],
                doi=row["doi_text"], reference_type=row["reference_type"], created_by=owner.id,
            )
            db.add(item)
            db.flush()
            item_map[row["id"]] = item.id
            newly_imported.add(row["id"])
            db.add(LegacyImportMap(source_fingerprint=source, entity_type="item", legacy_id=str(row["id"]), new_id=item.id))
            pdf_path = _legacy_pdf(legacy_data_dir, row["id"])
            if pdf_path.is_file():
                try:
                    validate_pdf_container(pdf_path)
                    with pdf_path.open("rb") as stream:
                        key, digest, size = LocalObjectStore().put_pdf(stream, 2**63 - 1)
                    revision = FileRevision(item_id=item.id, object_key=key, sha256=digest, size=size, original_name=pdf_path.name, created_by=owner.id)
                    db.add(revision)
                    db.flush()
                    db.add(Job(kind="pdf.inspect", payload=job_payload(revision_id=revision.id), idempotency_key=f"pdf.inspect:{revision.id}", owner_id=owner.id))
                    report["pdfs"] += 1
                except ValueError as error:
                    report["skipped"].append(f"PDF for item {row['id']}: {error}")
            search_index(db).index_item(db, item.id)
        for row in connection.execute("SELECT it.item_id, t.tag FROM items_tags it JOIN tags t ON t.id=it.tag_id"):
            if row["item_id"] not in item_map:
                continue
            tag = db.scalar(select(Tag).where(Tag.name == row["tag"]))
            if tag is None:
                tag = Tag(name=row["tag"], created_by=owner.id)
                db.add(tag)
                db.flush()
                report["tags"] += 1
            if db.get(ItemTag, (item_map[row["item_id"]], tag.id)) is None:
                db.add(ItemTag(item_id=item_map[row["item_id"]], tag_id=tag.id))
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "projects" in tables:
            for row in connection.execute("SELECT id, project FROM projects"):
                existing = db.scalar(
                    select(LegacyImportMap).where(
                        LegacyImportMap.source_fingerprint == source,
                        LegacyImportMap.entity_type == "project",
                        LegacyImportMap.legacy_id == str(row["id"]),
                    )
                )
                if existing:
                    continue
                project = Project(name=row["project"], created_by=owner.id)
                db.add(project)
                db.flush()
                db.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
                db.add(LegacyImportMap(source_fingerprint=source, entity_type="project", legacy_id=str(row["id"]), new_id=project.id))
                for linked in connection.execute("SELECT item_id FROM projects_items WHERE project_id=?", (row["id"],)):
                    if linked["item_id"] in item_map:
                        db.add(ProjectItem(project_id=project.id, item_id=item_map[linked["item_id"]]))
                report["projects"] += 1
        if "item_discussions" in tables:
            for row in connection.execute("SELECT item_id, message FROM item_discussions ORDER BY id"):
                if row["item_id"] in newly_imported and row["message"].strip():
                    db.add(DiscussionMessage(item_id=item_map[row["item_id"]], author_id=owner.id, body=row["message"].strip()))
                    report["discussions"] += 1
        for item_id in item_map.values():
            search_index(db).index_item(db, item_id)
        db.add(AuditEvent(actor_id=owner.id, action="legacy.import", target_type="migration", target_id=None, detail=json.dumps(report)))
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        connection.close()
