"""Request security for the Atlas web application.

One registration wires, in order, for every request:

1. a correlation id (accepted from ``X-Request-ID`` or minted),
2. authentication (mode-specific provider → ``g.principal``),
3. authorization (the endpoint's permission from ``authz_map`` —
   an unmapped endpoint is denied, so new routes fail closed),
4. CSRF protection for mutating methods,
5. rate limiting for sensitive endpoints,

and on the way out: security headers, cache control, and the
correlation id echoed for log correlation. Denials are audited with the
authenticated actor, roles, endpoint, and outcome — and never with
request bodies (which could carry secrets).

Authentication modes are decided once at startup (``ATLAS_AUTH_MODE``):
``local`` (loopback-only auto-principal — the development mode),
``password`` (user store + server-side sessions), ``proxy``
(SSO-terminating reverse proxy asserting identity; see
``access/providers.py``).
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import time
from uuid import uuid4

from founderos_atlas.access import (
    LocalDevelopmentAuth,
    PasswordAuth,
    ProxySSOAuth,
    SESSION_COOKIE,
    SessionStore,
    UserStore,
    ensure_recovery_admin,
    resolve_auth_mode,
    resolve_rate_limiter,
)
from founderos_atlas.audit import AuditEvent, AuditLog

from .authz_map import PUBLIC, permission_for_endpoint

CSRF_COOKIE = "atlas_csrf"
CSRF_HEADER = "X-Atlas-CSRF"
CSRF_FIELD = "_csrf"

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Endpoints exempt from the session-token CSRF requirement. login_submit
# runs before any session exists; it is protected by the same-origin
# check, SameSite cookies, and its rate limit.
_CSRF_TOKEN_EXEMPT = frozenset({"login_submit"})

# (limit per minute, applies-to-endpoint). Sensitive or expensive.
# login_submit is NOT here: sign-in uses the layered limiter below.
_RATE_LIMITS: dict[str, int] = {
    "credentials_test": 20,
    "profile_test": 20,
    "settings_restore": 5,
    "api_advisor_ask": 30,
    "advisor_ask_route": 30,
}


def _login_limits() -> dict[str, int]:
    """Layered sign-in limits (per minute). The ACCOUNT layer counts every
    attempt against the case-normalized submitted name regardless of
    source, so a distributed attack cannot dodge it; the SOURCE layer
    caps one address spraying many accounts; the optional GLOBAL layer
    (0 disables) is the final safety ceiling."""

    return {
        "account": int(os.environ.get("ATLAS_LOGIN_ACCOUNT_LIMIT", 5)),
        "source": int(os.environ.get("ATLAS_LOGIN_SOURCE_LIMIT", 30)),
        "global": int(os.environ.get("ATLAS_LOGIN_GLOBAL_LIMIT", 500)),
    }

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

logger = logging.getLogger("atlas.security")


def _wants_json(request) -> bool:
    if request.path.startswith("/api/"):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def _same_origin(request) -> bool:
    """False only when the browser proves the request came from another
    origin. Non-browser clients send no Origin/Sec-Fetch-Site and pass —
    CSRF is a confused-deputy attack on browsers, not on curl."""

    fetch_site = request.headers.get("Sec-Fetch-Site", "").casefold()
    if fetch_site in {"cross-site", "same-site"}:
        # "same-site" still means a DIFFERENT origin (e.g. another port).
        return False
    origin = request.headers.get("Origin")
    if origin and origin.casefold() != "null":
        return origin.rstrip("/").casefold() == request.host_url.rstrip(
            "/"
        ).casefold()
    if origin and origin.casefold() == "null":
        return False
    return True


def register_security(app, *, auth_mode: str | None = None) -> None:
    from flask import (
        Response, abort, g, redirect, render_template, request, url_for,
    )
    from markupsafe import Markup

    mode = resolve_auth_mode(auth_mode or app.config.get("ATLAS_AUTH_MODE"))
    app.config["ATLAS_AUTH_MODE"] = mode
    workspace_root = app.config["ATLAS_WORKSPACE_ROOT"]

    trusted_proxies = frozenset(
        item.strip()
        for item in os.environ.get("ATLAS_TRUSTED_PROXY_ADDRS", "").split(",")
        if item.strip()
    )
    allow_forwarded_local = (
        os.environ.get("ATLAS_LOCAL_ALLOW_FORWARDED", "").strip() == "1"
    )
    if mode == "local":
        # Proxy-shaped configuration alongside local mode is a deployment
        # mistake that would end in silently trusting a proxy: refuse to
        # start rather than guess.
        conflicting = [
            name for name in
            ("ATLAS_TRUSTED_PROXY_ADDRS", "ATLAS_PROXY_SECRET")
            if os.environ.get(name, "").strip()
        ]
        if conflicting:
            raise RuntimeError(
                "ATLAS_AUTH_MODE=local cannot run with proxy settings "
                f"({', '.join(conflicting)} set). Local mode must never "
                "sit behind a proxy — use ATLAS_AUTH_MODE=password or "
                "proxy to serve forwarded clients."
            )
        if allow_forwarded_local:
            logger.warning(
                "ATLAS_LOCAL_ALLOW_FORWARDED=1: local mode will accept "
                "loopback requests that carry forwarding headers. This is "
                "safe ONLY for a deliberate localhost-only dev wrapper; "
                "never expose this server beyond the machine."
            )
    tls_enabled = bool(
        app.config.get("ATLAS_TLS")
        or os.environ.get("ATLAS_TLS", "").strip() in {"1", "true", "yes"}
    )
    app.config["ATLAS_TLS"] = tls_enabled

    users = UserStore(workspace_root)
    sessions = SessionStore(
        workspace_root,
        max_age_seconds=int(os.environ.get("ATLAS_SESSION_MAX_AGE", 12 * 3600)),
        idle_timeout_seconds=int(
            os.environ.get("ATLAS_SESSION_IDLE_TIMEOUT", 2 * 3600)
        ),
    )
    app.config["ATLAS_USER_STORE"] = users
    app.config["ATLAS_SESSION_STORE"] = sessions

    if mode == "password":
        _bootstrap_admin_from_env(users)
        provider = PasswordAuth(users, sessions)
    elif mode == "proxy":
        provider = ProxySSOAuth(
            users, os.environ.get("ATLAS_PROXY_SECRET", "")
        )
    else:
        provider = LocalDevelopmentAuth(
            allow_forwarded=allow_forwarded_local
        )
    app.config["ATLAS_AUTH_PROVIDER"] = provider

    if mode in ("password", "proxy"):
        recovered = ensure_recovery_admin(workspace_root)
        if recovered:
            logger.warning(
                "Emergency recovery applied: %s is an enabled system "
                "administrator. Unset ATLAS_RECOVERY_ADMIN_USER/PASSWORD "
                "after signing in.", recovered,
            )
            AuditLog(workspace_root).append(AuditEvent.create(
                category="user-account", operation="recovery-reset",
                subject=f"user:{recovered}", actor="system",
                source="startup",
                reason="ATLAS_RECOVERY_ADMIN_* environment recovery",
            ))

    # The Flask signing key protects only flashes; sessions are server-side
    # opaque tokens. A hardcoded key would still be a liability (flash
    # forgery), so mint a per-process random key unless one is provided.
    provided_key = os.environ.get("ATLAS_SECRET_KEY", "").strip()
    app.secret_key = provided_key or secrets.token_hex(32)

    limiter = resolve_rate_limiter()
    audit_log = AuditLog(workspace_root)

    def _client_address() -> str:
        """The address rate limits and audit attribute the request to.

        ``request.remote_addr`` — except when the TCP peer is an
        EXPLICITLY trusted proxy (ATLAS_TRUSTED_PROXY_ADDRS, production
        modes only): then the closest untrusted hop of X-Forwarded-For
        is used. Header values are never trusted from anyone else, and
        this never feeds an authentication decision.
        """

        peer = request.remote_addr or "unknown"
        if mode == "local" or peer not in trusted_proxies:
            return peer
        forwarded = [
            hop.strip()
            for hop in request.headers.get("X-Forwarded-For", "").split(",")
            if hop.strip()
        ]
        for hop in reversed(forwarded):
            if hop not in trusted_proxies:
                return hop
        return peer

    def _audit_denial(operation: str, detail: str) -> None:
        principal = getattr(g, "principal", None)
        try:
            audit_log.append(AuditEvent.create(
                category="authorization",
                operation=operation,
                subject=f"endpoint:{request.endpoint or request.path}",
                actor=principal.username if principal else "unauthenticated",
                actor_roles=principal.roles if principal else (),
                outcome="denied",
                reason=detail,
                correlation_id=getattr(g, "correlation_id", None),
            ))
        except Exception:  # pragma: no cover - auditing must never 500 a deny
            logger.exception("audit write failed while recording a denial")

    def _deny(status: int, message: str):
        if _wants_json(request):
            return Response(
                json.dumps({"error": message,
                            "correlation_id": g.correlation_id}),
                status=status, mimetype="application/json",
            )
        template = "login.html" if status == 401 else "error.html"
        if status == 401:
            return redirect(url_for("login", next=request.full_path.rstrip("?")
                            if request.method == "GET" else "/"))
        return (
            render_template(
                template, status=status, message=message,
                correlation_id=g.correlation_id,
            ),
            status,
        )

    # -- before ------------------------------------------------------------

    @app.before_request
    def _security_gate():
        offered = request.headers.get("X-Request-ID", "")
        g.correlation_id = (
            offered if _SAFE_REQUEST_ID.match(offered)
            else f"req-{uuid4().hex[:16]}"
        )
        g.request_started = time.perf_counter()
        g.principal = None
        g.session_record = None

        decision = provider.identify(request)
        g.principal = decision.principal
        g.session_record = decision.session_record

        permission = permission_for_endpoint(request.endpoint)
        if permission == PUBLIC:
            pass
        elif decision.failure:
            _audit_denial("refuse", decision.failure)
            return _deny(403, decision.failure)
        elif decision.principal is None:
            return _deny(401, "Sign in to continue.")
        elif permission is None:
            _audit_denial(
                "deny-unmapped",
                "The endpoint has no entry in the authorization table.",
            )
            return _deny(
                403,
                "This operation has not been assigned a permission and is "
                "denied by default.",
            )
        elif not decision.principal.can(permission):
            _audit_denial("deny", f"missing permission {permission}")
            return _deny(
                403,
                "Your roles do not include the permission required for "
                f"this operation ({permission}).",
            )

        # CSRF for every mutating request, in every mode.
        if request.method in _MUTATING_METHODS:
            if not _same_origin(request):
                _audit_denial("csrf", "cross-origin mutation refused")
                return _deny(
                    403, "Cross-origin requests cannot perform this action."
                )
            if (
                mode == "password"
                and request.endpoint not in _CSRF_TOKEN_EXEMPT
            ):
                expected = (
                    g.session_record.csrf_token if g.session_record else ""
                )
                offered_token = (
                    request.headers.get(CSRF_HEADER)
                    or request.form.get(CSRF_FIELD, "")
                )
                if not offered_token and request.is_json:
                    offered_token = (
                        request.get_json(silent=True) or {}
                    ).get(CSRF_FIELD, "")
                if not expected or not hmac.compare_digest(
                    str(offered_token or ""), expected
                ):
                    _audit_denial("csrf", "missing or stale CSRF token")
                    return _deny(
                        403,
                        "The form's protection token is missing or stale. "
                        "Reload the page and try again.",
                    )

        if request.endpoint == "login_submit":
            limits = _login_limits()
            # The account layer keys the case-normalized SUBMITTED name —
            # existing or not — so limiting reveals nothing about which
            # accounts exist, and case games change nothing.
            account = str(
                request.form.get("username") or ""
            ).strip().casefold()[:64] or "(empty)"
            source = _client_address()
            layers = [
                ("account", f"login:acct:{account}", limits["account"]),
                ("source", f"login:src:{source}", limits["source"]),
            ]
            if limits["global"] > 0:
                layers.append(("global", "login:global", limits["global"]))
            # Every attempt consumes every layer; success never resets a
            # counter, so valid credentials cannot be used to launder an
            # attack window.
            blocked = [
                layer for layer, key, limit in layers
                if not limiter.allow(key, limit=limit)
            ]
            if blocked:
                _audit_denial(
                    "rate-limit",
                    f"sign-in limit ({'+'.join(blocked)} layer) for "
                    f"account {account!r} from {source}",
                )
                # One generic answer for every layer: no enumeration.
                return _deny(
                    429,
                    "Too many sign-in attempts. Wait a minute and try "
                    "again.",
                )

        limit = _RATE_LIMITS.get(request.endpoint or "")
        if limit is not None:
            key = f"{_client_address()}:{request.endpoint}"
            if not limiter.allow(key, limit=limit):
                _audit_denial("rate-limit", f"over {limit}/minute")
                return _deny(
                    429, "Too many attempts. Wait a minute and try again."
                )

    # -- after -------------------------------------------------------------

    @app.after_request
    def _security_headers(response):
        artifact_name = (
            str((request.view_args or {}).get("name") or "")
            if request.endpoint == "artifacts"
            else ""
        )
        is_topology_artifact = artifact_name.endswith("atlas_topology.html")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Normal Atlas pages and report artifacts must never be framed.  The
        # generated topology viewer is the single deliberate exception: the
        # /topology page embeds it in a same-origin iframe.  DENY here makes
        # a healthy discovery look like a broken/empty topology in every
        # modern browser.
        response.headers.setdefault(
            "X-Frame-Options",
            "SAMEORIGIN" if is_topology_artifact else "DENY",
        )
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if request.endpoint == "artifacts":
            # Generated topology artifacts are self-contained pages with
            # inline scripts.  Only the topology viewer may be embedded, and
            # only by Atlas on the same origin; other artifacts remain
            # non-frameable.
            frame_ancestors = "'self'" if is_topology_artifact else "'none'"
            csp = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                f"connect-src 'self'; frame-ancestors {frame_ancestors}; "
                "base-uri 'self'; form-action 'self'"
            )
        else:
            nonce = getattr(g, "csp_nonce", "")
            script_src = "'self'" + (f" 'nonce-{nonce}'" if nonce else "")
            csp = (
                "default-src 'self'; "
                f"script-src {script_src}; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'self'; form-action 'self'"
            )
        response.headers.setdefault("Content-Security-Policy", csp)
        if tls_enabled:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        if getattr(g, "principal", None) is not None and (
            response.mimetype == "text/html"
            or request.path.startswith("/api/")
        ):
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "X-Request-ID", getattr(g, "correlation_id", "")
        )
        return response

    # -- template context --------------------------------------------------

    @app.context_processor
    def _security_context():
        principal = getattr(g, "principal", None)
        record = getattr(g, "session_record", None)

        def can(permission: str) -> bool:
            return bool(principal) and principal.can(permission)

        def csrf_field() -> Markup:
            if mode != "password" or record is None:
                return Markup("")
            return Markup(
                f'<input type="hidden" name="{CSRF_FIELD}" '
                f'value="{record.csrf_token}">'
            )

        def csrf_token() -> str:
            return record.csrf_token if record is not None else ""

        def inbox_unread() -> int:
            if principal is None:
                return 0
            try:
                from founderos_atlas.notifications import NotificationStore

                return NotificationStore(workspace_root).unread_count(
                    principal.username, principal.roles
                )
            except Exception:  # pragma: no cover - a bad file must not 500 pages
                return 0

        if not hasattr(g, "csp_nonce"):
            g.csp_nonce = secrets.token_urlsafe(16)
        return {
            "inbox_unread": inbox_unread(),
            "current_principal": principal,
            "can": can,
            "csrf_field": csrf_field,
            "csrf_token": csrf_token,
            "auth_mode": mode,
            "csp_nonce": g.csp_nonce,
        }

    # -- error handling (no stack traces, no internal detail) --------------

    @app.errorhandler(404)
    def _not_found(_error):
        if _wants_json(request):
            return Response(
                json.dumps({"error": "not found"}), status=404,
                mimetype="application/json",
            )
        return (
            render_template(
                "error.html", status=404,
                message="Atlas has no page or record at this address.",
                correlation_id=getattr(g, "correlation_id", ""),
            ),
            404,
        )

    @app.errorhandler(409)
    def _conflict(error):
        message = getattr(error, "description", None) or (
            "Someone else changed this record while you were editing. "
            "Nothing was overwritten — reload to see the current state, "
            "then reapply your change."
        )
        _audit_denial("conflict", str(message))
        try:
            from founderos_atlas.notifications import (
                KIND_EDIT_CONFLICT, NotificationStore,
            )

            principal = getattr(g, "principal", None)
            if principal is not None:
                NotificationStore(workspace_root).notify(
                    kind=KIND_EDIT_CONFLICT,
                    title="An edit of yours hit a conflict",
                    detail=str(message),
                    href=request.headers.get("Referer") or "/",
                    audience=principal.username,
                    correlation_id=g.correlation_id,
                    dedupe_key=request.path,
                )
        except Exception:  # pragma: no cover - notify must not mask the 409
            pass
        if _wants_json(request):
            return Response(
                json.dumps({"error": str(message), "conflict": True,
                            "correlation_id": g.correlation_id}),
                status=409, mimetype="application/json",
            )
        return (
            render_template(
                "error.html", status=409, message=str(message),
                correlation_id=g.correlation_id,
            ),
            409,
        )

    @app.errorhandler(500)
    def _server_error(error):
        correlation = getattr(g, "correlation_id", "")
        logger.error(
            "unhandled error correlation=%s endpoint=%s",
            correlation, request.endpoint, exc_info=error,
        )
        if _wants_json(request):
            return Response(
                json.dumps({
                    "error": "Atlas hit an internal error.",
                    "correlation_id": correlation,
                }),
                status=500, mimetype="application/json",
            )
        return (
            render_template(
                "error.html", status=500,
                message=(
                    "Atlas hit an internal error. Nothing was changed "
                    "beyond what the audit log records. Quote the "
                    "correlation id when reporting this."
                ),
                correlation_id=correlation,
            ),
            500,
        )

    # -- login / logout ----------------------------------------------------

    @app.route("/login")
    def login():
        if mode != "password" or getattr(g, "principal", None) is not None:
            return redirect("/")
        return render_template(
            "login.html", next=_safe_next(request.args.get("next")),
        )

    @app.route("/login", methods=["POST"], endpoint="login_submit")
    def login_submit():
        if mode != "password":
            abort(404)
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        token = provider.login(username, password)
        if token is None:
            audit_log.append(AuditEvent.create(
                category="authentication", operation="login",
                subject=f"user:{username or 'unknown'}",
                actor=username or "unknown", outcome="failed",
                reason="invalid credentials or disabled account",
                correlation_id=g.correlation_id,
            ))
            return (
                render_template(
                    "login.html",
                    error="That sign-in didn't work. Check the username "
                          "and password.",
                    next=_safe_next(request.form.get("next")),
                ),
                401,
            )
        audit_log.append(AuditEvent.create(
            category="authentication", operation="login",
            subject=f"user:{username}", actor=username,
            correlation_id=g.correlation_id,
        ))
        record = sessions.resolve(token)
        response = redirect(_safe_next(request.form.get("next")))
        response.set_cookie(
            SESSION_COOKIE, token, httponly=True, samesite="Lax",
            secure=tls_enabled, path="/",
        )
        response.set_cookie(
            CSRF_COOKIE, record.csrf_token if record else "",
            httponly=False, samesite="Lax", secure=tls_enabled, path="/",
        )
        return response

    @app.route("/logout", methods=["POST"])
    def logout():
        principal = getattr(g, "principal", None)
        if mode == "password":
            sessions.invalidate(request.cookies.get(SESSION_COOKIE))
            if principal is not None:
                audit_log.append(AuditEvent.create(
                    category="authentication", operation="logout",
                    subject=f"user:{principal.username}",
                    actor=principal.username,
                    actor_roles=principal.roles,
                    correlation_id=g.correlation_id,
                ))
        response = redirect("/login" if mode == "password" else "/")
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return response


def _safe_next(target: str | None) -> str:
    """Only same-app paths; anything absolute or protocol-relative is
    replaced by the dashboard (open-redirect protection)."""

    candidate = str(target or "").strip()
    if candidate.startswith("/") and not candidate.startswith("//") and (
        ":" not in candidate.split("?", 1)[0]
    ):
        return candidate
    return "/"


def _bootstrap_admin_from_env(users: UserStore) -> None:
    """First-run bootstrap: if the user store is empty and the environment
    names a bootstrap admin, create it (password hashed immediately; the
    variables should be removed after first start)."""

    username = os.environ.get("ATLAS_BOOTSTRAP_ADMIN_USER", "").strip()
    password = os.environ.get("ATLAS_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not username or not password or not users.is_empty():
        return
    from founderos_atlas.access.models import ROLE_SYSTEM_ADMIN

    users.create(
        username=username, roles=(ROLE_SYSTEM_ADMIN,), password=password,
    )
