"""Server-verified confirmation for destructive operations.

A browser ``confirm()`` dialog is a courtesy, not a control — under a
strict CSP an inline handler never runs, and a hostile or scripted
client never shows a dialog at all. Every destructive route therefore
verifies confirmation ON THE SERVER:

1. The first POST (no token) does not destroy anything: it renders a
   confirmation page that names exactly what will happen, echoes the
   original form fields, and embeds a signed, path-bound, short-lived
   token.
2. Only a second POST carrying that valid token performs the action.

The token is signed with the app's secret key, bound to the request
path (a token minted for one deletion cannot authorize another), and
expires after ten minutes. JavaScript is not involved anywhere, so the
protection holds with scripts disabled, blocked, or bypassed.
"""

from __future__ import annotations

CONFIRM_TOKEN_FIELD = "_confirm_token"
CONFIRM_MAX_AGE_SECONDS = 600
_SALT = "atlas-destructive-confirmation"


def _serializer(app):
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(app.secret_key, salt=_SALT)


def confirmation_token(app, path: str) -> str:
    return _serializer(app).dumps({"path": path})


def token_is_valid(app, token: str, path: str) -> bool:
    from itsdangerous import BadSignature, SignatureExpired

    try:
        payload = _serializer(app).loads(
            token, max_age=CONFIRM_MAX_AGE_SECONDS
        )
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("path") == path


def require_confirmation(*, title: str, detail: str, consequence: str):
    """Gate a destructive route. Returns ``None`` when the request carries
    a valid confirmation token (proceed); otherwise returns the
    confirmation page response the route must return unchanged."""

    from flask import current_app, render_template, request

    token = str(request.form.get(CONFIRM_TOKEN_FIELD) or "")
    if token and token_is_valid(current_app, token, request.path):
        return None

    def _sensitive(name: str) -> bool:
        lowered = name.casefold()
        return any(
            marker in lowered
            for marker in ("password", "secret", "passphrase", "private_key")
        )

    # Echo the original fields so the confirmed POST replays the request —
    # but NEVER credential material: a password must not round-trip
    # through the confirmation page's HTML.
    fields = [
        (name, value)
        for name in request.form
        for value in request.form.getlist(name)
        if name not in (CONFIRM_TOKEN_FIELD, "_csrf") and not _sensitive(name)
    ]
    return render_template(
        "confirm_action.html",
        title=title,
        detail=detail,
        consequence=consequence,
        action_path=request.path,
        fields=fields,
        confirm_token=confirmation_token(current_app, request.path),
        cancel_href=request.referrer or "/",
    )
