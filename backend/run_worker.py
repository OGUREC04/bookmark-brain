"""Запуск arq worker с правильным event loop для Python 3.14+."""
import asyncio
import logging
import sys

from arq.worker import create_worker, get_kwargs

from app.worker import WorkerSettings

# Без этого arq пишет через logger.info и в stdout НИЧЕГО не видно —
# выглядит будто worker завис, хотя он штатно опрашивает Redis.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


async def main():
    worker = create_worker(WorkerSettings)
    await worker.async_run()


if __name__ == "__main__":
    asyncio.run(main())
