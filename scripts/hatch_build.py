from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Include the standalone frontend in release wheels, but not editable installs."""

    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel" or version == "editable":
            return

        frontend = Path(self.root) / "frontend" / "build"
        if not (frontend / "index.html").is_file():
            raise RuntimeError(
                "frontend build not found; run `bun run --cwd frontend build` before "
                "building a wheel"
            )
        build_data["force_include"][str(frontend)] = "quirebase_frontend"
