// Atlas local GUI — progressive enhancement only. No framework.
//
// Discovery jobs: the Discover form posts to /api/discovery/jobs and the
// page polls /api/discovery/jobs/<id> every 1.5s. Without JavaScript the
// form falls back to the synchronous /discovery/run route. The browser
// only ever handles profile identity and safe job metadata — credentials
// are resolved on the server and never reach this code.
(function () {
  "use strict";

  var POLL_MS = 1500;

  function byId(id) { return document.getElementById(id); }

  function setText(id, value) {
    var node = byId(id);
    if (node) node.textContent = value === null || value === undefined ? "—" : String(value);
  }

  function show(id, visible) {
    var node = byId(id);
    if (node) node.hidden = !visible;
  }

  function scopeHref(path, profileId) {
    return path + "?scope=" + encodeURIComponent(profileId);
  }

  function renderJob(job) {
    var panel = byId("job-panel");
    if (!panel) return;
    panel.hidden = false;
    panel.dataset.jobId = job.job_id;
    panel.dataset.status = job.status;
    setText("job-title", "Discovering " + job.profile_name);
    setText("job-badge", job.status);
    var badge = byId("job-badge");
    if (badge) badge.className = "badge job-badge job-badge-" + job.status;
    setText("job-stage", "Stage " + job.stage_number + " of " + job.total_stages + " — " + job.stage);
    setText("job-message", job.message);
    setText("job-devices", job.devices_discovered);
    setText("job-device", job.current_device || "—");
    setText("job-elapsed", job.elapsed_seconds === null || job.elapsed_seconds === undefined
      ? "—" : job.elapsed_seconds + "s");
    var bar = byId("job-bar");
    if (bar) bar.style.width = job.percent + "%";
    var events = byId("job-events");
    if (events && job.events) events.textContent = job.events.join("\n");
    show("job-failure", Boolean(job.error));
    if (job.error) setText("job-failure", job.error);
    var done = job.status === "completed";
    show("job-summary", done && Boolean(job.summary));
    if (done && job.summary) {
      setText("job-summary-title", job.message);
      setText("summary-network", job.profile_name);
      setText("summary-devices", job.summary.devices);
      setText("summary-relationships", job.summary.relationships);
      setText("summary-configs", job.summary.configurations_collected);
      setText("summary-duration", job.summary.duration_seconds + " seconds");
      show("job-warning", Boolean(job.warning));
      if (job.warning) setText("job-warning", job.warning);
      var topology = byId("action-topology");
      var changes = byId("action-changes");
      var dashboard = byId("action-dashboard");
      if (topology) topology.href = scopeHref("/topology", job.profile_id);
      if (changes) changes.href = scopeHref("/changes", job.profile_id);
      if (dashboard) dashboard.href = scopeHref("/", job.profile_id);
    }
    var button = byId("discovery-run");
    if (button) {
      var active = job.status === "queued" || job.status === "running";
      button.disabled = active;
      button.textContent = active ? "Discovery running…" : "Run Discovery";
    }
  }

  function poll(jobId) {
    fetch("/api/discovery/jobs/" + encodeURIComponent(jobId))
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        if (!payload.job) return;
        renderJob(payload.job);
        if (payload.job.status === "queued" || payload.job.status === "running") {
          window.setTimeout(function () { poll(jobId); }, POLL_MS);
        }
      })
      .catch(function () {
        // Transient polling failure (e.g. server briefly busy): retry.
        window.setTimeout(function () { poll(jobId); }, POLL_MS * 2);
      });
  }

  function startJob(profileName) {
    var body = new URLSearchParams();
    body.set("profile", profileName);
    fetch("/api/discovery/jobs", { method: "POST", body: body })
      .then(function (response) {
        return response.json().then(function (payload) {
          return { status: response.status, payload: payload };
        });
      })
      .then(function (result) {
        show("job-error", false);
        if (result.payload.job) {
          // 202 created or 409 already running: either way, attach to it.
          renderJob(result.payload.job);
          poll(result.payload.job.job_id);
        } else if (result.payload.error) {
          setText("job-error", result.payload.error);
          show("job-error", true);
        }
      })
      .catch(function () {
        setText("job-error", "Could not reach the Atlas server. Is it still running?");
        show("job-error", true);
      });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.id === "discovery-form" && window.fetch) {
      event.preventDefault();
      var select = byId("discovery-profile");
      if (select && select.value) startJob(select.value);
      return;
    }
    // Other forms: guard against double-submits of the primary action.
    var button = form.querySelector('button[type="submit"].btn-primary');
    if (button) button.disabled = true;
  });

  // Re-attach to an in-flight job after refresh or navigation.
  var panel = byId("job-panel");
  if (panel && panel.dataset.jobId) {
    var status = panel.dataset.status;
    if (status === "queued" || status === "running") poll(panel.dataset.jobId);
  }

  // Predict page: the interface dropdown only offers the selected device's
  // discovered interfaces (labels keep the device prefix hidden once
  // filtered). The server re-validates the pairing regardless.
  var predictDevice = byId("predict-device");
  var predictInterface = byId("predict-interface");
  if (predictDevice && predictInterface) {
    var filterInterfaces = function () {
      var device = predictDevice.value;
      var visible = 0;
      Array.prototype.forEach.call(predictInterface.options, function (option) {
        if (!option.dataset.device) {
          option.hidden = true;  // the "select a device first" placeholder
          return;
        }
        var matches = option.dataset.device === device;
        option.hidden = !matches;
        option.disabled = !matches;
        if (matches) {
          visible += 1;
          // Drop the device prefix once the device is chosen.
          if (!option.dataset.shortLabel) {
            option.dataset.shortLabel = option.textContent.replace(
              option.dataset.device + " — ", ""
            );
          }
          option.textContent = option.dataset.shortLabel;
        }
      });
      predictInterface.value = "";
      var note = byId("predict-no-interfaces");
      if (note) note.hidden = visible > 0;
      predictInterface.disabled = visible === 0;
    };
    predictDevice.addEventListener("change", filterInterfaces);
    if (predictDevice.value) filterInterfaces();
  }
})();
