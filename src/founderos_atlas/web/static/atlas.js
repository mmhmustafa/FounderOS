// Atlas local GUI — minimal progressive enhancement only. No framework.
(function () {
  "use strict";

  // Disable the primary submit button on click to avoid double-running a
  // discovery while the pipeline is in progress.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    var button = form.querySelector('button[type="submit"].btn-primary');
    if (button && form.getAttribute("action") &&
        form.getAttribute("action").indexOf("/discovery/run") !== -1) {
      button.disabled = true;
      button.textContent = "Running discovery…";
    }
  });
})();
