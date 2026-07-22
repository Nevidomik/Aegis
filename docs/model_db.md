## Blacklist persistence

### blacklist_snapshots

Represents one complete accepted provider snapshot.

Suggested fields:

- `snapshot_id`;
- `provider`;
- `provider_generated_at`;
- `fetched_at`;
- `confidence_minimum`;
- `requested_limit`;
- `returned_count`;
- `created_at`.

### blacklist_snapshot_entries

Stores every normalized entry belonging to one snapshot.

Suggested fields:

- `entry_id`;
- `snapshot_id`;
- `ip_address`;
- `ip_version`;
- `abuse_confidence_score`;
- `country_code`;
- `last_reported_at`;
- optional supplementary provider JSON.

Constraints:

- foreign key to `blacklist_snapshots`;
- unique `(snapshot_id, ip_address)`;
- score between 0 and 100;
- canonical IP representation.

### blacklist_sync_runs

Records every synchronization attempt.

Suggested fields:

- `sync_run_id`;
- `request_id`;
- `started_at`;
- `finished_at`;
- `status`;
- `snapshot_id`;
- `provider_http_status`;
- `rate_limit_limit`;
- `rate_limit_remaining`;
- `rate_limit_reset_at`;
- `retry_after_seconds`;
- `next_attempt_at`;
- `error_code`;
- safe `error_message`.

The old manual lookup table remains untouched and is not used by blacklist
synchronization.
