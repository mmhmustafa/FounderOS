"""Local Atlas web GUI shell (alpha).

A single-user, local-only browser interface over the existing Atlas backend
services. Not a production or multi-user web deployment.
"""

from .app import DEFAULT_HOST, DEFAULT_PORT, create_app

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "create_app"]
