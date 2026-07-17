// Atlas entity picker — accessible async combobox, no framework.
//
// Replaces giant <select> lists: results are fetched as you type from
// /api/entities (devices, sites) or /api/device-interfaces, so the DOM
// never holds the whole estate. Keyboard: arrows move, Enter picks,
// Escape closes. The picked value lands in a hidden input the form
// submits; the server re-validates everything.
//
// Usage:
//   <div class="entity-picker" data-picker
//        data-kind="device"            (device | site | interface)
//        data-name="source"            (hidden input name)
//        data-required="1"
//        data-device-from="source"     (interface pickers: name of the
//                                       picker whose device scopes them)
//        data-value="core1">           (optional initial value)
(function () {
  "use strict";

  var RECENT_KEY = "atlas-picker-recent";
  var DEBOUNCE_MS = 180;

  function recentFor(kind) {
    try {
      var all = JSON.parse(localStorage.getItem(RECENT_KEY) || "{}");
      return Array.isArray(all[kind]) ? all[kind] : [];
    } catch (error) { return []; }
  }

  function rememberRecent(kind, value) {
    try {
      var all = JSON.parse(localStorage.getItem(RECENT_KEY) || "{}");
      var list = Array.isArray(all[kind]) ? all[kind] : [];
      list = [value].concat(list.filter(function (item) { return item !== value; }));
      all[kind] = list.slice(0, 6);
      localStorage.setItem(RECENT_KEY, JSON.stringify(all));
    } catch (error) { /* private mode: recents are a convenience */ }
  }

  function scopeParam() {
    var params = new URLSearchParams(window.location.search);
    return params.get("scope") ? "&scope=" + encodeURIComponent(params.get("scope")) : "";
  }

  function init(root) {
    var kind = root.dataset.kind || "device";
    var name = root.dataset.name;
    var listId = "picker-list-" + name + "-" + Math.random().toString(36).slice(2, 7);

    var hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = name;
    hidden.value = root.dataset.value || "";

    var input = document.createElement("input");
    input.type = "text";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", listId);
    input.setAttribute("aria-autocomplete", "list");
    input.autocomplete = "off";
    input.placeholder = root.dataset.placeholder ||
      (kind === "interface" ? "Type to search interfaces…" : "Type to search…");
    input.value = root.dataset.value || "";
    if (root.dataset.required) { input.required = true; }

    var list = document.createElement("ul");
    list.className = "picker-list";
    list.id = listId;
    list.setAttribute("role", "listbox");
    list.hidden = true;

    var status = document.createElement("span");
    status.className = "visually-hidden";
    status.setAttribute("aria-live", "polite");

    root.append(hidden, input, list, status);

    var options = [];
    var active = -1;
    var timer = null;

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      active = -1;
    }

    function render(items, note) {
      list.textContent = "";
      options = items;
      items.forEach(function (item, index) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.id = listId + "-" + index;
        li.innerHTML = "<strong></strong> <span class='muted'></span>";
        li.querySelector("strong").textContent = item.label;
        li.querySelector("span").textContent = item.detail || "";
        li.addEventListener("mousedown", function (event) {
          event.preventDefault();
          pick(index);
        });
        list.appendChild(li);
      });
      if (note) {
        var noteLi = document.createElement("li");
        noteLi.className = "picker-note muted";
        noteLi.setAttribute("role", "presentation");
        noteLi.textContent = note;
        list.appendChild(noteLi);
      }
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      status.textContent = items.length + " result(s)";
    }

    function pick(index) {
      var item = options[index];
      if (!item) { return; }
      hidden.value = item.value;
      input.value = item.label;
      rememberRecent(kind, item.value);
      close();
      input.dispatchEvent(new CustomEvent("picker:change", {
        bubbles: true, detail: { name: name, value: item.value }
      }));
    }

    function endpoint(query) {
      if (kind === "interface") {
        var deviceFrom = root.dataset.deviceFrom;
        var device = deviceFrom
          ? (document.querySelector('input[type="hidden"][name="' + deviceFrom + '"]') || {}).value || ""
          : "";
        if (!device) { return null; }
        return "/api/device-interfaces?device=" + encodeURIComponent(device) + scopeParam();
      }
      return "/api/entities?kind=" + encodeURIComponent(kind) +
             "&q=" + encodeURIComponent(query) + scopeParam();
    }

    function search() {
      var query = input.value.trim();
      var url = endpoint(query);
      if (url === null) {
        render([], "Pick the device first — its interfaces load then.");
        return;
      }
      fetch(url).then(function (response) {
        if (!response.ok) { throw new Error("HTTP " + response.status); }
        return response.json();
      }).then(function (data) {
        var items = (data.results || []).filter(function (item) {
          return !query || (item.label + " " + (item.detail || ""))
            .toLowerCase().indexOf(query.toLowerCase()) !== -1;
        });
        var extra = data.total > items.length
          ? (data.total - items.length) + " more — keep typing to narrow"
          : "";
        if (!items.length) {
          render([], query ? "No match in this scope's evidence." :
            "Nothing discovered yet in this scope.");
          return;
        }
        render(items, extra);
      }).catch(function () {
        render([], "Search failed — check the connection and try again.");
      });
    }

    input.addEventListener("input", function () {
      hidden.value = "";        // typing invalidates the previous pick
      clearTimeout(timer);
      timer = setTimeout(search, DEBOUNCE_MS);
    });
    input.addEventListener("focus", function () {
      if (!input.value) {
        var recents = recentFor(kind);
        if (recents.length) {
          render(recents.map(function (value) {
            return { value: value, label: value, detail: "recent" };
          }), "Recent picks — type to search everything.");
          return;
        }
      }
      search();
    });
    input.addEventListener("blur", function () { setTimeout(close, 120); });
    input.addEventListener("keydown", function (event) {
      if (list.hidden) { return; }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        var delta = event.key === "ArrowDown" ? 1 : -1;
        active = Math.max(0, Math.min(options.length - 1, active + delta));
        Array.prototype.forEach.call(list.children, function (li, index) {
          li.setAttribute("aria-selected", String(index === active));
        });
        input.setAttribute("aria-activedescendant", listId + "-" + active);
      } else if (event.key === "Enter" && active >= 0) {
        event.preventDefault();
        pick(active);
      } else if (event.key === "Escape") {
        close();
      }
    });

    // Free-typed values still submit (the server validates); copy the
    // text into the hidden input when no explicit pick was made.
    var form = root.closest("form");
    if (form) {
      form.addEventListener("submit", function () {
        if (!hidden.value && input.value.trim()) {
          hidden.value = input.value.trim();
        }
      });
    }
  }

  Array.prototype.forEach.call(
    document.querySelectorAll("[data-picker]"), init
  );
})();
