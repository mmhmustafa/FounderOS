"""The unified Atlas mutation audit.

One model for every operator mutation: who, when, in which scope, what
operation, on what subject, from what to what, why, from which surface,
and under which correlation id. New mutation features (policy
exceptions, assignments, change acknowledgements, annotations) write
HERE; the pre-existing site-override and peer-identity audit trails are
read through adapters and stay untouched in their own files, because
their undo semantics replay those files verbatim.

Secrets never enter an audit event: callers pass references (credential
ref, device id), never values, and the model refuses obviously secret
field names as a second line of defence.
"""

from .models import AuditEvent, redact_payload
from .log import AuditLog
from .annotations import AnnotationStore
from .sources import export_rows, unified_audit_events

__all__ = [
    "AnnotationStore",
    "AuditEvent",
    "AuditLog",
    "export_rows",
    "redact_payload",
    "unified_audit_events",
]
