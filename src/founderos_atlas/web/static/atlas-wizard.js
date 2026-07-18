// Discovery Wizard behavior — external module, CSP-strict (no inline JS).
//
// The form and all four steps are server-rendered; without JavaScript the
// operator still has the classic /discovery form as the working fallback
// (linked on the page). This module adds staged progression, mode-specific
// field visibility, and credential-free draft autosaving.
//
// Hooks: #wizard-form[data-initial-step], .wizard-step[data-step],
// [data-prev]/[data-next], [data-mode-fields], [data-progress],
// [data-draft-jump] (resume-draft select).
(function () {
  "use strict";

  // Resume-draft jump: a <select> that navigates on choice. Delegated so it
  // works wherever the control renders.
  document.addEventListener("change", function (event) {
    var jump = event.target.closest("[data-draft-jump]");
    if (jump && jump.value) {
      window.location.href =
        "/discovery/wizard?draft=" + encodeURIComponent(jump.value);
    }
  });

  var form = document.getElementById("wizard-form");
  if (!form) { return; }

  var step = Number(form.dataset.initialStep || "1") || 1;
  var steps = Array.prototype.slice.call(
    document.querySelectorAll(".wizard-step")
  );
  var prev = document.querySelector("[data-prev]");
  var next = document.querySelector("[data-next]");

  function updateModes() {
    var mode = (form.elements.mode && form.elements.mode.value) || "seed";
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-mode-fields]"),
      function (el) { el.hidden = el.dataset.modeFields !== mode; }
    );
    var scope = mode === "management-network"
      ? (form.elements.cidr ? form.elements.cidr.value : "")
      : (mode === "seed"
        ? (form.elements.seed ? form.elements.seed.value : "")
        : "multiple candidates");
    var summary = document.getElementById("boundary-summary");
    if (summary) {
      summary.textContent = scope
        ? "Candidate scope: " + scope +
          ". Exclusions are validated before preview."
        : "Enter a scope to preview the permitted candidate region.";
    }
  }

  function show() {
    steps.forEach(function (section) {
      section.hidden = Number(section.dataset.step) !== step;
    });
    if (prev) { prev.hidden = step === 1; }
    if (next) { next.hidden = step === 4; }
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-progress]"),
      function (marker) {
        marker.classList.toggle(
          "active", Number(marker.dataset.progress) <= step
        );
      }
    );
    updateModes();
  }

  function save() {
    var data = {};
    new FormData(form).forEach(function (value, key) { data[key] = value; });
    delete data.password;           // drafts never contain credentials
    delete data._csrf;
    data.draft_id = form.elements.draft_id.value;
    return fetch("/api/discovery/wizard/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then(function (response) {
      if (!response.ok) { throw new Error("HTTP " + response.status); }
      return response.json();
    }).then(function (result) {
      form.elements.draft_id.value = result.draft_id;
      var status = document.getElementById("draft-status");
      if (status) {
        status.textContent = "Draft saved · credentials excluded";
      }
      window.history.replaceState(
        {}, "",
        "/discovery/wizard?draft=" + encodeURIComponent(result.draft_id)
      );
    }).catch(function () {
      var status = document.getElementById("draft-status");
      if (status) {
        status.textContent =
          "Draft could not be saved — continuing without autosave.";
      }
    });
  }

  if (next) {
    next.addEventListener("click", function () {
      var current = steps.find
        ? steps.find(function (s) { return Number(s.dataset.step) === step; })
        : null;
      var invalid = current ? current.querySelector(":invalid") : null;
      if (invalid) { invalid.reportValidity(); return; }
      save().then(function () {
        step = Math.min(4, step + 1);
        show();
      });
    });
  }
  if (prev) {
    prev.addEventListener("click", function () {
      step = Math.max(1, step - 1);
      show();
    });
  }
  form.addEventListener("change", updateModes);
  show();
})();
