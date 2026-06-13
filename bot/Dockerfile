FROM python:3.12-slim

WORKDIR /app

COPY bot/requirements.txt ./bot/requirements.txt
RUN pip install --no-cache-dir -r bot/requirements.txt

COPY bot/ ./bot/
# Shared media package (STT / extraction) reused by the bot (3sr).
COPY shared/ ./shared/

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app
USER app

CMD ["python", "-m", "bot.main"]
