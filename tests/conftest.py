"""Session-wide test guards.

The credential-store override itself is applied in ``tests/__init__.py``
(package import time — early enough for a module that resolves a
provider while being imported, and effective under ``unittest`` as well
as ``pytest``). This module owns the two things a fixture can do that an
import cannot: RESTORE the operator's original setting when the session
ends, and ASSERT that the guard is actually in force.
"""

from __future__ import annotations

import os

import pytest

from tests import (
    CREDENTIAL_PROVIDER_ENV,
    ORIGINAL_CREDENTIAL_PROVIDER,
    TEST_CREDENTIAL_PROVIDER,
)


@pytest.fixture(scope="session", autouse=True)
def isolate_credential_store():
    """Keep the whole session out of the developer's real OS keyring.

    Atlas's ``resolve_credential_provider()`` defaults to
    ``KeyringCredentialProvider`` (service ``founderos-atlas``). Any test
    that builds a ``ProfileService`` or an app without injecting a
    provider would otherwise write real secrets — profile passwords,
    credential-set entries, AI API keys — into the machine's keyring and
    leave them there after the run.

    Tests that deliberately exercise a specific provider construct it
    directly (``KeyringCredentialProvider()``,
    ``EncryptedFileCredentialProvider(...)``) rather than going through
    the factory, so they are unaffected by this override.
    """

    os.environ[CREDENTIAL_PROVIDER_ENV] = TEST_CREDENTIAL_PROVIDER

    from founderos_atlas.workspace.credentials import (
        InMemoryCredentialProvider,
        resolve_credential_provider,
    )

    # Fail loudly rather than let a run quietly reach the real keyring.
    resolved = resolve_credential_provider()
    assert isinstance(resolved, InMemoryCredentialProvider), (
        "credential isolation is not in force: "
        f"{type(resolved).__name__} would persist secrets outside the test "
        "run — check tests/__init__.py"
    )

    yield

    if ORIGINAL_CREDENTIAL_PROVIDER is None:
        os.environ.pop(CREDENTIAL_PROVIDER_ENV, None)
    else:
        os.environ[CREDENTIAL_PROVIDER_ENV] = ORIGINAL_CREDENTIAL_PROVIDER
