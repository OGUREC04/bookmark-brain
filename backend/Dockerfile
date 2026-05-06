FROM python:3.12-slim

WORKDIR /app

# System deps for asyncpg, cryptography
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app
USER app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
