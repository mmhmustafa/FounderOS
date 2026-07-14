/*
 * Behaviour for the universal device action (PR-044A, CONSOLE).
 *
 * The action macro (_device_actions.html) renders on Console, Topology, the
 * enterprise inventory, Device details, Configuration, Paths and Advisor.
 * Its behaviour has to be just as universal, so this loads from base.html on
 * every page.
 *
 * It previously lived in atlas-console.js, which only the terminal page
 * loads — so Copy SSH Command was dead everywhere else. One implementation,
 * one place, every page.
 */
(function () {
  'use strict';

  function flash(button, message, restore) {
    button.textContent = message;
    window.setTimeout(function () { button.textContent = restore; }, 1400);
  }

  /* The last-resort path: a hidden textarea + execCommand. Deprecated, but it
     works without the async clipboard's focus/permission requirements. */
  function copyViaTextarea(text) {
    var scratch = document.createElement('textarea');
    scratch.value = text;
    scratch.setAttribute('readonly', '');
    scratch.style.position = 'fixed';
    scratch.style.top = '-1000px';
    scratch.style.opacity = '0';
    document.body.appendChild(scratch);
    var selection = document.getSelection();
    var previous = selection.rangeCount ? selection.getRangeAt(0) : null;
    scratch.select();
    var copied = false;
    try {
      copied = document.execCommand('copy');
    } catch (error) {
      copied = false;
    }
    document.body.removeChild(scratch);
    if (previous) { selection.removeAllRanges(); selection.addRange(previous); }
    return copied;
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest ? event.target.closest('.js-copy-ssh') : null;
    if (!button) { return; }
    event.preventDefault();

    var command = button.getAttribute('data-ssh-command') || '';
    var restore = button.getAttribute('data-restore-label') || button.textContent;
    button.setAttribute('data-restore-label', restore);

    if (!command || command === 'None') {
      /* Atlas has no verified endpoint for this device, so there is no
         honest command to give. Say so rather than copying "None". */
      flash(button, 'No SSH endpoint', restore);
      return;
    }

    /* The async clipboard needs a secure context, a focused document, and
       permission. Any of those can fail — and a failure must NOT be reported
       as success, which is what reporting both outcomes through one callback
       used to do. Fall back, then tell the truth. */
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(command).then(
        function () { flash(button, 'Copied', restore); },
        function () {
          if (copyViaTextarea(command)) {
            flash(button, 'Copied', restore);
          } else {
            flash(button, 'Press Ctrl+C', restore);
            window.prompt('Copy the SSH command:', command);
          }
        }
      );
      return;
    }
    if (copyViaTextarea(command)) {
      flash(button, 'Copied', restore);
    } else {
      flash(button, 'Press Ctrl+C', restore);
      window.prompt('Copy the SSH command:', command);
    }
  });

  /* Copy a management URL (HTTPS or HTTP). Same honesty as Copy SSH: never a
     credential, and never a false "Copied". */
  document.addEventListener('click', function (event) {
    var button = event.target.closest ? event.target.closest('.js-copy-url') : null;
    if (!button) { return; }
    event.preventDefault();
    var url = button.getAttribute('data-url') || '';
    var restore = button.getAttribute('data-restore-label') || button.textContent;
    button.setAttribute('data-restore-label', restore);
    if (!url) { flash(button, 'No URL', restore); return; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(
        function () { flash(button, 'Copied', restore); },
        function () {
          if (copyViaTextarea(url)) { flash(button, 'Copied', restore); }
          else { flash(button, 'Press Ctrl+C', restore); window.prompt('Copy the URL:', url); }
        }
      );
      return;
    }
    if (copyViaTextarea(url)) { flash(button, 'Copied', restore); }
    else { flash(button, 'Press Ctrl+C', restore); window.prompt('Copy the URL:', url); }
  });

  /* Audit that a web management interface was opened. The <a> opens the tab
     itself (target=_blank); this only records that it happened. Never a
     credential, cookie, or anything typed into the device. */
  function auditWebOpen(deviceId, protocol, url) {
    if (!deviceId) { return; }
    fetch('/management/' + encodeURIComponent(deviceId) + '/opened', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ url: url, protocol: protocol })
    }).catch(function () { /* audit is best-effort; never block the open */ });
  }

  document.addEventListener('click', function (event) {
    var link = event.target.closest ? event.target.closest('.js-web-open') : null;
    if (!link) { return; }
    /* The browser follows the href and shows its OWN TLS warning if the cert
       is bad — Atlas never suppresses it. We only record the intent. */
    auditWebOpen(link.getAttribute('data-device-id'),
                 link.getAttribute('data-protocol'),
                 link.getAttribute('data-url'));
  });

  /* HTTP is insecure. Confirm before the first insecure open for a device,
     then open in a new tab and audit it. */
  var insecureConfirmed = {};
  document.addEventListener('click', function (event) {
    var button = event.target.closest ? event.target.closest('.js-web-open-insecure') : null;
    if (!button) { return; }
    event.preventDefault();
    var deviceId = button.getAttribute('data-device-id');
    var url = button.getAttribute('data-url');
    var host = button.getAttribute('data-hostname') || deviceId;
    if (!insecureConfirmed[deviceId]) {
      var ok = window.confirm(
        'HTTP is insecure. Anything you type into ' + host + "'s web interface "
        + '— including a password — travels in the clear and can be read on the '
        + 'network.\n\nOpen ' + url + ' anyway?'
      );
      if (!ok) { return; }
      insecureConfirmed[deviceId] = true;
    }
    auditWebOpen(deviceId, 'http', url);
    window.open(url, '_blank', 'noopener,noreferrer');
  });

  /* Disconnect a live session from the console index. */
  document.addEventListener('click', function (event) {
    var button = event.target.closest ? event.target.closest('.js-disconnect') : null;
    if (!button) { return; }
    event.preventDefault();
    var id = button.getAttribute('data-session');
    if (!id) { return; }
    button.disabled = true;
    fetch('/console/sessions/' + encodeURIComponent(id) + '/disconnect', {
      method: 'POST', credentials: 'same-origin'
    }).then(function () {
      window.location.reload();
    }, function () {
      button.disabled = false;
    });
  });
}());
