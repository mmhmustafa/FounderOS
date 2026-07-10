"""Persistent site catalog storage (``<workspace_root>/sites.json``)."""

from __future__ import annotations

import json
from pathlib import Path

from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError
from founderos_atlas.workspace.repository import default_workspace_root

from .models import SiteCatalog


SITES_FILENAME = "sites.json"


class SiteCatalogRepository:
    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._root = (
            Path(workspace_root) if workspace_root is not None else default_workspace_root()
        )

    @property
    def path(self) -> Path:
        return self._root / SITES_FILENAME

    def load(self) -> SiteCatalog:
        if not self.path.is_file():
            return SiteCatalog()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The site catalog {self.path} could not be read: {error}"
            ) from error
        return SiteCatalog.from_dict(raw)

    def save(self, catalog: SiteCatalog) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(catalog.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
