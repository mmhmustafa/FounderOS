"""Runtime foundation error types."""


class RuntimeFoundationError(Exception):
    """Base class for runtime foundation failures."""


class ContractValidationError(RuntimeFoundationError):
    """A record does not conform to its JSON Schema contract."""


class DuplicateRecordError(RuntimeFoundationError):
    """A repository already contains the requested immutable identity."""


class RecordNotFoundError(RuntimeFoundationError):
    """A requested record does not exist."""


class ConflictError(RuntimeFoundationError):
    """An optimistic revision or ordered-sequence check failed."""


class ReferenceIntegrityError(RuntimeFoundationError):
    """A typed reference cannot be resolved exactly."""


class StateMutationError(RuntimeFoundationError):
    """A caller attempted to bypass the State Machine boundary."""


class VerticalSliceError(RuntimeFoundationError):
    """The Founder Setup vertical slice cannot perform the requested operation."""


class ApprovalRequiredError(VerticalSliceError):
    """A current human approval is required before Founder Setup can complete."""
