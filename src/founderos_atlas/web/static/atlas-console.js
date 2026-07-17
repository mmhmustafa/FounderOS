/*
 * Atlas Console terminal (PR-044A, CONSOLE).
 *
 * The browser holds a terminal and nothing else. It never sees a password,
 * never speaks SSH, and cannot open a session on its own: every attach needs
 * a single-use token minted by a same-origin POST, and the server checks the
 * Origin of the WebSocket before it touches the device.
 */
(function (global) {
  'use strict';

  var term = null;
  var fit = null;
  var socket = null;
  var sessionId = null;
  var openedAt = null;
  var durationTimer = null;
  var config = {};

  function el(id) { return document.getElementById(id); }

  function setState(label, kind) {
    var node = el('console-state');
    if (!node) { return; }
    node.textContent = label;
    node.className = 'job-badge job-badge-' + (kind || 'queued');
  }

  function showAlert(title, body, actions, fingerprints) {
    var box = el('console-alert');
    if (!box) { return; }
    el('console-alert-title').textContent = title;
    el('console-alert-body').textContent = body;
    var actionBar = el('console-alert-actions');
    actionBar.innerHTML = '';
    (actions || []).forEach(function (action) {
      var button = document.createElement('button');
      button.className = 'btn btn-sm';
      button.type = 'button';
      button.textContent = action.label;
      button.addEventListener('click', action.onClick);
      actionBar.appendChild(button);
    });
    var fpBox = el('console-alert-fingerprints');
    if (fingerprints && fingerprints.known_fingerprint) {
      el('fp-known').textContent = fingerprints.known_fingerprint;
      el('fp-new').textContent = fingerprints.fingerprint;
      fpBox.hidden = false;
    } else if (fingerprints && fingerprints.fingerprint) {
      el('fp-known').textContent = '(never seen before)';
      el('fp-new').textContent = fingerprints.fingerprint;
      fpBox.hidden = false;
    } else {
      fpBox.hidden = true;
    }
    box.hidden = false;
  }

  function hideAlert() {
    var box = el('console-alert');
    if (box) { box.hidden = true; }
  }

  function tickDuration() {
    if (!openedAt) { return; }
    var seconds = Math.floor((Date.now() - openedAt) / 1000);
    var mins = Math.floor(seconds / 60);
    var secs = seconds % 60;
    var node = el('console-duration');
    if (node) {
      node.textContent = 'Session ' + mins + 'm ' + (secs < 10 ? '0' : '') + secs + 's';
    }
  }

  function chosenCredential() {
    var select = el('credential-ref');
    return select ? select.value : config.credentialRef;
  }

  /* Mint a one-shot token. Same-origin POST: a cross-origin page cannot do
     this, which is what makes the WebSocket safe to expose at all. */
  function requestToken() {
    return fetch('/console/' + encodeURIComponent(config.deviceId) + '/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ credential_ref: chosenCredential() })
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) { throw new Error(data.error || 'Atlas refused the console request.'); }
        return data;
      });
    });
  }

  function socketUrl(token) {
    var scheme = global.location.protocol === 'https:' ? 'wss://' : 'ws://';
    return scheme + global.location.host + '/console/attach/'
      + encodeURIComponent(config.deviceId) + '?token=' + encodeURIComponent(token);
  }

  function onHostKeyProblem(payload) {
    var hostKey = payload.host_key || {};
    if (payload.state === 'host-key-changed') {
      /* Deliberately no "connect anyway" here. A changed host key is either a
         rebuild or an interception, and Atlas cannot tell which. Accepting is
         a separate, explicit act after seeing both fingerprints. */
      showAlert('SSH host key changed', payload.reason, [
        { label: 'Review and trust the new key', onClick: acceptHostKey },
        { label: 'Cancel', onClick: hideAlert }
      ], hostKey);
      setState('Blocked', 'failed');
      return;
    }
    showAlert('Unrecognised SSH host key', payload.reason, [
      { label: 'Accept this fingerprint', onClick: acceptHostKey },
      { label: 'Cancel', onClick: hideAlert }
    ], hostKey);
    setState('Host key unknown', 'failed');
  }

  function acceptHostKey() {
    /* Trust the key the operator was SHOWN, not whatever the device offers
       now: the server re-probes and refuses if they differ. */
    var shown = el('fp-new').textContent;
    fetch('/console/' + encodeURIComponent(config.deviceId) + '/hostkey/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ fingerprint: shown })
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) { throw new Error(data.error || 'Atlas could not accept that key.'); }
        hideAlert();
        connect();
      });
    }).catch(function (error) {
      showAlert('Could not accept the host key', error.message, [
        { label: 'Dismiss', onClick: hideAlert }
      ]);
    });
  }

  function handleMessage(payload) {
    if (payload.type === 'output') {
      term.write(payload.data);
      return;
    }
    if (payload.type === 'status') {
      if (payload.state === 'connecting') { setState('Connecting', 'running'); }
      if (payload.state === 'connected') {
        sessionId = payload.session_id;
        openedAt = Date.now();
        setState('Connected', 'completed');
        el('btn-disconnect').disabled = false;
        el('btn-connect').disabled = true;
        hideAlert();
        durationTimer = global.setInterval(tickDuration, 1000);
        sendResize();
        term.focus();
      }
      return;
    }
    if (payload.type === 'closed') {
      if (payload.state === 'host-key-changed' || payload.state === 'host-key-unknown') {
        onHostKeyProblem(payload);
      } else {
        setState('Session ended', 'failed');
        term.writeln('\r\n\x1b[33m' + (payload.reason || 'The session ended.') + '\x1b[0m');
      }
      teardown();
    }
  }

  function teardown() {
    if (durationTimer) { global.clearInterval(durationTimer); durationTimer = null; }
    openedAt = null;
    sessionId = null;
    var disconnect = el('btn-disconnect');
    var connectBtn = el('btn-connect');
    if (disconnect) { disconnect.disabled = true; }
    if (connectBtn) { connectBtn.disabled = false; }
  }

  function sendResize() {
    if (!socket || socket.readyState !== 1 || !term) { return; }
    socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
  }

  function connect() {
    /* Never stack sessions. Reconnecting (or a double click that beat the
       disabled button) must not leave the previous SSH session holding a VTY
       line on the device while a second one opens beside it. */
    if (socket) {
      try { socket.close(); } catch (error) { /* already gone */ }
      socket = null;
      teardown();
    }
    hideAlert();
    setState('Connecting', 'running');
    term.clear();
    requestToken().then(function (data) {
      socket = new global.WebSocket(socketUrl(data.token));
      socket.onmessage = function (event) {
        var payload;
        try { payload = JSON.parse(event.data); } catch (error) { return; }
        handleMessage(payload);
      };
      socket.onclose = function () {
        if (openedAt) { setState('Session ended', 'failed'); }
        teardown();
      };
      socket.onerror = function () {
        /* The server closes the socket after explaining itself (a changed
           host key, a refused origin). That explanation is already on
           screen — a generic 'Connection failed' would bury the reason the
           operator actually needs. */
        if (el('console-alert').hidden) { setState('Connection failed', 'failed'); }
      };
    }).catch(function (error) {
      setState('Cannot connect', 'failed');
      showAlert('Atlas could not open a session', error.message, [
        { label: 'Retry', onClick: connect },
        { label: 'Device details', onClick: function () { global.location.href = '/topology'; } }
      ]);
    });
  }

  function disconnect() {
    if (socket && socket.readyState === 1) {
      socket.send(JSON.stringify({ type: 'disconnect' }));
      socket.close();
    }
    setState('Disconnected', 'queued');
    teardown();
  }

  function init(options) {
    config = options || {};
    if (!global.Terminal) { return; }
    term = new global.Terminal({
      convertEol: false,
      cursorBlink: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: 13,
      scrollback: 5000,
      theme: { background: '#0f172a', foreground: '#e2e8f0' }
    });
    try {
      fit = new global.FitAddon.FitAddon();
      term.loadAddon(fit);
    } catch (error) { fit = null; }
    term.open(el('terminal'));
    if (fit) { fit.fit(); }

    term.onData(function (data) {
      if (socket && socket.readyState === 1) {
        socket.send(JSON.stringify({ type: 'input', data: data }));
      }
    });

    global.addEventListener('resize', function () {
      if (fit) { fit.fit(); }
      sendResize();
    });

    /* A closed tab must not leave an SSH session holding a VTY line. The
       server also reaps it when the socket drops; this just makes it prompt. */
    global.addEventListener('beforeunload', function () {
      if (socket && socket.readyState === 1) { socket.close(); }
    });

    el('btn-connect').addEventListener('click', connect);
    el('btn-disconnect').addEventListener('click', disconnect);

    term.writeln('\x1b[90mAtlas Console — ' + (config.hostname || '') + ' ('
      + (config.managementIp || '') + ')\x1b[0m');
    term.writeln('\x1b[90mPress Connect to open an interactive SSH session.\x1b[0m');
  }

  global.AtlasConsole = { init: init, connect: connect, disconnect: disconnect };
}(window));
