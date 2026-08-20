# The API and the arq worker share this image — same code, same deps —
# differing only in command:
#   API:     uvicorn src.main:app --host 0.0.0.0 --port 8010   (default CMD)
#   Worker:  arq src.workers.main.WorkerSettings
#   Migrate: alembic upgrade head        (a one-shot job per deploy)
#
# ffmpeg/ffprobe are real runtime dependencies (services/media/ transcodes
# with them; CI installs them the same way), not build-time tooling — hence
# apt in the runtime stage. python:3.12-slim matches CI's Python.
FROM python:3.12-slim AS runtime

RUN apt-get update \
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
