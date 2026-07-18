// Discovery operations console — external module, CSP-strict.
//
// Renders live pooled-discovery state from /api/discovery/execution/demo
// into the ops-* elements. Guarded: does nothing on pages without the
// console markup.
  (function () {
    "use strict";
    var $ = function (id) { return document.getElementById(id); };
    if (!$("ops-state")) { return; }
    var setText = function (el, v) { if (el) el.textContent = (v === null || v === undefined) ? "—" : String(v); };
    var fmtDuration = function (s) {
      if (s === null || s === undefined) return "—";
      s = Math.round(s);
      if (s < 60) return s + "s";
      return Math.floor(s / 60) + "m " + (s % 60) + "s";
    };
    var escapeHtml = function (v) { var d = document.createElement("div"); d.textContent = String(v == null ? "" : v); return d.innerHTML; };

    function render(snap) {
      var running = snap.state === "running" || snap.state === "inventory-pass" || snap.state === "deep-discovery-pass" || snap.state === "paused";
      var badge = $("ops-state");
      setText(badge, snap.state);
      badge.className = "badge job-badge job-badge-" + (snap.state === "completed" ? "completed" : (snap.state === "cancelled" || snap.state === "failed") ? "failed" : "running");
      if (snap.network) setText($("ops-network"), snap.network);
      var m = snap.metrics || {};
      setText($("ops-elapsed"), fmtDuration(m.elapsed_seconds));
      setText($("ops-eta"), snap.eta_seconds ? fmtDuration(snap.eta_seconds) : "—");
      setText($("ops-rate"), (m.devices_per_minute || 0) + " dev/min");
      $("ops-bar").style.width = (snap.progress_percent || 0) + "%";
      setText($("ops-progress-label"), (snap.processed || 0) + " / " + (snap.total || 0) + " devices");
      setText($("ops-progress-count"), (snap.processed || 0) + " / " + (snap.total || 0));
      setText($("ops-progress-pct"), (snap.progress_percent || 0) + "%");
      setText($("ops-card-rate").firstChild, (m.devices_per_minute || 0));
      setText($("ops-card-workers"), (m.worker_count || 0) + " / " + (m.worker_count || 0));
      setText($("ops-card-util"), (m.worker_utilization_percent || 0) + "%");

      // metric bindings
      Array.prototype.forEach.call(document.querySelectorAll("[data-metric]"), function (el) {
        var key = el.getAttribute("data-metric");
        var v = m[key];
        if (key.indexOf("seconds") >= 0 && typeof v === "number") v = v.toFixed(2) + "s";
        if (key === "worker_utilization_percent") v = (v || 0) + "%";
        setText(el, v);
      });

      // current activity: first busy worker
      var busy = (snap.workers || []).filter(function (w) { return !w.idle; });
      if (busy.length) {
        setText($("ops-current").querySelector(".ops-big-sm"), "Worker " + busy[0].worker_id);
        setText($("ops-current-detail"), busy[0].address + " · " + (busy[0].stage || ""));
      } else {
        setText($("ops-current").querySelector(".ops-big-sm"), running ? "—" : "Complete");
        setText($("ops-current-detail"), running ? "Waiting…" : "All candidates processed");
      }

      // workers
      var workers = $("ops-workers");
      workers.innerHTML = "";
      var alive = 0;
      (snap.workers || []).forEach(function (w) {
        if (!w.idle) alive++;
        var li = document.createElement("li");
        li.className = "ops-worker" + (w.idle ? " idle" : "");
        li.innerHTML = '<span class="ops-worker-id">W' + w.worker_id + '</span>' +
          (w.idle ? '<span class="muted">Idle</span>' :
            '<span class="ops-worker-addr">' + escapeHtml(w.address) + '</span><span class="ops-worker-stage">' + escapeHtml(w.stage || "") + '</span>');
        workers.appendChild(li);
      });
      setText($("ops-worker-summary"), alive + " / " + (snap.workers || []).length + " active");

      // queue
      var queue = $("ops-queue");
      queue.innerHTML = "";
      var byOutcome = (snap.queue || {}).by_outcome || {};
      [["queued","Queued"],["running","Running"],["discovered","Completed"],["authentication-failed","Auth failed"],["unsupported-platform","Unsupported"],["unreachable","Failed"],["cancelled","Cancelled"]].forEach(function (pair) {
        if (byOutcome[pair[0]] === undefined) return;
        var li = document.createElement("li");
        li.innerHTML = '<span>' + pair[1] + '</span><strong>' + byOutcome[pair[0]] + '</strong>';
        queue.appendChild(li);
      });

      // pipeline highlight (by slowest/current known stage)
      var stage = (busy[0] && busy[0].stage) || "";
      Array.prototype.forEach.call($("ops-pipeline").children, function (li) {
        li.classList.toggle("active", stage.indexOf(li.getAttribute("data-stage").replace("_", " ")) >= 0);
      });

      // live inventory (nodes with role stencils)
      var inv = $("ops-inventory");
      inv.innerHTML = "";
      (snap.nodes || []).forEach(function (n) {
        var card = document.createElement("div");
        card.className = "ops-node";
        card.title = (n.role || "unknown") + " — " + (n.role_evidence || "");
        card.innerHTML = (n.stencil ? '<img alt="' + escapeHtml(n.role) + '" src="' + n.stencil + '">' : '') +
          '<div><strong>' + escapeHtml(n.hostname) + '</strong><span class="muted">' + escapeHtml(n.platform) + '</span></div>';
        inv.appendChild(card);
      });
      setText($("ops-inventory-count"), (snap.nodes || []).length + " device(s)");

      // log
      var log = $("ops-logstream");
      log.innerHTML = "";
      (snap.log || []).slice().reverse().forEach(function (e) {
        var ok = e.message.toLowerCase().indexOf("fail") < 0 && e.message.toLowerCase().indexOf("unreachable") < 0;
        var li = document.createElement("li");
        li.innerHTML = '<span class="ops-log-mark ' + (ok ? "ok" : "bad") + '">' + (ok ? "✓" : "✗") + '</span>' +
          '<span class="ops-log-addr">' + escapeHtml(e.address) + '</span>' +
          '<span class="activity-kind">' + escapeHtml(e.platform || "—") + '</span>' +
          '<span class="muted">' + escapeHtml(e.message) + '</span>';
        log.appendChild(li);
      });

      // complete state
      var done = snap.state === "completed";
      $("ops-complete").hidden = !done;
      if (done) {
        setText($("ops-complete-summary"),
          m.discovered + " device(s) discovered across " + m.addresses_evaluated + " address(es) — " +
          m.authentication_failures + " auth failure(s), " + m.unreachable + " unreachable. " +
          "First device usable in " + fmtDuration(snap.time_to_first_device_seconds) + ".");
      }
    }

    function load() {
      var url = new URLSearchParams(window.location.search).get("state") === "running"
        ? "/api/discovery/execution/demo?state=running"
        : "/api/discovery/execution/demo";
      fetch(url).then(function (r) { return r.json(); }).then(render)
        .catch(function () { $("ops-current-detail").textContent = "No discovery running."; });
    }
    load();

    // Controls (keyboard: p pause, r resume, s stop)
    var note = $("ops-control-note");
    function control(name) { setText(note, "Control sent: " + name); }
    ["resume","pause","stop","restart"].forEach(function (a) {
      var b = $("ops-" + a); if (b) b.addEventListener("click", function () { control(a); });
    });
    document.addEventListener("keydown", function (e) {
      if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
      if (e.key === "p") control("pause");
      else if (e.key === "r") control("resume");
      else if (e.key === "s") control("stop");
    });
  })();
