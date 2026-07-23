import subprocess
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).parents[1] / "src" / "ui_service" / "static" / "blacklist.js"
)


def test_blacklist_polling_change_detection_and_error_behavior() -> None:
    test_program = r"""
const assert = require("node:assert/strict");
const polling = require(process.argv[1]);

assert.equal(polling.snapshotChanged(42, 42), false);
assert.equal(polling.snapshotChanged(42, 43), true);
assert.equal(polling.snapshotChanged(null, 1), true);
assert.equal(typeof polling.renderTurnoverCharts, "function");

async function exercise() {
  let reloads = 0;
  let updates = [];
  let scheduled = 0;
  const base = {
    currentSnapshotId: 42,
    isHidden: () => false,
    setTimer: () => { scheduled += 1; return scheduled; },
    clearTimer: () => {},
    reload: () => { reloads += 1; },
    updateIndicator: (state, stale) => { updates.push([state, stale]); }
  };

  const unchanged = polling.createPoller({
    ...base,
    fetchStatus: async () => ({
      state: "stale", latest_snapshot_id: 42, data_stale: true
    })
  });
  await unchanged.poll();
  assert.equal(reloads, 0);
  assert.deepEqual(updates, [["stale", true]]);

  const changed = polling.createPoller({
    ...base,
    fetchStatus: async () => ({
      state: "ready", latest_snapshot_id: 43, data_stale: false
    })
  });
  await changed.poll();
  assert.equal(reloads, 1);

  updates = [];
  const failed = polling.createPoller({
    ...base,
    fetchStatus: async () => { throw new Error("unavailable"); }
  });
  await failed.poll();
  assert.equal(reloads, 1);
  assert.deepEqual(updates, []);

  let resolveRequest;
  let requestCount = 0;
  const pending = new Promise((resolve) => { resolveRequest = resolve; });
  const overlapping = polling.createPoller({
    ...base,
    fetchStatus: () => { requestCount += 1; return pending; }
  });
  const first = overlapping.poll();
  await overlapping.poll();
  assert.equal(requestCount, 1);
  resolveRequest({state: "ready", latest_snapshot_id: 42, data_stale: false});
  await first;

  let hidden = true;
  scheduled = 0;
  const visibility = polling.createPoller({
    ...base,
    isHidden: () => hidden,
    fetchStatus: async () => ({
      state: "ready", latest_snapshot_id: 42, data_stale: false
    })
  });
  visibility.start();
  assert.equal(scheduled, 0);
  hidden = false;
  visibility.visibilityChanged();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(scheduled, 1);
}

exercise().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""

    result = subprocess.run(
        ["node", "-e", test_program, str(SCRIPT_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_turnover_renderer_preserves_gaps_and_separate_bar_series() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "point.turnover_percent == null" in source
    assert "appendSegment();" in source
    assert '["added_count", "bar-added"' in source
    assert '["removed_count", "bar-removed"' in source
