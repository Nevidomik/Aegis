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
  const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

  function svgElement(name, attributes) {
    const element = document.createElementNS(SVG_NAMESPACE, name);
    Object.entries(attributes || {}).forEach(function (entry) {
      element.setAttribute(entry[0], String(entry[1]));
    });
    return element;
  }

  function chartFrame(container) {
    const svg = svgElement("svg", {
      viewBox: "0 0 720 260",
      preserveAspectRatio: "xMidYMid meet",
      "aria-hidden": "true",
      focusable: "false"
    });
    svg.appendChild(svgElement("line", {
      x1: 52, y1: 220, x2: 700, y2: 220, class: "chart-axis"
    }));
    svg.appendChild(svgElement("line", {
      x1: 52, y1: 18, x2: 52, y2: 220, class: "chart-axis"
    }));
    container.replaceChildren(svg);
    return svg;
  }

  function pointX(index, count) {
    return count <= 1 ? 376 : 52 + (index / (count - 1)) * 648;
  }

  function renderLineChart(container, points) {
    const svg = chartFrame(container);
    let segment = [];

    function appendSegment() {
      if (segment.length > 1) {
        svg.appendChild(svgElement("polyline", {
          points: segment.join(" "),
          class: "turnover-line",
          fill: "none"
        }));
      } else if (segment.length === 1) {
        const coordinates = segment[0].split(",");
        svg.appendChild(svgElement("circle", {
          cx: coordinates[0], cy: coordinates[1], r: 3, class: "turnover-point"
        }));
      }
      segment = [];
    }

    points.forEach(function (point, index) {
      if (point.turnover_percent == null) {
        appendSegment();
        return;
      }
      const value = Math.max(0, Math.min(100, Number(point.turnover_percent)));
      segment.push(pointX(index, points.length) + "," + (220 - value * 2));
    });
    appendSegment();

    const yLabel = svgElement("text", {
      x: 14, y: 125, class: "chart-axis-label",
      transform: "rotate(-90 14 125)"
    });
    yLabel.textContent = "Turnover percent";
    svg.appendChild(yLabel);
    const xLabel = svgElement("text", {
      x: 376, y: 252, class: "chart-axis-label"
    });
    xLabel.textContent = "UTC time bucket";
    svg.appendChild(xLabel);
  }

  function renderBarChart(container, points) {
    const svg = chartFrame(container);
    const values = points.flatMap(function (point) {
      return [point.added_count, point.removed_count]
        .filter(function (value) { return value != null; })
        .map(Number);
    });
    const maximum = Math.max(1, ...values);
    const groupWidth = 648 / Math.max(points.length, 1);
    const barWidth = Math.max(2, Math.min(14, groupWidth * 0.3));

    points.forEach(function (point, index) {
      const center = 52 + groupWidth * (index + 0.5);
      [
        ["added_count", "bar-added", center - barWidth],
        ["removed_count", "bar-removed", center]
      ].forEach(function (definition) {
        const value = point[definition[0]];
        if (value == null) return;
        const height = Math.max(0, Number(value)) / maximum * 190;
        svg.appendChild(svgElement("rect", {
          x: definition[2],
          y: 220 - height,
          width: barWidth,
          height: height,
          class: definition[1]
        }));
      });
    });

    const yLabel = svgElement("text", {
      x: 14, y: 125, class: "chart-axis-label",
      transform: "rotate(-90 14 125)"
    });
    yLabel.textContent = "IP address count";
    svg.appendChild(yLabel);
    const xLabel = svgElement("text", {
      x: 376, y: 252, class: "chart-axis-label"
    });
    xLabel.textContent = "UTC time bucket";
    svg.appendChild(xLabel);
  }

  function renderTurnoverCharts(rootElement) {
    const scope = rootElement || document;
    scope.querySelectorAll("[data-turnover-chart]").forEach(function (container) {
      let points;
      try {
        points = JSON.parse(container.dataset.points || "[]");
      } catch (_error) {
        return;
      }
      if (container.dataset.turnoverChart === "line") {
        renderLineChart(container, points);
      } else {
        renderBarChart(container, points);
      }
    });
  }

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
    renderTurnoverCharts(document);
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

  return {
    createPoller,
    indicatorMessage,
    renderTurnoverCharts,
    snapshotChanged,
    start
  };
});
