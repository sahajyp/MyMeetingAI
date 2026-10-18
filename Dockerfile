FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    DATA_DIR=/app/data \
    PORT=5000

WORKDIR /app

# CPU-only PyTorch keeps the image far smaller than the default CUDA build.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000
VOLUME ["/app/data"]

# One worker: the AI models live in memory and recordings are processed one at a
# time. Threads serve the web requests while a recording is being processed.
CMD ["sh", "-c", "gunicorn --workers 1 --threads 8 --timeout 900 --bind 0.0.0.0:${PORT} app:app"]
