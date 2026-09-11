# Production release verification

This runbook is the operational evidence layer for the production-hardening deployment-integrity work (T10).

## Canonical release command

Use:

```bash
sudo -E ./scripts/release.sh
```

Do not run `rolling-update.sh` directly for a normal production release. `release.sh` intentionally chains two phases:

1. `rolling-update.sh` performs signature verification, migrations, service swaps and its existing rollback handling.
2. `verify-deployment.sh` proves the resulting release is actually serving the expected build and writes objective evidence.

A release is not considered verified if the second phase fails.

## What the verifier proves

The verifier fails closed unless all of the following are true:

- `api`, `worker` and `web` containers are present.
- API and worker are running the exact `ttli-api:sha-<git-sha>` image pulled for the release.
- Web is running the exact `ttli-web:sha-<git-sha>` image pulled for the release.
- `GET /health/ready` succeeds from inside the API container, proving the application can reach its database rather than only proving the process is alive.
- `arq --check src.workers.main.WorkerSettings` succeeds from inside the worker container. This checks the short-lived Redis heartbeat written by the arq worker event loop and is stronger than checking only that the container PID remains running.
- The web container returns a non-5xx response from its local HTTP listener.
- `APP_VERSION` in both API and worker matches the expected Git SHA baked into the image at build time.

The verifier waits up to `DEPLOY_VERIFY_TIMEOUT` seconds (default `90`) for active canaries to become healthy.

## Evidence record

On success, the verifier writes a text evidence file under:

```text
/opt/ttli/var/deployments/
```

The directory can be changed with `DEPLOY_EVIDENCE_DIR`.

Each record contains:

- UTC verification timestamp;
- expected Git SHA;
- release image refs;
- running container IDs;
- exact Docker image IDs;
- registry repo digests where available;
- API/worker baked application version;
- pass state for API readiness, worker heartbeat and web HTTP canary.

`latest.txt` is a symlink to the most recent successful record.

Keep these records with deployment/change-management evidence. They are intentionally free of credentials and should not contain `.env.prod` values.

## Release override / rollback verification

`rolling-update.sh` already supports deploying a known commit with `RELEASE=<git-sha>`. The verifier uses the same variable, so a deliberate rollback or redeploy can be proved with:

```bash
sudo -E RELEASE=<known-good-git-sha> ./scripts/release.sh
```

The run is successful only if the running images and baked version match that requested SHA.

## What this does not close by itself

This change materially strengthens T10 but does not replace the required production rehearsal. Before T10 is marked complete, operations must still capture real evidence that an intentionally failed worker release causes the application/worker compatibility unit to roll back as designed, then run this verifier against the restored known-good release.

The production rehearsal should retain:

- terminal/change-ticket evidence of the induced failure;
- the rollback log from `rolling-update.sh`;
- the successful `verify-deployment.sh` evidence file for the restored release;
- named operator and witness;
- date/time and incident/change reference.

This distinction is deliberate: code can provide the rollback and verification mechanism, but only a controlled production/staging rehearsal can prove the operational path end to end.
