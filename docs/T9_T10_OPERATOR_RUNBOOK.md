# T9/T10 Operator Evidence Runbook

**Purpose.** This runbook is for closing gates T9 (backup + restore) and T10 (worker rollback) by collecting real, dated evidence from production-shaped rehearsals. The scripts already work; this documents how an operator runs them by hand, what success looks like, and where to record the numbers in docs/BACKLOG.md and GitHub issue #31. The runbook itself does not close either gate — it produces the evidence a human then files as a PR.

---

## T9 — Backup + Restore Rehearsal

### Prerequisites

1. The VM is deployed via `scripts/deploy-single-vm.sh` and `.env.prod` exists with working backups.
2. An rclone crypt remote is already configured via `rclone config` before the deploy. The backup scripts check its type and refuse to run if it is not `crypt`.
3. `.env.prod` contains:
   - `BACKUP_RCLONE_REMOTE=<remote>:<path>` (e.g., `ttli-crypt:ttli-backups`, no whitespace)
   - `BACKUP_OWNER=<individual-email-or-id>` (3–128 characters, no spaces; this operator is paged on failure)
   - `BACKUP_RETENTION_DAYS=<7-30>` (e.g., `30`)
4. The deployment summary from `deploy-single-vm.sh` instructs you to run both scripts once by hand before considering the deploy finished. This runbook walks those steps.

### Step-by-step

1. **Run a manual backup.**

   ```bash
   sudo $APP_DIR/scripts/backup-production.sh
   ```

   Replace `$APP_DIR` with the app directory (typically `/opt/ttli`, shown in the deploy summary).

   **Success looks like:**
   - Exit code 0.
   - Final line: `backup complete in Ns; encrypted remote: <remote>:<path>; owner: <owner-email>`
   - A manifest file appears in `$APP_DIR/backups/ttli-<TIMESTAMP>.manifest` with the timestamp, owner, git SHA, Postgres image digest, database checksum, and duration.
   - **If exit code is non-zero:** the script outputs the reason (missing env var, rclone remote not crypt, pg_dump failed, etc.). Fix and re-run.

2. **Run the restore drill.**

   ```bash
   sudo $APP_DIR/scripts/restore-drill.sh
   ```

   This restores the newest backup into a throwaway database and Garage bucket. It never touches the live `ttli` database or production buckets.

   **Success looks like:**
   - Exit code 0.
   - Final line: `Restore drill passed; evidence: $APP_DIR/backups/drills/restore-drill-<TIMESTAMP>.txt`
   - The drill report file contains:
     - `restore_drill_utc=<ISO timestamp>`
     - `owner=<BACKUP_OWNER>`
     - `backup_timestamp_utc=<ISO timestamp of the backup it restored>`
     - `rpo_seconds=<actual>` (measured from backup timestamp to drill start)
     - `rpo_target_seconds=900` (15 minutes per docs/06_OPERATIONS.md §5.4)
     - `rpo_result=PASS` (actual must be ≤ 900)
     - `rto_seconds=<actual>` (measured from drill start to finish)
     - `rto_target_seconds=28800` (4–8 hours per docs/06_OPERATIONS.md §5.4; max is 8h = 28800s)
     - `rto_result=PASS` (actual must be ≤ 28800)
     - Object and database integrity counts
   - **If exit code is non-zero:** the script outputs the reason (no backup found, checksum mismatch, restored database has no tables, object restore failed, RPO or RTO target missed, etc.). The report still appears; read it for which target was missed, fix, and re-run.

3. **Automated quarterly runs.**

   The cron lines installed by `deploy-single-vm.sh` run the drill every 10 minutes (backup) and quarterly (drill). Verify they are installed:

   ```bash
   crontab -l | grep backup-production
   crontab -l | grep restore-drill
   ```

   Expected output:
   - Backup line: `*/10 * * * * APP_DIR=... $APP_DIR/scripts/backup-production.sh >> /var/log/ttli-backup.log 2>&1`
   - Drill line: `30 3 1 1,4,7,10 * APP_DIR=... $APP_DIR/scripts/restore-drill.sh >> /var/log/ttli-restore-drill.log 2>&1`

   The drill runs at 03:30 UTC on the 1st of January, April, July, October.

### Recording T9 evidence

In docs/BACKLOG.md's **T9 / O2** row, update the "Current state" column with a dated comment:

