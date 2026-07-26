(function () {
  "use strict";

  const root = document.querySelector("[data-time-travel-replay]");
  if (!root) return;
  const steps = Array.from(root.querySelectorAll("[data-replay-step]"));
  const previous = root.querySelector("[data-replay-previous]");
  const next = root.querySelector("[data-replay-next]");
  const play = root.querySelector("[data-replay-play]");
  const pause = root.querySelector("[data-replay-pause]");
  const status = root.querySelector("[data-replay-status]");
  if (!steps.length || !previous || !next || !play || !pause || !status) return;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let current = -1;
  let timer = null;

  function stop() {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
    play.disabled = false;
    pause.disabled = true;
  }

  function show(index, moveFocus) {
    current = (index + steps.length) % steps.length;
    steps.forEach(function (row, position) {
      row.removeAttribute("aria-current");
      row.removeAttribute("tabindex");
      if (position === current) {
        row.setAttribute("aria-current", "step");
        row.setAttribute("tabindex", "-1");
      }
    });
    const row = steps[current];
    status.textContent = "Change " + (current + 1) + " of " + steps.length + ": "
      + row.textContent.trim().replace(/\s+/g, " ");
    if (moveFocus) {
      row.focus({preventScroll: reducedMotion});
      if (!reducedMotion) row.scrollIntoView({block: "nearest", behavior: "smooth"});
    }
  }

  previous.addEventListener("click", function () {
    stop();
    show(current <= 0 ? steps.length - 1 : current - 1, true);
  });
  next.addEventListener("click", function () {
    stop();
    show(current + 1, true);
  });
  play.addEventListener("click", function () {
    if (timer !== null) return;
    play.disabled = true;
    pause.disabled = false;
    show(current + 1, false);
    timer = window.setInterval(function () {
      show(current + 1, false);
    }, reducedMotion ? 3000 : 1800);
  });
  pause.addEventListener("click", stop);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && timer !== null) {
      stop();
      status.textContent = "Playback paused at change " + (current + 1) + ".";
    }
  });
}());

