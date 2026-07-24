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

  // -- CSRF -------------------------------------------------------------------
  // In production auth mode every mutating request must carry the session's
  // CSRF token (double submit against the server-side session). Wrapping
  // fetch here means every existing and future call site complies without
  // remembering to. Cross-origin requests are left untouched.
  (function installCsrf() {
    function token() {
      var meta = document.querySelector('meta[name="atlas-csrf"]');
      if (meta && meta.content) { return meta.content; }
      var match = document.cookie.match(/(?:^|; )atlas_csrf=([^;]*)/);
      return match ? decodeURIComponent(match[1]) : "";
    }
    var original = window.fetch;
    if (!original) { return; }
    window.fetch = function (input, init) {
      init = init || {};
      var method = (init.method || (input && input.method) || "GET").toUpperCase();
      var url = typeof input === "string" ? input : (input && input.url) || "";
      var sameOrigin = url.indexOf("://") === -1 || url.indexOf(window.location.origin) === 0;
      var value = token();
      if (value && sameOrigin && method !== "GET" && method !== "HEAD") {
        var headers = new Headers(init.headers || (input && input.headers) || {});
        if (!headers.has("X-Atlas-CSRF")) { headers.set("X-Atlas-CSRF", value); }
        init.headers = headers;
      }
      return original.call(window, input, init);
    };
  })();

  function byId(id) { return document.getElementById(id); }

  // -- Responsive tables ------------------------------------------------------
  // Any .grid table not already inside a labelled scroll region gets one:
  // deliberate horizontal scrolling on narrow screens, keyboard-reachable,
  // named after its nearest heading. Future pages inherit this without
  // remembering a wrapper.
  Array.prototype.forEach.call(
    document.querySelectorAll("table.grid"),
    function (table) {
      if (table.closest(".table-scroll")) return;
      var wrapper = document.createElement("div");
      wrapper.className = "table-scroll";
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute("tabindex", "0");
      var section = table.closest("section, .card, main");
      var heading = section && section.querySelector("h1, h2, h3");
      wrapper.setAttribute(
        "aria-label",
        (heading && heading.textContent.trim()) || "Data table"
      );
      table.parentNode.insertBefore(wrapper, table);
      wrapper.appendChild(table);
    }
  );

  // -- Entity action menus (_entity_actions.html) ----------------------------
  // Plain <details> popovers, enhanced: outside click and Escape close
  // them, only one stays open, and "Copy link" copies an ABSOLUTE stable
  // URL so a pasted link works from any browser.
  var closeMenus = function (except) {
    Array.prototype.forEach.call(
      document.querySelectorAll("details.action-menu[open]"),
      function (menu) { if (menu !== except) menu.removeAttribute("open"); }
    );
  };
  document.addEventListener("click", function (event) {
    var menu = event.target.closest && event.target.closest("details.action-menu");
    closeMenus(menu);
    var copy = event.target.closest && event.target.closest(".js-copy-link");
    if (copy) {
      var url = new URL(
        copy.getAttribute("data-copy-url") || "", window.location.origin
      ).toString();
      var done = function () {
        var original = copy.textContent;
        copy.textContent = "Link copied";
        window.setTimeout(function () { copy.textContent = original; }, 1200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done, done);
      } else {
        window.prompt("Copy this link:", url);
      }
      if (menu) menu.removeAttribute("open");
    }
  });
  // Escape handling lives in the SINGLE document-level keydown handler in
  // the search section below (one handler, one lifecycle).

  // -- Responsive navigation drawer ------------------------------------------
  // Below 1024px the sidebar is an off-canvas drawer. The toggle button
  // reflects state via aria-expanded; Escape, the backdrop, and following
  // a navigation link all close it. Focus returns to the toggle on close.
  // Escape is dispatched from the SINGLE document-level keydown handler
  // in the search section below (one handler, one lifecycle).
  var closeNavDrawer = null;
  var navToggle = byId("atlas-nav-toggle");
  var sidebar = byId("atlas-sidebar");
  var navBackdrop = byId("atlas-sidebar-backdrop");
  if (navToggle && sidebar && navBackdrop) {
    var navOpen = function () {
      document.body.classList.add("nav-open");
      navBackdrop.hidden = false;
      navToggle.setAttribute("aria-expanded", "true");
      navToggle.setAttribute("aria-label", "Close navigation menu");
      var first = sidebar.querySelector("a");
      if (first) first.focus();
    };
    var navClose = function (restoreFocus) {
      document.body.classList.remove("nav-open");
      navBackdrop.hidden = true;
      navToggle.setAttribute("aria-expanded", "false");
      navToggle.setAttribute("aria-label", "Open navigation menu");
      if (restoreFocus) navToggle.focus();
    };
    navToggle.addEventListener("click", function () {
      if (document.body.classList.contains("nav-open")) navClose(true);
      else navOpen();
    });
    navBackdrop.addEventListener("click", function () { navClose(false); });
    sidebar.addEventListener("click", function (event) {
      // Following a nav link navigates away; close so back-navigation
      // via bfcache never restores a stale open drawer.
      if (event.target.closest && event.target.closest("a")) navClose(false);
    });
    closeNavDrawer = navClose;
  }

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
    function sweepSummary(summary) {
      var swept = summary.addresses_scanned;
      if (swept == null) { return "—"; }   // older runs recorded no sweep
      var parts = [swept + " swept", summary.devices + " answered"];
      if (summary.addresses_without_device) {
        parts.push(
          summary.addresses_without_device + " silent (no device answered)"
        );
      }
      if (summary.auth_failed_devices) {
        parts.push(summary.auth_failed_devices + " refused credentials");
      }
      return parts.join(" · ");
    }
    show("job-summary", done && Boolean(job.summary));
    if (done && job.summary) {
      setText("job-summary-title", job.message);
      setText("summary-network", job.profile_name);
      setText("summary-devices", job.summary.devices);
      // Twelve devices out of a swept /24 reads as a failure until the
      // denominator is on screen. The run already separates a silent
      // address (no device there — coverage, not a fault) from a device
      // that refused credentials, so say both rather than leaving the
      // operator to wonder why a sweep "only contacted 12".
      setText("summary-sweep", sweepSummary(job.summary));
      setText("summary-relationships", job.summary.relationships);
      setText("summary-configs", job.summary.configurations_collected);
      setText("summary-platforms", job.summary.platforms || "—");
      setText("summary-physical", job.summary.physical_links ?? "—");
      setText("summary-adjacencies", job.summary.routing_adjacencies ?? "—");
      setText("summary-peers", job.summary.protocol_peers ?? "—");
      setText("summary-unresolved", job.summary.unresolved_peers ?? "—");
      // "73s", to match the elapsed counter above it — not "72.366208 seconds".
      var secs = job.summary.duration_seconds;
      setText("summary-duration", secs == null ? "—" : Math.round(secs) + "s");
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

  // The Networks table is server-rendered at page load, so a run finishing
  // beside it leaves it claiming "running" / "never". Re-fetch the page and
  // swap in that table's fresh body — a full reload would be simpler but would
  // throw away the results panel, which only exists because renderJob drew it.
  function refreshNetworksTable() {
    var body = byId("networks-body");
    if (!body || !window.fetch || !window.DOMParser) return;
    fetch(window.location.pathname + window.location.search, {
      credentials: "same-origin"
    })
      .then(function (response) { return response.text(); })
      .then(function (html) {
        var fresh = new DOMParser()
          .parseFromString(html, "text/html")
          .getElementById("networks-body");
        if (fresh) body.innerHTML = fresh.innerHTML;
      })
      .catch(function () { /* the stale table is not worth an error */ });
  }

  // The opt-in active pass: once a read-only discovery finishes, and only
  // if the operator ticked "measure link latency", ask each device to ping
  // its neighbour over SSH. It runs from the browser (in the operator's
  // session, host-key-verified and audited server-side) rather than in the
  // read-only discovery pipeline, so keeping this page open is what lets it
  // fire. Fires once per page.
  var latencyStarted = false;
  function maybeMeasureLatency(job) {
    if (latencyStarted || !job) return;
    if (job.status !== "completed" || !job.measure_latency) return;
    latencyStarted = true;
    var line = byId("summary-latency");
    show("summary-latency-row", true);
    if (line) line.textContent = "measuring… pinging each neighbour over SSH";
    fetch("/api/topology/measure-latency?scope=" + encodeURIComponent(job.profile_id), {
      method: "POST",
      credentials: "same-origin"
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return { status: response.status, body: body };
        });
      })
      .then(function (result) {
        if (!line) return;
        var b = result.body || {};
        if (result.status === 200) {
          var span = (b.rtt_ms_min != null && b.rtt_ms_max != null)
            ? b.rtt_ms_min + "–" + b.rtt_ms_max + " ms"
            : "no timed replies";
          var text = b.measured + " of " + b.considered + " links measured · " + span;
          var missed = (b.unreachable || []).length;
          if (missed) {
            text += " · " + missed + " unmeasured (a device needs an accepted "
              + "SSH host key — open its console to accept it, then re-measure)";
          }
          line.textContent = text;
        } else {
          // 409 and friends carry an operator-facing sentence; show it.
          line.textContent = b.error || "could not measure link latency";
        }
      })
      .catch(function () {
        if (line) {
          line.textContent = "could not reach the Atlas server to measure latency";
        }
      });
  }

  function poll(jobId) {
    fetch("/api/discovery/jobs/" + encodeURIComponent(jobId))
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        if (!payload.job) return;
        renderJob(payload.job);
        if (payload.job.status === "queued" || payload.job.status === "running") {
          window.setTimeout(function () { poll(jobId); }, POLL_MS);
        } else {
          // Terminal: the run just finished under this page.
          refreshNetworksTable();
          maybeMeasureLatency(payload.job);
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

  /*
   * A profile needs a way in — its own credential, or a credential set.
   *
   * Ticking a set makes the username/password optional: the set already
   * carries one, and the resolver has always accepted sets without a profile
   * default. Previously both fields stayed `required`, so choosing a saved
   * credential set still blocked the form on "Please fill out this field" —
   * for a credential the operator had already saved. The server enforces the
   * same rule; this only stops the browser refusing first.
   */
  (function () {
    var sets = document.querySelectorAll(".js-credential-set");
    var fields = document.querySelectorAll(".js-credential-optional");
    if (!sets.length || !fields.length) return;

    // A set is "chosen" whether it is ticked (the wizard's checkboxes) or
    // typed (the profile form's comma-separated ids). Same rule, both shapes.
    function anySetChosen() {
      return Array.prototype.some.call(sets, function (input) {
        return input.type === "checkbox" ? input.checked : Boolean(input.value.trim());
      });
    }
    function sync() {
      var preservesExisting = Array.prototype.some.call(fields, function (field) {
        var form = field.closest("form");
        return form && form.dataset.preserveCredential === "1";
      });
      var optional = preservesExisting || anySetChosen();
      Array.prototype.forEach.call(fields, function (field) {
        field.required = !optional;
        // The browser keeps a stale validity message until the value changes.
        if (optional && field.setCustomValidity) field.setCustomValidity("");
      });
      var hint = document.querySelector(".js-credential-hint");
      if (hint) hint.classList.toggle("credential-optional", optional);
    }
    Array.prototype.forEach.call(sets, function (input) {
      input.addEventListener("change", sync);
      input.addEventListener("input", sync);  // typed set ids
    });
    sync();  // a set may already be chosen on a re-render or an edit
  }());

  // Re-attach to an in-flight job after refresh or navigation.
  var panel = byId("job-panel");
  if (panel && panel.dataset.jobId) {
    var status = panel.dataset.status;
    if (status === "queued" || status === "running") poll(panel.dataset.jobId);
  }

  // Device-aware interface dropdowns (Predict, Compass, and any future
  // form): the interface select only offers the selected device's
  // discovered interfaces. Options carrying data-keep (e.g. "none /
  // device-level") stay available. The server re-validates regardless.
  function bindInterfaceFilter(deviceId, interfaceId, noteId, allowEmpty) {
    var deviceSelect = byId(deviceId);
    var interfaceSelect = byId(interfaceId);
    if (!deviceSelect || !interfaceSelect) return;
    var filterInterfaces = function () {
      var device = deviceSelect.value;
      var visible = 0;
      Array.prototype.forEach.call(interfaceSelect.options, function (option) {
        if (!option.dataset.device) {
          // Placeholder / "none" options: keep only when flagged.
          option.hidden = !option.dataset.keep;
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
      interfaceSelect.value = "";
      var note = byId(noteId);
      if (note) note.hidden = visible > 0;
      interfaceSelect.disabled = visible === 0 && !allowEmpty;
    };
    deviceSelect.addEventListener("change", filterInterfaces);
    if (deviceSelect.value) filterInterfaces();
  }
  bindInterfaceFilter("predict-device", "predict-interface", "predict-no-interfaces", false);
  bindInterfaceFilter("compass-device", "compass-interface", null, true);

  // Discovery wizard (PR-043.2): show only the selected method's fields.
  var wizardForm = byId("wizard-form");
  if (wizardForm) {
    var showMode = function () {
      var mode = (wizardForm.querySelector('input[name="mode"]:checked') || {}).value;
      Array.prototype.forEach.call(
        wizardForm.querySelectorAll(".wizard-fields"),
        function (block) { block.hidden = block.dataset.mode !== mode; }
      );
    };
    Array.prototype.forEach.call(
      wizardForm.querySelectorAll('input[name="mode"]'),
      function (radio) { radio.addEventListener("change", showMode); }
    );
    showMode();
  }

  // -- Universal search (PR-038) --------------------------------------------
  // Ctrl+K opens the overlay; results come from /api/search — deterministic,
  // evidence-based, grouped, ranked server-side. This code only renders.
  var searchOverlay = byId("atlas-search");
  var searchInput = byId("atlas-search-input");
  if (searchOverlay && searchInput) {
    var DEBOUNCE_MS = 150;
    var RECENT_KEY = "atlas-recent-searches";
    var searchTimer = null;
    var activeIndex = -1;
    var resultLinks = [];
    var lastFocused = null;

    // Lifecycle: the single overlay in base.html toggles via the `hidden`
    // attribute (with a matching CSS state) and mirrors aria-hidden.
    // Closing PRESERVES the last query and its results — deliberate UX:
    // reopening selects the text so the engineer can resume or overtype.
    var openSearch = function () {
      lastFocused = document.activeElement;
      searchOverlay.hidden = false;
      searchOverlay.setAttribute("aria-hidden", "false");
      renderRecent();
      searchInput.focus();
      searchInput.select();
    };
    var closeSearch = function () {
      searchOverlay.hidden = true;
      searchOverlay.setAttribute("aria-hidden", "true");
      activeIndex = -1;
      // Restore focus to whatever opened the modal, where practical.
      if (lastFocused && typeof lastFocused.focus === "function") {
        lastFocused.focus();
      }
    };

    // Focus trap: while the search dialog is open, Tab cycles within it.
    searchOverlay.addEventListener("keydown", function (event) {
      if (event.key !== "Tab" || searchOverlay.hidden) return;
      var focusable = searchOverlay.querySelectorAll(
        "input, a[href], button:not([disabled])"
      );
      if (!focusable.length) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    var recentSearches = function () {
      try {
        var raw = window.localStorage.getItem(RECENT_KEY);
        var list = raw ? JSON.parse(raw) : [];
        return Array.isArray(list) ? list : [];
      } catch (error) { return []; }
    };
    var rememberSearch = function (query) {
      if (!query) return;
      try {
        var list = recentSearches().filter(function (item) { return item !== query; });
        list.unshift(query);
        window.localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 8)));
      } catch (error) { /* private mode: recent searches are optional */ }
    };
    var renderRecent = function () {
      var container = byId("atlas-search-recent");
      var list = byId("atlas-search-recent-list");
      if (!container || !list) return;
      var items = recentSearches();
      container.hidden = items.length === 0 || searchInput.value.trim() !== "";
      list.textContent = "";
      items.forEach(function (query) {
        var item = document.createElement("li");
        var link = document.createElement("a");
        link.href = "#";
        link.textContent = query;
        link.addEventListener("click", function (event) {
          event.preventDefault();
          searchInput.value = query;
          runSearch(query);
        });
        item.appendChild(link);
        list.appendChild(item);
      });
    };

    var highlight = function (text, needle) {
      var target = document.createDocumentFragment();
      var lower = text.toLowerCase();
      var index = needle ? lower.indexOf(needle.toLowerCase()) : -1;
      if (index < 0) {
        target.appendChild(document.createTextNode(text));
        return target;
      }
      target.appendChild(document.createTextNode(text.slice(0, index)));
      var mark = document.createElement("mark");
      mark.textContent = text.slice(index, index + needle.length);
      target.appendChild(mark);
      target.appendChild(document.createTextNode(text.slice(index + needle.length)));
      return target;
    };

    var renderResults = function (payload) {
      var container = byId("atlas-search-results");
      var status = byId("atlas-search-status");
      if (!container) return;
      container.textContent = "";
      resultLinks = [];
      activeIndex = -1;
      if (!payload) { if (status) status.hidden = true; return; }
      if (status) {
        status.hidden = false;
        status.textContent = payload.total === 0
          ? "No evidence matches “" + payload.query + "”. Atlas never invents results — try a hostname, IP, interface, site, or serial."
          : payload.total + " result(s) across " + payload.groups.length + " group(s).";
      }
      if (payload.expanded_group) {
        var back = document.createElement("button");
        back.type = "button";
        back.className = "btn btn-sm search-show-all";
        back.textContent = "← All result groups";
        back.addEventListener("click", function () {
          runSearch(searchInput.value.trim());
        });
        container.appendChild(back);
      }
      payload.groups.forEach(function (group) {
        var head = document.createElement("div");
        head.className = "search-group-head";
        head.textContent = group.label + " (" + group.count + ")";
        container.appendChild(head);
        group.results.forEach(function (result) {
          var link = document.createElement("a");
          link.className = "search-result";
          link.href = result.href;
          var title = document.createElement("div");
          title.className = "search-result-title";
          title.appendChild(highlight(result.title, payload.query));
          var meta = document.createElement("div");
          meta.className = "search-result-meta muted";
          var bits = [result.subtitle];
          if (result.match && result.match.field) {
            bits.push("matched " + result.match.field + " (" + result.match.rank + ")");
          }
          if (result.detail && result.detail.confidence_percent) {
            bits.push("identity " + result.detail.confidence_percent + "%");
          }
          if (result.detail && result.detail.neighbor) {
            bits.push("neighbor " + result.detail.neighbor);
          }
          meta.textContent = bits.filter(Boolean).join(" · ");
          link.appendChild(title);
          link.appendChild(meta);
          link.addEventListener("click", function () { rememberSearch(payload.query); });
          container.appendChild(link);
          resultLinks.push(link);
        });
        // "Show all": a truncated group can expand in place. The count is
        // always shown; the control appears only when there is more.
        if (!payload.expanded_group && group.count > group.results.length) {
          var more = document.createElement("button");
          more.type = "button";
          more.className = "btn btn-sm search-show-all";
          more.setAttribute(
            "aria-label",
            "Show all " + group.count + " " + group.label + " results"
          );
          more.textContent = "Show all " + group.count;
          more.addEventListener("click", function () {
            runSearch(searchInput.value.trim(), group.group_id || group.id);
          });
          container.appendChild(more);
        }
      });
    };

    var runSearch = function (query, expandGroup) {
      var status = byId("atlas-search-status");
      renderRecent();
      if (!query) { renderResults(null); return; }
      if (status) { status.hidden = false; status.textContent = "Searching…"; }
      var url = "/api/search?q=" + encodeURIComponent(query);
      if (expandGroup) {
        url += "&group=" + encodeURIComponent(expandGroup) + "&limit=200";
      }
      fetch(url)
        .then(function (response) { return response.json(); })
        .then(function (payload) {
          if (searchInput.value.trim() === payload.query) renderResults(payload);
        })
        .catch(function () {
          if (status) { status.hidden = false; status.textContent = "Search unavailable — is the Atlas server still running?"; }
        });
    };

    searchInput.addEventListener("input", function () {
      window.clearTimeout(searchTimer);
      var query = searchInput.value.trim();
      searchTimer = window.setTimeout(function () { runSearch(query); }, DEBOUNCE_MS);
    });

    var setActive = function (index) {
      if (!resultLinks.length) return;
      if (activeIndex >= 0) resultLinks[activeIndex].classList.remove("active");
      activeIndex = (index + resultLinks.length) % resultLinks.length;
      resultLinks[activeIndex].classList.add("active");
      resultLinks[activeIndex].scrollIntoView({ block: "nearest" });
    };

    searchInput.addEventListener("keydown", function (event) {
      // Escape wins over everything — including the browser's native
      // clear-the-search-input behavior — and closes from inside the input.
      if (event.key === "Escape") { event.preventDefault(); closeSearch(); }
      else if (event.key === "ArrowDown") { event.preventDefault(); setActive(activeIndex + 1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); setActive(activeIndex - 1); }
      else if (event.key === "Enter" && activeIndex >= 0 && resultLinks[activeIndex]) {
        event.preventDefault();
        rememberSearch(searchInput.value.trim());
        window.location.href = resultLinks[activeIndex].href;
      }
    });

    document.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && (event.key === "k" || event.key === "K")) {
        event.preventDefault();
        if (searchOverlay.hidden) openSearch(); else closeSearch();
      } else if (event.key === "Escape" && !searchOverlay.hidden) {
        closeSearch();
      } else if (event.key === "Escape" && closeNavDrawer &&
                 document.body.classList.contains("nav-open")) {
        closeNavDrawer(true);
      } else if (event.key === "Escape") {
        closeMenus(null);
      }
    });
    var trigger = byId("atlas-search-trigger");
    if (trigger) trigger.addEventListener("click", openSearch);
    // MISSION (PR-040) and any other page can offer "Search the
    // Enterprise" buttons — same overlay, never a duplicate.
    Array.prototype.forEach.call(
      document.querySelectorAll(".js-open-search"),
      function (button) { button.addEventListener("click", openSearch); }
    );
    searchOverlay.addEventListener("click", function (event) {
      if (event.target === searchOverlay) closeSearch();
    });

    // -- Mission context awareness (PR-040) -------------------------------
    // Stored locally in THIS browser only (localStorage) — Atlas never
    // persists this server-side and no sensitive data is recorded.
    var DEVICES_KEY = "atlas-recent-devices";
    var readList = function (key) {
      try {
        var raw = window.localStorage.getItem(key);
        var list = raw ? JSON.parse(raw) : [];
        return Array.isArray(list) ? list : [];
      } catch (error) { return []; }
    };
    if (window.location.pathname.indexOf("/devices/") === 0) {
      var heading = document.querySelector("main h1");
      if (heading && heading.textContent.trim() &&
          heading.textContent.trim() !== "Device not found") {
        try {
          var entry = {
            title: heading.textContent.trim(),
            href: window.location.pathname
          };
          var devices = readList(DEVICES_KEY).filter(function (item) {
            return item.href !== entry.href;
          });
          devices.unshift(entry);
          window.localStorage.setItem(
            DEVICES_KEY, JSON.stringify(devices.slice(0, 8))
          );
        } catch (error) { /* private mode: context awareness is optional */ }
      }
    }
    var renderMissionList = function (id, items, onClick) {
      var list = byId(id);
      if (!list || !items.length) return;
      list.textContent = "";
      items.forEach(function (item) {
        var row = document.createElement("li");
        var link = document.createElement("a");
        link.href = item.href || "#";
        link.textContent = item.title || item;
        if (onClick) {
          link.addEventListener("click", function (event) { onClick(event, item); });
        }
        row.appendChild(link);
        list.appendChild(row);
      });
    };
    renderMissionList(
      "mission-recent-devices",
      readList(DEVICES_KEY)
    );
    renderMissionList(
      "mission-recent-searches",
      recentSearches().map(function (query) {
        return { title: query, href: "#" };
      }),
      function (event, item) {
        event.preventDefault();
        openSearch();
        searchInput.value = item.title;
        runSearch(item.title);
      }
    );
  }
})();

