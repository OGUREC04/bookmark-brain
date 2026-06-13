FROM python:3.12-slim

WORKDIR /app

# System deps for asyncpg, cryptography
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Build context is the repo ROOT (compose: context: .) so we can copy the
# shared/ package alongside the backend. requirements first for layer caching.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
# Shared media package (STT / extraction / storage) reused by the worker (3sr).
COPY shared/ ./shared/

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app
USER app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
