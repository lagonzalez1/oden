# workers/document_processor/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for neo4j driver
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY workers/document_processor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker code
COPY workers/document_processor/ /app/

# Set Python path to include all modules
ENV PYTHONPATH="/:/app:/Config:/Database:/:Repository/:Core/:Schema/:Prompts/:MessageBroker"

# Run the worker
CMD ["python", "main.py"]