// ---------------------------------------------------------------------------
// CSP-strict page behaviors (no inline scripts, no inline handlers).
// Every block is guarded and delegated: pages opt in via data-* hooks,
// and essential flows keep working with JavaScript disabled.
(function () {
  "use strict";

  // Auto-submitting selects (scope switcher, filter selects). The
  // enclosing form keeps its <noscript> Apply button as the fallback.
  document.addEventListener("change", function (event) {
    var control = event.target.closest("[data-autosubmit]");
    if (control && control.form) { control.form.submit(); }
  });

  // Dirty-form protection: forms marked data-dirty-guard warn before
  // navigation once edited, and stand down on submit.
  var dirtyForms = document.querySelectorAll("form[data-dirty-guard]");
  if (dirtyForms.length) {
    var dirty = false;
    Array.prototype.forEach.call(dirtyForms, function (form) {
      form.addEventListener("input", function () { dirty = true; });
      form.addEventListener("submit", function () { dirty = false; });
    });
    window.addEventListener("beforeunload", function (event) {
      if (!dirty) { return; }
      event.preventDefault();
      event.returnValue = "";
    });
  }

  // Copy Diagnostics: fetch the JSON and place it on the clipboard.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy-url]");
    if (!button) { return; }
    fetch(button.dataset.copyUrl)
      .then(function (response) { return response.json(); })
      .then(function (data) {
        return navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      })
      .then(function () { button.textContent = "Copied"; })
      .catch(function () { button.textContent = "Copy failed — open the JSON link instead"; });
  });

  // Advisor ask: explicit in-progress state while the server prepares
  // the evidence-backed answer.
  var advisorForm = document.getElementById("advisor-ask-form");
  var advisorNote = document.getElementById("advisor-asking");
  var advisorButton = document.getElementById("advisor-ask-button");
  if (advisorForm && advisorNote && advisorButton) {
    advisorForm.addEventListener("submit", function () {
      advisorButton.disabled = true;
      advisorButton.textContent = "Asking…";
      advisorNote.hidden = false;
    });
  }

  // Interactive SSH console bootstrap: configuration rides in a JSON data
  // block (never executable), read here and handed to AtlasConsole.
  var consoleConfig = document.getElementById("atlas-console-config");
  if (consoleConfig && window.AtlasConsole) {
    try {
      window.AtlasConsole.init(JSON.parse(consoleConfig.textContent));
    } catch (error) {
      var terminal = document.getElementById("terminal");
      if (terminal) {
        terminal.textContent =
          "The console could not start: its configuration did not parse.";
      }
    }
  }
})();

