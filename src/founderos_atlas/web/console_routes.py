"""Console HTTP + WebSocket surface (PR-044A, CONSOLE).

The browser holds a terminal; Atlas holds the SSH session. Between them runs
a WebSocket carrying bytes and a few small JSON control frames. No credential
ever crosses it.

Frame protocol (deliberately tiny — a terminal does not need a schema):

  client -> server   ``{"type":"input","data":"…"}``     keystrokes
                     ``{"type":"resize","cols":N,"rows":N}``
                     ``{"type":"ping"}``
  server -> client   ``{"type":"output","data":"…"}``    device bytes
                     ``{"type":"status","state":…,"detail":…}``
                     ``{"type":"closed","reason":…}``

Why a token and not just "it's localhost": WebSockets are not covered by the
same-origin policy, so any page the operator visits could otherwise attach to
this endpoint and drive a router. See ``console.security``.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from founderos_atlas.console import (
    ACTION_AUTH_FAILED,
    ACTION_HOST_KEY_CHANGED,
    ConsoleAccessDenied,
    ConsoleAuthenticationError,
    ConsoleHostKeyBlocked,
    ConsoleHostKeyUnknown,
    ConsoleLimitReached,
    ConsoleSession,
    ConsoleSessionError,
    HostKeyStoreError,
    require_operator,
    origin_allowed,
)


#: How long the pump waits between reads when the device is quiet.
_POLL_SECONDS = 0.02


def register_console_routes(app, deps) -> None:
    """Wire the console onto the app.

    ``deps`` supplies the pieces the console needs from the surrounding GUI
    without importing routes.py (which imports this module):
    ``scoped_context``, ``console_target``, ``credential_for``,
    ``host_key_store``, ``token_store``, ``session_manager``, ``audit``.
    """

    sock = _make_sock(app)

    # -- helpers -----------------------------------------------------------

    def _allowed_hosts() -> tuple[str, ...]:
        configured = current_app.config.get("ATLAS_CONSOLE_ALLOWED_ORIGINS") or ()
        return tuple(str(item) for item in configured)

    def _guard_origin() -> None:
        """Refuse any request that did not come from the Atlas GUI itself."""

        if not origin_allowed(
            request.headers.get("Origin"),
            host_header=request.headers.get("Host"),
            allowed_hosts=_allowed_hosts(),
        ):
            raise ConsoleAccessDenied(
                "This request did not come from the Atlas interface and was "
                "refused."
            )

    # -- pages -------------------------------------------------------------

    @app.route("/console/<path:device_id>")
    def console_page(device_id: str):
        """The terminal page for one canonical device."""

        context, scopes, scope_id = deps.scoped_context("topology")
        target = deps.console_target(scopes, scope_id, device_id)
        if target is None:
            flash(
                "Atlas has no canonical device with that identity in this "
                "scope.",
                "error",
            )
            return redirect(url_for("topology"))
        operator = require_operator()
        host_key = None
        if target.eligible and target.management_ip:
            try:
                store = deps.host_key_store()
                known = {
                    (entry.get("host"), entry.get("port"))
                    for entry in store.known_hosts()
                }
                host_key = {
                    "trusted": (target.management_ip, target.port) in known,
                }
            except HostKeyStoreError as error:
                host_key = {"trusted": False, "error": str(error)}
        return render_template(
            "console.html",
            target=target.to_dict(),
            operator=operator.to_dict(),
            host_key=host_key,
            credential_sets=deps.credential_choices(scopes, scope_id),
            # A window that IS one console has no use for the navigation
            # shell. Asked for explicitly by the popup opener rather than
            # sniffed from window.opener: a request either carries it or it
            # does not, which is deterministic and testable server-side.
            bare_chrome=request.args.get("chrome") == "bare",
            **context,
        )

    @app.route("/console/<path:device_id>/token", methods=["POST"])
    def console_token(device_id: str):
        """Mint a single-use ticket for one attach.

        Same-origin POST only. The token names the device it was minted for,
        so it cannot be replayed at another one.
        """

        try:
            _guard_origin()
        except ConsoleAccessDenied as error:
            return jsonify({"error": str(error)}), 403

        _context, scopes, scope_id = deps.scoped_context("topology")
        target = deps.console_target(scopes, scope_id, device_id)
        if target is None:
            return jsonify({"error": "No such device in this scope."}), 404
        if not target.eligible:
            # The GUI should not have offered this, but never trust the GUI.
            return jsonify({"error": target.reason, "state": target.state}), 409

        operator = require_operator()
        try:
            deps.session_manager().check_capacity()
        except ConsoleLimitReached as error:
            return jsonify({"error": str(error), "state": "limit"}), 429

        credential_ref = (
            request.json.get("credential_ref")
            if request.is_json and request.json
            else None
        ) or target.credential_ref
        if not credential_ref:
            return jsonify(
                {"error": "Choose a credential set to connect.",
                 "state": "credential-required"}
            ), 409
        token = deps.token_store().mint(
            device_id=device_id,
            scope_id=scope_id,
            operator=operator.name,
            credential_ref=credential_ref,
        )
        # The token is the only thing that goes back. Not the password, not
        # the credential's contents — only the reference the operator chose.
        return jsonify(
            {
                "token": token.token,
                "device_id": device_id,
                "hostname": target.hostname,
                "management_ip": target.management_ip,
                "port": target.port,
                "expires_in": deps.token_store()._ttl,
            }
        )

    @app.route("/console/<path:device_id>/hostkey", methods=["GET"])
    def console_hostkey(device_id: str):
        """The fingerprint the device is presenting right now."""

        try:
            _guard_origin()
        except ConsoleAccessDenied as error:
            return jsonify({"error": str(error)}), 403
        _context, scopes, scope_id = deps.scoped_context("topology")
        target = deps.console_target(scopes, scope_id, device_id)
        if target is None or not target.management_ip:
            return jsonify({"error": "No verified management endpoint."}), 404
        try:
            verdict = deps.probe_host_key(target.management_ip, target.port)
        except ConsoleSessionError as error:
            return jsonify({"error": str(error)}), 502
        return jsonify(verdict.to_dict())

    @app.route("/console/<path:device_id>/hostkey/accept", methods=["POST"])
    def console_hostkey_accept(device_id: str):
        """Record the operator's explicit decision to trust a fingerprint.

        The fingerprint must be echoed back by the client: acceptance applies
        to the key the operator was *shown*, never to whatever the device
        happens to present at the moment the button is clicked.
        """

        try:
            _guard_origin()
        except ConsoleAccessDenied as error:
            return jsonify({"error": str(error)}), 403
        _context, scopes, scope_id = deps.scoped_context("topology")
        target = deps.console_target(scopes, scope_id, device_id)
        if target is None or not target.management_ip:
            return jsonify({"error": "No verified management endpoint."}), 404
        payload = request.json if request.is_json else None
        fingerprint = str((payload or {}).get("fingerprint") or "").strip()
        if not fingerprint:
            return jsonify({"error": "No fingerprint was supplied."}), 400
        try:
            verdict = deps.probe_host_key(target.management_ip, target.port)
        except ConsoleSessionError as error:
            return jsonify({"error": str(error)}), 502
        if verdict.fingerprint != fingerprint:
            return jsonify(
                {
                    "error": (
                        "The device is presenting a different key than the one "
                        "you were shown. Nothing was accepted. Review the "
                        "fingerprint again."
                    ),
                    "fingerprint": verdict.fingerprint,
                }
            ), 409
        deps.host_key_store().accept(
            target.management_ip, target.port, verdict.key_type, verdict.fingerprint
        )
        deps.audit().record(
            "host-key-accepted",
            session_id="-",
            operator=require_operator().name,
            device_id=device_id,
            hostname=target.hostname,
            management_ip=target.management_ip,
            port=target.port,
            credential_ref=None,
            result="accepted",
            detail=f"{verdict.key_type} {verdict.fingerprint}",
        )
        return jsonify({"accepted": True, **verdict.to_dict()})

    @app.route("/console/sessions")
    def console_sessions():
        """Every live session — for the operator, and for cleanup."""

        manager = deps.session_manager()
        manager.expire_due()
        return jsonify(
            {"sessions": [item.to_dict() for item in manager.sessions()]}
        )

    @app.route("/console/sessions/<session_id>/disconnect", methods=["POST"])
    def console_disconnect(session_id: str):
        try:
            _guard_origin()
        except ConsoleAccessDenied as error:
            return jsonify({"error": str(error)}), 403
        info = deps.session_manager().close(session_id)
        if info is None:
            return jsonify({"error": "No such session."}), 404
        return jsonify(info.to_dict())

    # -- the terminal itself ----------------------------------------------

    @sock.route("/console/attach/<path:device_id>")
    def console_attach(ws, device_id: str):
        """Attach a browser terminal to a server-side SSH session.

        Every failure path here ends the socket with an operator-facing
        reason. None of them leak a trace, and none of them leave an SSH
        session running behind a closed tab.
        """

        # 1. Origin. Before anything else, and before any SSH is attempted.
        if not origin_allowed(
            request.headers.get("Origin"),
            host_header=request.headers.get("Host"),
            allowed_hosts=_allowed_hosts(),
        ):
            _send(ws, {
                "type": "closed",
                "reason": (
                    "This terminal did not come from the Atlas interface and "
                    "was refused."
                ),
            })
            return

        # 2. Token. Single-use, device-bound, short-lived.
        token_value = request.args.get("token", "")
        try:
            token = deps.token_store().redeem(token_value, device_id=device_id)
        except ConsoleAccessDenied as error:
            _send(ws, {"type": "closed", "reason": str(error)})
            return

        _context, scopes, scope_id = deps.scoped_context("topology")
        target = deps.console_target(scopes, scope_id, device_id)
        if target is None or not target.eligible or not target.management_ip:
            _send(ws, {
                "type": "closed",
                "reason": (
                    target.reason if target
                    else "No such device in this scope."
                ),
            })
            return

        operator = require_operator()
        manager = deps.session_manager()
        audit = deps.audit()

        # 3. Credential. Resolved server-side, used here, never sent anywhere.
        credential_ref = token.credential_ref or target.credential_ref
        try:
            username, password = deps.credential_for(
                scopes, scope_id, credential_ref
            )
        except Exception:  # noqa: BLE001
            _send(ws, {
                "type": "closed",
                "reason": (
                    "Atlas could not read the credential for this device from "
                    "its secure store."
                ),
            })
            return

        _send(ws, {"type": "status", "state": "connecting",
                   "detail": f"Connecting to {target.management_ip}…"})

        session = ConsoleSession(
            host=target.management_ip,
            port=target.port,
            username=username,
            password=password,
            host_key_store=deps.host_key_store(),
            allow_new_host_key=False,
            connect_timeout=float(
                current_app.config.get("ATLAS_CONSOLE_CONNECT_TIMEOUT", 10.0)
            ),
        )
        del password  # the only copy this frame holds

        try:
            session.connect()
        except ConsoleHostKeyBlocked as error:
            audit.record(
                "host-key-changed", session_id="-", operator=operator.name,
                device_id=device_id, hostname=target.hostname,
                management_ip=target.management_ip, port=target.port,
                credential_ref=credential_ref, result="blocked",
                detail=error.verdict.fingerprint,
            )
            _send(ws, {
                "type": "closed",
                "state": ACTION_HOST_KEY_CHANGED,
                "reason": str(error),
                "host_key": error.verdict.to_dict(),
            })
            return
        except ConsoleHostKeyUnknown as error:
            _send(ws, {
                "type": "closed",
                "state": "host-key-unknown",
                "reason": str(error),
                "host_key": error.verdict.to_dict(),
            })
            return
        except ConsoleAuthenticationError as error:
            audit.record(
                "authentication-failed", session_id="-", operator=operator.name,
                device_id=device_id, hostname=target.hostname,
                management_ip=target.management_ip, port=target.port,
                credential_ref=credential_ref, result="authentication-failed",
            )
            _send(ws, {"type": "closed", "state": ACTION_AUTH_FAILED,
                       "reason": str(error)})
            return
        except ConsoleSessionError as error:
            audit.record(
                "connect-failed", session_id="-", operator=operator.name,
                device_id=device_id, hostname=target.hostname,
                management_ip=target.management_ip, port=target.port,
                credential_ref=credential_ref, result="failed",
                detail=str(error),
            )
            _send(ws, {"type": "closed", "reason": str(error)})
            return

        # 4. Register. Enforces the concurrency ceiling.
        try:
            info = manager.register(
                session,
                device_id=device_id,
                hostname=target.hostname,
                management_ip=target.management_ip,
                port=target.port,
                username=username,
                credential_ref=credential_ref or "",
                operator=operator.name,
            )
        except ConsoleLimitReached as error:
            session.close()
            _send(ws, {"type": "closed", "reason": str(error)})
            return

        _send(ws, {
            "type": "status", "state": "connected",
            "session_id": info.session_id,
            "opened_at": info.opened_at,
            "detail": f"Connected to {target.hostname}.",
        })

        _pump(ws, session, manager, info.session_id)

    # -- pump --------------------------------------------------------------

    def _pump(ws, session, manager, session_id: str) -> None:
        """Shuttle bytes until either end stops talking.

        The reader runs in its own thread because a WebSocket receive blocks;
        the device must be able to speak unprompted (a syslog line, a prompt)
        without waiting for the operator to press a key.
        """

        stop = threading.Event()

        def reader() -> None:
            while not stop.is_set():
                try:
                    data = session.read()
                except Exception:  # noqa: BLE001
                    break
                if data:
                    manager.touch(session_id)
                    if not _send(
                        ws, {"type": "output",
                             "data": data.decode("utf-8", errors="replace")}
                    ):
                        break
                    continue
                if session.eof():
                    break
                stop.wait(_POLL_SECONDS)
            _send(ws, {"type": "closed", "reason": "The device closed the session."})

        thread = threading.Thread(target=reader, name=f"console-{session_id}",
                                  daemon=True)
        thread.start()
        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    break            # the browser went away (tab closed)
                try:
                    message = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                kind = message.get("type")
                if kind == "input":
                    manager.touch(session_id)
                    try:
                        session.write(str(message.get("data", "")).encode())
                    except ConsoleSessionError as error:
                        _send(ws, {"type": "closed", "reason": str(error)})
                        break
                elif kind == "resize":
                    session.resize(message.get("cols", 80), message.get("rows", 24))
                elif kind == "disconnect":
                    break
        except Exception:  # noqa: BLE001 - a broken socket is a normal exit
            pass
        finally:
            # This is the "browser closed" path. Without it the SSH session
            # would survive the tab and keep a VTY line open on the device.
            stop.set()
            manager.close(session_id, reason="session ended")


def _send(ws, payload: dict[str, Any]) -> bool:
    try:
        ws.send(json.dumps(payload))
        return True
    except Exception:  # noqa: BLE001
        return False


def _make_sock(app):
    try:
        from flask_sock import Sock
    except ImportError as error:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "The Atlas console requires flask-sock. Install it with: "
            "pip install founderos-runtime[web]"
        ) from error
    return Sock(app)
