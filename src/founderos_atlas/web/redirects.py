"""One fail-closed policy for every user-controlled redirect target.

PR-164.1: the implementation moved to the package-neutral
``founderos_atlas.redirects`` so that non-web consumers (notifications,
and through it the OIR capability bootstrap) can use it WITHOUT pulling
the whole web layer into their import closure. This module re-exports
it for the web package's existing importers.
"""

from __future__ import annotations

from founderos_atlas.redirects import safe_redirect_target

__all__ = ["safe_redirect_target"]
