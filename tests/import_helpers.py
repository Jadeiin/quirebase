def pdf_import_batch_data(pending_records: list[dict]) -> dict:
    from uuid import uuid4

    from advanced_alchemy.types import FileObject

    files = []
    records = []
    for index, pending in enumerate(pending_records, start=1):
        pdf = pending["_pdf"]
        source_id = pending.setdefault("_source_id", str(uuid4()))
        files.append(
            FileObject(
                backend="documents",
                filename=pdf["object_key"],
                content_type="application/pdf",
                size=pdf.get("size"),
                metadata={
                    "row": pending.get("_row", index),
                    "source_id": source_id,
                    "original_name": pdf.get("original_name", "source.pdf"),
                },
            )
        )
        records.append({key: value for key, value in pending.items() if key != "_pdf"})
    return {"staged_files": files, "records": records}