// -- Navigation accordion (PR: calmer navigation) ---------------------------
// One primary area open at a time. Progressive enhancement only: without
// JavaScript every <details> group still opens and closes natively with
// the keyboard — the enhancement merely closes the OTHERS.
(function () {
  "use strict";
  var sidebar = document.getElementById("atlas-sidebar");
  if (!sidebar) { return; }
  sidebar.addEventListener("toggle", function (event) {
    var opened = event.target;
    if (!opened.classList || !opened.classList.contains("nav-details")) { return; }
    if (!opened.open) { return; }
    var all = sidebar.querySelectorAll("details.nav-details[open]");
    for (var i = 0; i < all.length; i++) {
      if (all[i] !== opened) { all[i].open = false; }
    }
  }, true);
})();

// -- Table column customization (PR: calmer tables) -------------------------
// A table marked <table data-columns="name"> with <th data-col="x"> headers
// gains a "Columns" control (body cells hide by column position, so only
// the THEAD needs markers; rows using colspans are left intact): Simple /
// Detailed / Expert presets, per-column toggles, and Reset. Choices
// persist per user and table through the UI-preference API (never
// localStorage). Progressive enhancement — without JS every column shows,
// and EXPORTS are server-side and independent of what is visible.
(function () {
  "use strict";
  var tables = document.querySelectorAll("table[data-columns]");
  if (!tables.length) { return; }

  function presetOf(th) {
    // A column belongs to the lightest preset that includes it.
    return th.dataset.colPreset || "detailed";
  }

  Array.prototype.forEach.call(tables, function (table, tableIndex) {
    var name = table.dataset.columns;
    var prefKey = "table:" + name;
    var headers = Array.prototype.slice.call(
      table.querySelectorAll("thead th[data-col]")
    );
    if (!headers.length) { return; }
    var columns = headers.map(function (th) { return th.dataset.col; });

    var allHead = Array.prototype.slice.call(
      table.querySelectorAll("thead th")
    );
    var indexOf = {};
    headers.forEach(function (th) {
      indexOf[th.dataset.col] = allHead.indexOf(th);
    });

    function setVisible(hidden) {
      var rows = Array.prototype.slice.call(
        table.querySelectorAll("tbody tr")
      );
      columns.forEach(function (col) {
        var off = hidden.indexOf(col) !== -1;
        var index = indexOf[col];
        if (allHead[index]) { allHead[index].hidden = off; }
        rows.forEach(function (row) {
          // Rows with colspans (detail/empty rows) keep their layout.
          if (row.children.length !== allHead.length) { return; }
          var cell = row.children[index];
          if (cell) { cell.hidden = off; }
        });
        // Cells explicitly marked keep working too (evidence table).
        table.querySelectorAll('td[data-col="' + col + '"]').forEach(
          function (cell) { cell.hidden = off; }
        );
        var box = panel.querySelector('input[value="' + col + '"]');
        if (box) { box.checked = !off; }
      });
    }

    function currentHidden() {
      var hidden = [];
      panel.querySelectorAll("input[type=checkbox]").forEach(function (box) {
        if (!box.checked) { hidden.push(box.value); }
      });
      return hidden;
    }

    var saveNote = document.createElement("p");
    saveNote.className = "muted table-columns-note";
    saveNote.setAttribute("role", "status");
    saveNote.hidden = true;

    function persist() {
      // The installCsrf fetch wrapper adds X-Atlas-CSRF for us.
      fetch("/api/preferences/ui", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: prefKey, value: { hidden: currentHidden() } })
      }).then(function (response) {
        saveNote.hidden = response.ok;
        if (!response.ok) {
          saveNote.textContent = "Column choice was not saved (HTTP "
            + response.status + ") — it applies to this page only.";
        }
      }).catch(function () {
        saveNote.hidden = false;
        saveNote.textContent = "Column choice was not saved — Atlas could "
          + "not be reached. It applies to this page only.";
      });
    }

    function applyPreset(level, save) {
      var order = { simple: 0, detailed: 1, expert: 2 };
      var hidden = headers.filter(function (th) {
        return order[presetOf(th)] > order[level];
      }).map(function (th) { return th.dataset.col; });
      setVisible(hidden);
      // Initial page-load presets are views, not choices: only a user
      // action (preset button, checkbox, reset) writes a preference.
      if (save !== false) { persist(); }
    }

    // Build the control.
    var wrap = document.createElement("details");
    wrap.className = "table-columns";
    var summary = document.createElement("summary");
    summary.textContent = "Columns";
    summary.setAttribute("aria-label", "Choose which columns to show");
    var panel = document.createElement("div");
    panel.className = "table-columns-body";
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-label", "Column visibility for " + name);

    var presets = document.createElement("div");
    presets.className = "table-columns-presets";
    ["simple", "detailed", "expert"].forEach(function (level) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = level.charAt(0).toUpperCase() + level.slice(1);
      b.addEventListener("click", function () { applyPreset(level); });
      presets.appendChild(b);
    });
    panel.appendChild(presets);
    panel.appendChild(saveNote);

    headers.forEach(function (th) {
      // tableIndex keeps ids unique when one page repeats a table
      // (credentials renders one table per credential set).
      var id = "col-" + name + "-" + tableIndex + "-" + th.dataset.col;
      var label = document.createElement("label");
      var box = document.createElement("input");
      box.type = "checkbox";
      box.value = th.dataset.col;
      box.id = id;
      box.checked = true;
      box.addEventListener("change", function () {
        setVisible(currentHidden()); persist();
      });
      label.appendChild(box);
      var colLabel = th.dataset.colLabel
        || (th.textContent || "").trim()
        || th.dataset.col;
      label.appendChild(document.createTextNode(" " + colLabel));
      panel.appendChild(label);
    });

    var reset = document.createElement("button");
    reset.type = "button";
    reset.className = "table-columns-reset";
    reset.textContent = "Reset to recommended";
    reset.addEventListener("click", function () {
      applyPreset(document.body.dataset.displayLevel || "detailed");
    });
    panel.appendChild(reset);

    wrap.appendChild(summary);
    wrap.appendChild(panel);
    // Place the control just before the table.
    table.parentNode.insertBefore(wrap, table);

    // Restore saved hidden set, else apply the display-level preset.
    try {
      fetch("/api/preferences/ui?key=" + encodeURIComponent(prefKey))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          var saved = data && data.value && data.value.hidden;
          if (Array.isArray(saved)) { setVisible(saved); }
          else { applyPreset(document.body.dataset.displayLevel || "detailed", false); }
        })
        .catch(function () {
          applyPreset(document.body.dataset.displayLevel || "detailed", false);
        });
    } catch (e) {
      applyPreset(document.body.dataset.displayLevel || "detailed", false);
    }
  });
})();

