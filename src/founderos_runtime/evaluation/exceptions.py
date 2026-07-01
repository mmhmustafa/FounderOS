"""Typed deterministic Evaluation failures."""


class EvaluationError(Exception):
    """Base exception for Evaluation contract or runner failures."""


class EvaluationConfigurationError(EvaluationError):
    """A rule, schema, custom handler, or score threshold is invalid."""


class EvaluationRequestError(EvaluationError):
    """An EvaluationRequest or result contract is invalid."""


class EvaluationExecutionError(EvaluationError):
    """A custom rule failed to execute or returned an invalid result."""
