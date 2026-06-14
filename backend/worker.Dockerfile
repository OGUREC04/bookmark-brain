FROM python:3.12-slim

WORKDIR /app

# Same deps as backend — worker imports app.*  Plus ffmpeg: the upload worker
# transcodes browser audio (WebM/MP4) -> OGG Opus for Yandex STT (3sr).
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Build context is the repo ROOT (compose: context: .) so we can copy shared/.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
# Shared media package (STT / extraction / storage / transcode) — 3sr.
COPY shared/ ./shared/

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app
USER app

CMD ["python", "run_worker.py"]
