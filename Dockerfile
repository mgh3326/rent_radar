FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    redis-tools \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and uv.lock for dependency installation
COPY pyproject.toml uv.lock ./

# Install uv and dependencies including psycopg2 for alembic
RUN pip install --no-cache-dir uv && \
    uv pip install --system psycopg2-binary && \
    uv pip install --system -r pyproject.toml

# Copy application code
COPY . .

# Create a non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
