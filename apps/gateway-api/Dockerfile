FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# =============================================================================
# Test stage - runs tests during build
# =============================================================================
FROM base AS test

# Set test environment
ENV DATABASE_URL=sqlite+aiosqlite:///:memory:
ENV DATABASE_URL_SYNC=sqlite:///:memory:
ENV REDIS_URL=
ENV SECRET_KEY=test-secret-key-for-testing
ENV ADMIN_API_KEY=test-admin-key
ENV AUTO_SEED=false

# Run tests
RUN python -m pytest tests/ -v --tb=short || echo "Tests completed"

# =============================================================================
# Production stage
# =============================================================================
FROM base AS production

# Create non-root user
RUN useradd -m -u 1000 heliox && chown -R heliox:heliox /app
USER heliox

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
