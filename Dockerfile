FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

CMD ["sh", "-c", "uvicorn bot.server:app --host 0.0.0.0 --port ${PORT:-10000}"]
