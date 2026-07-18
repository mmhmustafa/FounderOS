// Atlas chip editor — accessible structured multi-value input, CSP-strict.
//
// Progressive enhancement over a plain text input: the ORIGINAL input is
// kept (name preserved) and hidden, and the server still receives the
// same comma/whitespace-joined string it always did, so stored records
// and server-side validation are untouched and backward-compatible.
// Without JavaScript the original input remains fully usable.
//
// Usage: <input ... data-chips data-chip-kind="cidr"> (kind optional:
// cidr | ip | hostname | tag | plain — drives light client validation;
// the server remains authoritative).
//
// Keyboard: type + Enter/comma to add; Backspace on an empty field
// removes the last chip; each chip's × is a real button; paste splits
// on commas/whitespace/newlines. Duplicates (case-insensitive) are
// rejected with an accessible message.
(function () {
  "use strict";

  var SPLIT = /[\s,;]+/;

  function normalize(kind, value) {
    var v = value.trim();
    if (!v) { return ""; }
    if (kind === "hostname" || kind === "tag" || kind === "platform" ||
        kind === "vendor" || kind === "role") {
      return v.toLowerCase();
    }
    return v;
  }

  function validate(kind, value) {
    if (kind === "ip" || kind === "cidr") {
      var host = value.split("/")[0];
      var octets = host.split(".");
      if (octets.length !== 4 ||
          !octets.every(function (o) {
            return /^\d+$/.test(o) && Number(o) >= 0 && Number(o) <= 255;
          })) {
        return "Not a valid IPv4 address.";
      }
      if (kind === "cidr" && value.indexOf("/") !== -1) {
        var bits = Number(value.split("/")[1]);
        if (!(bits >= 0 && bits <= 32)) { return "CIDR prefix must be 0–32."; }
      }
    }
    return null;
  }

  function build(input) {
    var kind = input.dataset.chipKind || "plain";
    var wrap = document.createElement("div");
    wrap.className = "chips";
    var list = document.createElement("ul");
    list.className = "chip-list";
    list.setAttribute("role", "list");
    var entry = document.createElement("input");
    entry.type = "text";
    entry.className = "chip-entry";
    entry.setAttribute("aria-label",
      (input.getAttribute("aria-label") || input.name) + " — type a value and press Enter");
    entry.autocomplete = "off";
    if (input.placeholder) { entry.placeholder = input.placeholder; }
    var status = document.createElement("span");
    status.className = "chip-status muted";
    status.setAttribute("aria-live", "polite");

    var values = [];

    function sync() {
      input.value = values.join(", ");
    }

    function render() {
      list.textContent = "";
      values.forEach(function (value, index) {
        var li = document.createElement("li");
        li.className = "chip";
        var label = document.createElement("span");
        label.textContent = value;
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "chip-remove";
        remove.setAttribute("aria-label", "Remove " + value);
        remove.textContent = "×";
        remove.addEventListener("click", function () {
          values.splice(index, 1);
          render();
          sync();
          entry.focus();
        });
        li.append(label, remove);
        list.appendChild(li);
      });
    }

    function add(raw) {
      var value = normalize(kind, raw);
      if (!value) { return; }
      var problem = validate(kind, value);
      if (problem) { status.textContent = problem; return; }
      if (values.some(function (v) { return v.toLowerCase() === value.toLowerCase(); })) {
        status.textContent = value + " is already in the list.";
        return;
      }
      values.push(value);
      status.textContent = "";
      render();
      sync();
    }

    (input.value || "").split(SPLIT).forEach(function (v) {
      var value = normalize(kind, v);
      if (value && !values.some(function (x) { return x.toLowerCase() === value.toLowerCase(); })) {
        values.push(value);
      }
    });
    render();
    sync();

    entry.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === ",") {
        event.preventDefault();
        add(entry.value);
        entry.value = "";
      } else if (event.key === "Backspace" && !entry.value && values.length) {
        values.pop();
        render();
        sync();
      }
    });
    entry.addEventListener("blur", function () {
      if (entry.value.trim()) { add(entry.value); entry.value = ""; }
    });
    entry.addEventListener("paste", function (event) {
      var text = (event.clipboardData || window.clipboardData).getData("text");
      if (text && SPLIT.test(text)) {
        event.preventDefault();
        text.split(SPLIT).forEach(add);
        entry.value = "";
      }
    });

    // Keep the original input in the DOM (form submits it) but hidden and
    // out of the tab order — the chips are the interactive surface.
    input.type = "hidden";
    input.setAttribute("aria-hidden", "true");
    input.parentNode.insertBefore(wrap, input.nextSibling);
    wrap.append(list, entry, status);
  }

  Array.prototype.forEach.call(
    document.querySelectorAll("input[data-chips]"), build
  );
})();