// -- Guided forms: never hide a validation error (PR: guided workflows) -----
// If a form fails to submit because a required/invalid field sits inside a
// collapsed <details> (an "Advanced" section), open that section and focus
// the field. A blocked submit must never look like nothing happened.
(function () {
  "use strict";
  document.addEventListener("invalid", function (event) {
    var field = event.target;
    if (!field || typeof field.closest !== "function") { return; }
    var section = field.closest("details:not([open])");
    while (section) {
      section.open = true;
      section = section.parentElement
        ? section.parentElement.closest("details:not([open])")
        : null;
    }
    // Let the browser show its own message on the now-visible field.
    if (typeof field.focus === "function") {
      try { field.focus({ preventScroll: false }); } catch (e) { field.focus(); }
    }
  }, true);
})();

// -- Remember "Advanced" open state per user (PR: guided workflows) ----------
// A <details data-remember="workflow:key"> restores its open/closed state
// from the UI-preference API and saves changes — so an experienced user who
// keeps Advanced open finds it open next time. Best-effort; a failed fetch
// simply leaves the server-rendered default.
(function () {
  "use strict";
  var remembered = document.querySelectorAll("details[data-remember]");
  if (!remembered.length) { return; }
  Array.prototype.forEach.call(remembered, function (section) {
    var key = section.dataset.remember;
    if (key.indexOf("workflow:") !== 0) { return; }
    try {
      fetch("/api/preferences/ui?key=" + encodeURIComponent(key))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (data && typeof data.value === "boolean") { section.open = data.value; }
        }).catch(function () {});
    } catch (e) { /* keep default */ }
    section.addEventListener("toggle", function () {
      try {
        fetch("/api/preferences/ui", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: key, value: section.open })
        }).catch(function () {});
      } catch (e) { /* best-effort */ }
    });
  });
})();

