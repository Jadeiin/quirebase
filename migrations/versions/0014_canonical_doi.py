"""Make Item.doi the sole canonical DOI representation."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0014_canonical_doi"
down_revision = "0013_domain_state_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    items = sa.table(
        "items",
        sa.column("id", sa.String),
        sa.column("identifiers", sa.Text),
    )
    rows = bind.execute(sa.select(items.c.id, items.c.identifiers)).fetchall()
    for item_id, raw in rows:
        if not raw:
            continue
        try:
            values = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(values, dict):
            continue
        doi_keys = [key for key in values if str(key).casefold() == "doi"]
        if not doi_keys:
            continue
        for key in doi_keys:
            values.pop(key, None)
        bind.execute(
            items
            .update()
            .where(items.c.id == item_id)
            .values(identifiers=json.dumps(values, ensure_ascii=False) if values else None)
        )

    identifiers = sa.table(
        "item_identifiers",
        sa.column("provider", sa.String),
    )
    bind.execute(identifiers.delete().where(sa.func.lower(identifiers.c.provider) == "doi"))


def downgrade() -> None:
    # DOI values remain available in items.doi; recreating duplicate rows would
    # reintroduce the ambiguity this migration removes.
    pass
