FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    python3-dev \
    libev-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD gunicorn bot:app --bind 0.0.0.0:${PORT} --workers 3 --worker-class gevent
