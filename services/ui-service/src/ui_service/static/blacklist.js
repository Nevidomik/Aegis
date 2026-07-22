(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.BlacklistPolling = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const POLL_INTERVAL_MS = 30000;

  function snapshotChanged(currentSnapshotId, latestSnapshotId) {
    return currentSnapshotId !== latestSnapshotId;
  }

  function indicatorMessage(state) {
    if (state === "stale") return "The displayed blacklist snapshot is stale.";
    if (state === "degraded") {
      return "The latest synchronization failed. The most recent valid snapshot remains available.";
    }
    if (state === "syncing") {
      return "A synchronization is in progress. The latest successful snapshot remains available below.";
    }
    if (state === "empty") return "No successful blacklist snapshot is available yet.";
    return "The latest blacklist snapshot is ready.";
  }

  function createPoller(options) {
    let timer = null;
    let inFlight = false;
    let stopped = false;

    function schedule() {
      if (!stopped && !options.isHidden()) {
        timer = options.setTimer(poll, options.interval || POLL_INTERVAL_MS);
      }
    }

    async function poll() {
      if (stopped || inFlight || options.isHidden()) return;
      inFlight = true;
      try {
        const status = await options.fetchStatus();
        if (snapshotChanged(options.currentSnapshotId, status.latest_snapshot_id)) {
          options.reload();
          return;
        }
        options.updateIndicator(status.state, status.data_stale);
      } catch (_error) {
        // Keep the currently rendered snapshot and status after polling failures.
      } finally {
        inFlight = false;
        schedule();
      }
    }

    function visibilityChanged() {
      if (options.isHidden()) {
        if (timer !== null) options.clearTimer(timer);
        timer = null;
      } else if (!inFlight) {
        void poll();
      }
    }

    function start() {
      schedule();
    }

    function stop() {
      stopped = true;
      if (timer !== null) options.clearTimer(timer);
      timer = null;
    }

    return { poll, start, stop, visibilityChanged };
  }

  function start(options) {
    const poller = createPoller({
      currentSnapshotId: options.currentSnapshotId,
      interval: POLL_INTERVAL_MS,
      isHidden: function () { return document.hidden; },
      setTimer: window.setTimeout.bind(window),
      clearTimer: window.clearTimeout.bind(window),
      fetchStatus: async function () {
        const response = await fetch(options.statusUrl, {
          headers: { Accept: "application/json" },
          cache: "no-store"
        });
        if (!response.ok) throw new Error("Status request failed");
        return response.json();
      },
      reload: function () { window.location.reload(); },
      updateIndicator: function (state, dataStale) {
        options.indicator.dataset.state = state;
        options.indicator.className = (state === "stale" || state === "degraded" || dataStale) ? "warning" : "";
        options.indicator.textContent = indicatorMessage(state);
      }
    });
    document.addEventListener("visibilitychange", poller.visibilityChanged);
    poller.start();
    return poller;
  }

  return { createPoller, indicatorMessage, snapshotChanged, start };
});
