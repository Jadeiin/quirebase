"""Generate Inquiro's Work types from the locked, external Commonmeta schema."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from commonmeta_schema import schema_path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "packages/inquiro/src/inquiro/work_models.py"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the committed generated model")
    args = parser.parse_args()
    schema = json.loads(schema_path("1.0").read_text(encoding="utf-8"))
    # Select the Work contract and exactly its referenced official definitions.
    # No field definitions, constraints, or mappings are maintained locally.
    required = set()

    def include(value):
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/$defs/"):
                name = reference.removeprefix("#/$defs/")
                if name not in required:
                    required.add(name)
                    include(schema["$defs"][name])
            for child in value.values():
                include(child)
        elif isinstance(value, list):
            for child in value:
                include(child)

    include({"$ref": "#/$defs/work"})
    contract = {
        "$schema": schema["$schema"],
        "$id": schema["$id"],
        "$ref": "#/$defs/work",
        "$defs": {
            name: definition for name, definition in schema["$defs"].items() if name in required
        },
    }
    # Keep the check output below the package so codegen's Ruff formatter finds
    # the same repository configuration as normal generation.
    with tempfile.TemporaryDirectory(
        prefix=".commonmeta-", dir=OUTPUT.parent if args.check else None
    ) as temporary:
        source = Path(temporary) / "commonmeta_v1.0.json"
        output = Path(temporary) / "work_models.py" if args.check else OUTPUT
        source.write_text(json.dumps(contract), encoding="utf-8")
        subprocess.run(
            [
                "datamodel-codegen",
                "--input",
                str(source),
                "--input-file-type",
                "jsonschema",
                "--output",
                str(output),
                "--output-model-type",
                "pydantic_v2.BaseModel",
                "--class-name",
                "Work",
                "--target-python-version",
                "3.12",
                "--target-pydantic-version",
                "2.12",
                "--use-annotated",
                "--use-standard-collections",
                "--use-union-operator",
                "--enum-field-as-literal",
                "all",
                "--extra-fields",
                "forbid",
                "--strict-types",
                "str",
                "int",
                "float",
                "bool",
                "--type-mappings",
                "uri=string",
                "--collapse-root-models",
                "--reuse-model",
                "--collapse-reuse-models",
                "--base-class-map",
                '{"Work":"inquiro.work.WorkContract"}',
                "--disable-timestamp",
                "--formatters",
                "ruff-check",
                "ruff-format",
            ],
            check=True,
        )
        # Codegen formats stdin without a filename. Normalize with the real
        # package filename so Ruff classifies Inquiro imports consistently.
        for arguments in (["check", "--fix"], ["format"]):
            formatted = subprocess.run(
                ["ruff", *arguments, "--stdin-filename", str(OUTPUT), "-"],
                input=output.read_text(encoding="utf-8"),
                text=True,
                capture_output=True,
                cwd=ROOT,
                check=True,
            )
            output.write_text(formatted.stdout, encoding="utf-8")
        if args.check and output.read_bytes() != OUTPUT.read_bytes():
            parser.exit(1, "Commonmeta models differ; run scripts/generate-commonmeta-models.py\n")


if __name__ == "__main__":
    main()
