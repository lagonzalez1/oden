FROM python:3.11-slim

WORKDIR /oden/workers/document_processor

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY workers/document_processor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Monorepo root on PYTHONPATH so `from Config...` / `from Service...` resolve.
ENV PYTHONPATH=/oden

CMD ["python", "main.py"]
