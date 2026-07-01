"""Read-only semantic Workspace assembled from validated manifests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from founderos_runtime.manifest_loader import ManifestLoader

from .discovery import DiscoveredManifest, discover_manifests
from .exceptions import (
    WorkspaceCompatibilityError,
    WorkspaceDependencyCycleError,
    WorkspaceDuplicateIdError,
    WorkspaceItemNotFoundError,
    WorkspaceMissingReferenceError,
)


SUPPORTED_RUNTIME_VERSION = "0.1.0"
_CORE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_VERSION_RANGE = re.compile(
    r"^>=(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*) "
    r"<(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _CORE_VERSION.fullmatch(version)
    if match is None:
        raise WorkspaceCompatibilityError(
            f"runtime version must use core Semantic Versioning X.Y.Z: {version!r}"
        )
    return tuple(int(part) for part in match.groups())


def _range_bounds(version_range: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    match = _VERSION_RANGE.fullmatch(version_range)
    if match is None:  # App schema normally prevents this; retain a defensive boundary.
        raise WorkspaceCompatibilityError(f"unsupported version range: {version_range!r}")
    values = tuple(int(part) for part in match.groups())
    return values[:3], values[3:]


def _in_range(version: str, version_range: str) -> bool:
    current = _version_tuple(version)
    minimum, maximum = _range_bounds(version_range)
    return minimum <= current < maximum


class Workspace:
    """Immutable-by-interface snapshot of validated App, Workflow, and Agent definitions."""

    def __init__(
        self,
        project_root: Path,
        runtime_version: str,
        apps: dict[str, dict[str, Any]],
        workflows: dict[str, dict[str, Any]],
        agents: dict[str, dict[str, Any]],
    ) -> None:
        self._project_root = project_root
        self._runtime_version = runtime_version
        self._apps = deepcopy(apps)
        self._workflows = deepcopy(workflows)
        self._agents = deepcopy(agents)

    @classmethod
    def load(
        cls,
        project_root: str | Path,
        *,
        runtime_version: str = SUPPORTED_RUNTIME_VERSION,
        manifest_loader: ManifestLoader | None = None,
    ) -> "Workspace":
        root = Path(project_root)
        runtime = _version_tuple(runtime_version)
        loader = manifest_loader or ManifestLoader()
        manifests = discover_manifests(root, loader)
        builder = _WorkspaceBuilder(root.resolve(), runtime_version, runtime, manifests)
        return builder.build()

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def runtime_version(self) -> str:
        return self._runtime_version

    def apps(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(self._apps[key]) for key in sorted(self._apps))

    def workflows(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(self._workflows[key]) for key in sorted(self._workflows))

    def agents(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(self._agents[key]) for key in sorted(self._agents))

    def get_app(self, identifier: str) -> dict[str, Any]:
        return self._get("app", identifier, self._apps)

    def get_workflow(self, identifier: str) -> dict[str, Any]:
        return self._get("workflow", identifier, self._workflows)

    def get_agent(self, identifier: str) -> dict[str, Any]:
        return self._get("agent", identifier, self._agents)

    @staticmethod
    def _get(kind: str, identifier: str, items: dict[str, dict[str, Any]]) -> dict[str, Any]:
        try:
            return deepcopy(items[identifier])
        except KeyError as error:
            raise WorkspaceItemNotFoundError(f"{kind} id not found: {identifier!r}") from error

    def summary(self) -> dict[str, Any]:
        return {
            "project_root": str(self._project_root),
            "runtime_version": self._runtime_version,
            "counts": {
                "apps": len(self._apps),
                "workflows": len(self._workflows),
                "agents": len(self._agents),
            },
            "apps": sorted(self._apps),
            "workflows": sorted(self._workflows),
            "agents": sorted(self._agents),
        }


class _WorkspaceBuilder:
    def __init__(
        self,
        root: Path,
        runtime_version: str,
        runtime: tuple[int, int, int],
        manifests: tuple[DiscoveredManifest, ...],
    ) -> None:
        self.root = root
        self.runtime_version = runtime_version
        self.runtime = runtime
        self.manifests = manifests
        self.items: dict[str, dict[str, dict[str, Any]]] = {
            "app": {},
            "workflow": {},
            "agent": {},
        }
        self.paths: dict[str, dict[str, Path]] = {"app": {}, "workflow": {}, "agent": {}}

    def build(self) -> Workspace:
        self._index()
        self._validate_runtime_compatibility()
        self._validate_app_references()
        self._validate_workflow_references()
        self._validate_dependency_cycles()
        return Workspace(
            self.root,
            self.runtime_version,
            self.items["app"],
            self.items["workflow"],
            self.items["agent"],
        )

    def _index(self) -> None:
        for discovered in self.manifests:
            identifier = discovered.data["id"]
            existing = self.paths[discovered.kind].get(identifier)
            if existing is not None:
                raise WorkspaceDuplicateIdError(
                    discovered.kind,
                    identifier,
                    str(existing),
                    str(discovered.path),
                )
            self.items[discovered.kind][identifier] = discovered.data
            self.paths[discovered.kind][identifier] = discovered.path

    def _validate_runtime_compatibility(self) -> None:
        for identifier in sorted(self.items["app"]):
            app = self.items["app"][identifier]
            if not _in_range(self.runtime_version, app["compatible_runtime"]):
                raise WorkspaceCompatibilityError(
                    f"app {identifier!r} requires runtime {app['compatible_runtime']}; "
                    f"workspace runtime is {self.runtime_version}"
                )
        for identifier in sorted(self.items["workflow"]):
            workflow = self.items["workflow"][identifier]
            compatibility = workflow["compatibility"]
            minimum = _version_tuple(compatibility["minimum_kernel_contract"])
            maximum = _version_tuple(compatibility["maximum_kernel_contract_exclusive"])
            if not minimum <= self.runtime < maximum:
                raise WorkspaceCompatibilityError(
                    f"workflow {identifier!r} requires kernel >="
                    f"{compatibility['minimum_kernel_contract']} <"
                    f"{compatibility['maximum_kernel_contract_exclusive']}; "
                    f"workspace runtime is {self.runtime_version}"
                )

    def _validate_app_references(self) -> None:
        for app_id in sorted(self.items["app"]):
            app = self.items["app"][app_id]
            self._require_exact_references(app_id, "app", "workflow", app["workflows"])
            self._require_exact_references(app_id, "app", "agent", app["agents"])
            for dependency in sorted(app["dependencies"], key=lambda item: item["id"]):
                target = self.items["app"].get(dependency["id"])
                if target is None:
                    if dependency["optional"]:
                        continue
                    raise WorkspaceMissingReferenceError(
                        f"app {app_id!r} requires missing app dependency {dependency['id']!r}"
                    )
                if not _in_range(target["version"], dependency["version_range"]):
                    raise WorkspaceCompatibilityError(
                        f"app {app_id!r} requires dependency {dependency['id']!r} "
                        f"{dependency['version_range']}; found {target['version']}"
                    )

    def _validate_workflow_references(self) -> None:
        for workflow_id in sorted(self.items["workflow"]):
            workflow = self.items["workflow"][workflow_id]
            references = workflow["required_agents"] + workflow["optional_agents"]
            self._require_exact_references(workflow_id, "workflow", "agent", references)

    def _require_exact_references(
        self,
        source_id: str,
        source_kind: str,
        target_kind: str,
        references: list[dict[str, Any]],
    ) -> None:
        targets = self.items[target_kind]
        for reference in sorted(references, key=lambda item: (item["id"], item["version"])):
            target = targets.get(reference["id"])
            if target is None:
                raise WorkspaceMissingReferenceError(
                    f"{source_kind} {source_id!r} references missing {target_kind} "
                    f"{reference['id']!r} version {reference['version']}"
                )
            if target["version"] != reference["version"]:
                raise WorkspaceMissingReferenceError(
                    f"{source_kind} {source_id!r} references {target_kind} {reference['id']!r} "
                    f"version {reference['version']}; found {target['version']}"
                )

    def _validate_dependency_cycles(self) -> None:
        graph = {
            app_id: sorted(
                dependency["id"]
                for dependency in app["dependencies"]
                if dependency["id"] in self.items["app"]
            )
            for app_id, app in self.items["app"].items()
        }
        visited: set[str] = set()
        active: list[str] = []

        def visit(app_id: str) -> None:
            if app_id in active:
                start = active.index(app_id)
                cycle = active[start:] + [app_id]
                raise WorkspaceDependencyCycleError(
                    f"circular app dependency: {' -> '.join(cycle)}"
                )
            if app_id in visited:
                return
            active.append(app_id)
            for dependency_id in graph[app_id]:
                visit(dependency_id)
            active.pop()
            visited.add(app_id)

        for app_id in sorted(graph):
            visit(app_id)
