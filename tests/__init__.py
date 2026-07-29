"""FounderOS runtime foundation tests.

Credential isolation is set up HERE, at package-import time, because it
must hold before any test module imports Atlas code — and because
importing this package is the one thing that happens under every
runner, ``pytest`` and ``python -m unittest`` alike.
``resolve_credential_provider()`` defaults to the OS keyring, so
without this a test that saves a profile password, a credential-set
entry, or an AI API key writes a real secret into the developer's own
keyring and leaves it there.

``tests/conftest.py`` holds the matching session fixture, which
restores the operator's original setting when the run ends and asserts
that this guard actually took effect. Neither file is redundant: this
one guarantees COVERAGE, that one guarantees RESTORATION.
"""

import os

CREDENTIAL_PROVIDER_ENV = "ATLAS_CREDENTIAL_PROVIDER"
TEST_CREDENTIAL_PROVIDER = "memory"

# The operator's own setting, captured before we override it so the
# conftest fixture can put it back exactly as it was.
ORIGINAL_CREDENTIAL_PROVIDER = os.environ.get(CREDENTIAL_PROVIDER_ENV)

# "memory" is Atlas's own documented tests-only provider: it keeps
# secrets in process and never persists (see workspace/credentials.py).
os.environ[CREDENTIAL_PROVIDER_ENV] = TEST_CREDENTIAL_PROVIDER
