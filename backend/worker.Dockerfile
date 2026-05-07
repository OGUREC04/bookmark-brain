FROM python:3.12-slim

WORKDIR /app

# Same deps as backend — worker imports app.*
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app
USER app

CMD ["python", "run_worker.py"]
