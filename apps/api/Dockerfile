# The API and the arq worker share this image — same code, same deps —
# differing only in command:
#   API:     uvicorn src.main:app --host 0.0.0.0 --port 8010   (default CMD)
#   Worker:  arq src.workers.main.WorkerSettings
#   Migrate: alembic upgrade head        (a one-shot job per deploy)
#
# ffmpeg/ffprobe are real runtime dependencies (services/media/ transcodes
# with them; CI installs them the same way), not build-time tooling — hence
# apt in the runtime stage. python:3.12-slim matches CI's Python.
#
# Digest-pinned (report M7) — a mutable tag lets whoever controls it change
# what a production build actually pulls; the tag comment is kept purely
# for a human re-resolving the pin, not something the build itself trusts.
# Re-resolve deliberately (not on a schedule) with:
#   docker buildx imagetools inspect python:3.12-slim
FROM python:3.12-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217 AS runtime

# upgrade (not just install): picks up whatever Debian security patches
# are already published since this base image's own last rebuild --
# report M7's Trivy pass found the pinned digest above shipping openssl
# 3.5.6-1~deb13u2 against 3.5.7-1~deb13u2 already being available
# (CVE-2026-14456). Re-run after any digest re-resolution: a fresh base
# image may already carry it, making this a no-op, which is fine.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root from the start: nothing here needs root at runtime, and
# 04_SECURITY_AND_COMPLIANCE.md's posture expects least privilege.
RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

USER app

# ENVIRONMENT=production must come from the deployment environment, which
# arms core/config.py's check_production_safety fail-fast. No .env is baked
# in — configuration is environment-only in a container.
EXPOSE 8010
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8010"]