```
CODE DONE; operator evidence recorded 2026-MM-DD. 
Drill: backup_timestamp=<ISO>, rpo_seconds=<actual>, rpo_result=PASS, 
rto_seconds=<actual>, rto_result=PASS. 
Evidence: $APP_DIR/backups/drills/restore-drill-<TIMESTAMP>.txt
```

Copy the exact numbers from the drill report. The report is also synced off-host to the encrypted crypt remote by the next `backup-production.sh` run (every 10 minutes), so the evidence is not local-only.

---

## T10 — Forced Worker Rollback Rehearsal

### Prerequisites

1. A production-shaped host running via `scripts/deploy-single-vm.sh`.
2. The stack is currently healthy (all services passing health checks).
3. A known-good baseline release is running (check with `docker compose -f $COMPOSE_FILE ps` and note the image IDs).

### Step-by-step

**Open question:** Rolling-update.sh supports setting `RELEASE=<git-sha>` to pin a specific commit, but there is no documented way to force it to deploy a deliberately broken worker image (e.g., a bad tag, a non-existent image reference, or an image that fails the `arq --check` sentinel test). To complete T10, you must:

1. Either update `scripts/rolling-update.sh` to accept a way to inject a bad worker image (e.g., `WORKER_IMAGE=<bad-tag>` environment variable before the pull step).
2. Or manually force the condition another way (e.g., edit the compose file's worker `image:` reference, run `docker compose up -d worker`, and confirm it fails the healthcheck, then run the rollback steps below).

Assuming you have a way to deploy a broken worker:

1. **Capture the running state before the rollout.**

   ```bash
   docker compose -f $COMPOSE_FILE ps
   docker compose -f $COMPOSE_FILE exec -T api printenv APP_VERSION
   ```

   Note the running image IDs and APP_VERSION (a human will compare these to the post-rollback manifest).

2. **Trigger the broken worker deployment.**

   Run rolling-update.sh (or your chosen method) to deploy a known-bad worker image that will fail the `arq --check src.workers.main.WorkerSettings` healthcheck.

   **Expected behavior:**
   - The script detects the worker healthcheck failure.
   - It immediately rolls **both api and worker** back together to the previous image (because they share the same build and migrations).
   - A rollback manifest is written to `$APP_DIR/backups/release-rollback-<git-sha>.json`.

3. **Verify the rollback.**

   Check that:
   - API and worker report healthy after the rollback (the script's own `wait_healthy` confirms this before exiting).
   - Web was never touched (web's original image is still running).
   - The site is still responding (`curl -f https://<domain>/`).

4. **Trigger a known-good canary deployment.**

   ```bash
   sudo -E $APP_DIR/scripts/rolling-update.sh
   ```

   with `RELEASE` pointing to a known-good commit, to verify that a normal healthy deploy works after the rollback.

   **Expected behavior:**
   - Migration succeeds.
   - API health check passes and stays healthy.
   - Worker health check passes and stays healthy.
   - Web health check passes and stays healthy.
   - A release manifest is written to `$APP_DIR/backups/release-<git-sha>.json` with `"outcome": "deployed"`.

### Recording T10 evidence

After the rehearsal, two release manifests exist in `$APP_DIR/backups/`:

- `release-rollback-<git-sha>.json` — the failed rollout with actual health-check results and the running image IDs from the moment the rollback completed.
- `release-<git-sha>.json` — the successful canary deployment after rollback, with the same check structure.

These are automatically synced off-host to the encrypted crypt remote by the next `backup-production.sh` run.

In docs/BACKLOG.md's **F9 / T10** row, update the "Current state" column:

```
CODE DONE 2026-09-15 via #25. T10 rehearsal complete 2026-MM-DD:
- Broken worker deployment correctly failed healthcheck and triggered rollback.
- Both API and worker rolled back together to previous image.
- Known-good canary deployed successfully after rollback.
- Release manifests (rollback + canary) present in backups/ and synced off-host.
Evidence: $APP_DIR/backups/release-rollback-<sha>.json, $APP_DIR/backups/release-<sha>.json
```

---

## Closing the gates

This runbook produces the evidence; it does not itself close T9 or T10. After running the rehearsals:

1. Collect the evidence (drill reports, release manifests, dated operator notes).
2. Open a PR that updates docs/BACKLOG.md's T9 and T10 rows with the dated evidence comments above, and records the same evidence in GitHub issue #31's checklist.
3. The PR merge closes the gates; both are marked **DONE** once the evidence is recorded.
