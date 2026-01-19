FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    celery>=5.3.6 \
    redis>=5.0.1 \
    httpx>=0.26.0 \
    structlog>=24.1.0 \
    pydantic>=2.5.0 \
    pydantic-settings>=2.1.0

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 heliox && chown -R heliox:heliox /app
USER heliox

# Run Celery worker
CMD ["celery", "-A", "src.celery_app", "worker", "--loglevel=info"]