// -- Row selection ------------------------------------------------------------
// Every table where rows are picked for a bulk action behaves the same
// way: a select-all in the header, and a click anywhere in the row
// toggling that row. Written once here rather than per template, so a
// new bulk-action table inherits the behaviour (and the accessibility
// work) by adding one attribute: data-row-select="<checkbox name>".
//
// Deliberately its own top-level block: the section above returns early
// on any page without a <details data-remember>, and code appended
// after that return is simply never reached. Selection must not depend
// on an unrelated feature being present.
//
// Without JavaScript the individual checkboxes still submit normally —
// this only removes the pixel-hunting, it is never load-bearing.
(function rowSelection() {
  "use strict";
  (function () {
    function boxesOf(table) {
      var name = table.getAttribute("data-row-select");
      return Array.prototype.slice.call(
        table.querySelectorAll(
          'tbody input[type="checkbox"][name="' + name + '"]'
        )
      );
    }

    function syncHeader(table, master) {
      var boxes = boxesOf(table);
      var checked = boxes.filter(function (box) { return box.checked; }).length;
      master.checked = boxes.length > 0 && checked === boxes.length;
      // Partial selection is neither on nor off, and saying so is what
      // stops "select all" from looking like it failed.
      master.indeterminate = checked > 0 && checked < boxes.length;
      // The count usually sits with the submit button, outside the
      // table — look across the form, not just the table.
      var scope = table.closest("form") || document;
      var count = scope.querySelector("[data-selection-count]");
      if (count) {
        count.textContent = checked
          ? checked + " of " + boxes.length + " selected"
          : "";
      }
      boxes.forEach(function (box) {
        var row = box.closest("tr");
        if (row) { row.classList.toggle("row-selected", box.checked); }
      });
    }

    function setChecked(box, value) {
      if (box.checked === value) { return; }
      box.checked = value;
      // Anything listening for a real user change must still hear it.
      box.dispatchEvent(new Event("change", { bubbles: true }));
    }

    document.querySelectorAll("table[data-row-select]").forEach(function (table) {
      var master = table.querySelector("[data-select-all]");
      // Setting a box fires a bubbling change, which re-enters the sync
      // below; that recomputed the header mid-loop and flipped
      // master.checked to false after the FIRST box, so "select all"
      // selected exactly one row and cleared the rest. The wanted value
      // is therefore read once, and the sync stands down while a bulk
      // set is in flight.
      var bulkSetting = false;
      if (master) {
        master.addEventListener("change", function () {
          var wanted = master.checked;
          bulkSetting = true;
          boxesOf(table).forEach(function (box) { setChecked(box, wanted); });
          bulkSetting = false;
          syncHeader(table, master);
        });
      }

      table.addEventListener("change", function (event) {
        if (bulkSetting) { return; }
        var target = event.target;
        if (target && target.matches('input[type="checkbox"]') && master) {
          syncHeader(table, master);
        }
      });

      table.addEventListener("click", function (event) {
        var row = event.target.closest("tbody tr");
        if (!row || !table.contains(row)) { return; }
        var box = row.querySelector(
          'input[type="checkbox"][name="' +
          table.getAttribute("data-row-select") + '"]'
        );
        if (!box || box.disabled) { return; }
        // A click on something with its own job — a link, a button, the
        // checkbox, a label bound to it — belongs to that thing.
        if (event.target.closest("a, button, input, select, textarea, label")) {
          return;
        }
        // Selecting text is not clicking a row.
        var selection = window.getSelection && window.getSelection();
        if (selection && String(selection).length > 0) { return; }
        setChecked(box, !box.checked);
        if (master) { syncHeader(table, master); }
      });

      if (master) { syncHeader(table, master); }
    });
  })();
})();
