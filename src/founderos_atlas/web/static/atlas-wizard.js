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

  function validIpv4(value) {
    var parts = value.split(".");
    if (parts.length !== 4) { return false; }
    return parts.every(function (part) {
      if (!/^\d{1,3}$/.test(part)) { return false; }
      if (part.length > 1 && part.charAt(0) === "0") { return false; }
      var number = Number(part);
      return number >= 0 && number <= 255;
    });
  }

  function validIpv6(value) {
    // This is deliberately a conservative syntax gate, not the security
    // authority. The Python ipaddress validator runs again at preview.
    if (!value || value === ":" || value.indexOf(":") < 0 ||
        !/^[0-9a-fA-F:.]+$/.test(value)) {
      return false;
    }
    var halves = value.split("::");
    if (halves.length > 2) { return false; }
    var groups = value.split(":").filter(function (item) { return item !== ""; });
    if (groups.length > 8 || (halves.length === 1 && groups.length !== 8) ||
        (halves.length === 2 && groups.length >= 8)) { return false; }
    return groups.every(function (group) {
      return validIpv4(group) || /^[0-9a-fA-F]{1,4}$/.test(group);
    });
  }

  function validAddress(value) {
    return validIpv4(value) || validIpv6(value);
  }

  function validNetwork(value) {
    var slash = value.lastIndexOf("/");
    if (slash <= 0 || slash === value.length - 1) { return false; }
    var address = value.slice(0, slash);
    var prefixText = value.slice(slash + 1);
    if (!/^\d{1,3}$/.test(prefixText) || !validAddress(address)) {
      return false;
    }
    var prefix = Number(prefixText);
    return prefix >= 0 && prefix <= (address.indexOf(":") >= 0 ? 128 : 32);
  }

  function setValidity(control, message) {
    if (control) { control.setCustomValidity(message || ""); }
    return !message;
  }

  function tokens(value) {
    return String(value || "").split(/[\s,]+/).filter(Boolean);
  }

  function validateAddressList(control, options) {
    if (!control) { return true; }
    var values = tokens(control.value);
    if (options.required && values.length === 0) {
      return setValidity(control, options.requiredMessage);
    }
    var invalid = values.find(function (value) {
      return !(validAddress(value) || (options.networks && validNetwork(value)));
    });
    return setValidity(
      control,
      invalid ? options.invalidMessage.replace("{value}", invalid) : ""
    );
  }

  function validateStep() {
    if (step === 1) {
      var mode = (form.elements.mode && form.elements.mode.value) || "seed";
      if (mode === "seed" && !validateAddressList(form.elements.seed, {
        required: true,
        requiredMessage: "Enter a seed IP address.",
        invalidMessage: "{value} is not a valid IP address."
      })) { return false; }
      if (mode === "management-network") {
        var cidr = form.elements.cidr;
        var cidrValue = String(cidr && cidr.value || "").trim();
        if (!setValidity(
          cidr,
          !cidrValue ? "Enter a management CIDR." :
            (!validNetwork(cidrValue) ? cidrValue + " is not a valid CIDR." : "")
        )) { return false; }
      }
      if (mode === "multiple-seeds" && !validateAddressList(form.elements.seeds, {
        required: true,
        requiredMessage: "Enter at least one seed IP address.",
        invalidMessage: "{value} is not a valid seed IP address."
      })) { return false; }
    }
    if (step === 3 && !validateAddressList(form.elements.exclusions, {
      required: false,
      networks: true,
      invalidMessage: "{value} is not a valid exclusion address or CIDR."
    })) { return false; }
    return true;
  }

  function save() {
    // Repeated fields (every selected credential set, multiple seeds)
    // must ALL survive into the draft — flattening to one value per key
    // was the bug that silently dropped every credential set but the
    // last. Collect any key that appears more than once as an array.
    var data = {};
    var multi = {};
    new FormData(form).forEach(function (value, key) {
      if (key === "password" || key === "_csrf") { return; }
      if (Object.prototype.hasOwnProperty.call(data, key)) {
        if (!multi[key]) { multi[key] = [data[key]]; }
        multi[key].push(value);
      } else {
        data[key] = value;
      }
    });
    Object.keys(multi).forEach(function (key) { data[key] = multi[key]; });
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
      if (!validateStep()) {
        var customInvalid = current ? current.querySelector(":invalid") : null;
        if (customInvalid) { customInvalid.reportValidity(); }
        return;
      }
      save().then(function () {
        step = Math.min(4, step + 1);
        show();
      });
    });
  }
  form.addEventListener("input", function (event) {
    if (event.target && typeof event.target.setCustomValidity === "function") {
      event.target.setCustomValidity("");
    }
  });
  if (prev) {
    prev.addEventListener("click", function () {
      step = Math.max(1, step - 1);
      show();
    });
  }
  form.addEventListener("change", updateModes);
  show();
})();
