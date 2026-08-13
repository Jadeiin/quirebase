from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "tests" / "oa_corpus.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(destination: Path) -> None:
    corpus = json.loads(MANIFEST.read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    for paper in corpus["papers"]:
        target = destination / f"{paper['id']}.pdf"
        if target.is_file() and sha256(target) == paper["sha256"]:
            print(f"verified {target.name}")
            continue
        temporary = target.with_suffix(".pdf.part")
        request = urllib.request.Request(
            paper["url"], headers={"User-Agent": "Quirebase-OA-PDF-tests/0.1"}
        )
        try:
            with (
                urllib.request.urlopen(request, timeout=120) as source,
                temporary.open("wb") as output,
            ):
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            if temporary.stat().st_size != paper["bytes"]:
                raise ValueError(f"size mismatch for {paper['id']}")
            actual = sha256(temporary)
            if actual != paper["sha256"]:
                raise ValueError(f"SHA-256 mismatch for {paper['id']}: {actual}")
            os.replace(temporary, target)
            print(f"downloaded {target.name}")
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download and verify the licensed OA PDF corpus")
    parser.add_argument("destination", nargs="?", type=Path, default=ROOT / ".cache" / "oa-pdfs")
    download(parser.parse_args().destination.resolve())
