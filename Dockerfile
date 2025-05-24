FROM python:3.11
RUN apt-get update && apt-get install -y python3-dev libev-dev
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["gunicorn", "bot:app", "--bind", "0.0.0.0:$PORT", "--workers", "3", "--worker-class", "gevent"]
