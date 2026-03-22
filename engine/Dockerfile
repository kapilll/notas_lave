FROM python:3.13-slim

WORKDIR /app

# System deps for pandas/numpy compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir . 2>/dev/null || pip install --no-cache-dir -e .

# Copy engine source
COPY . .

# Create data directory for SQLite + logs
RUN mkdir -p data

# Expose API port
EXPOSE 8000

# Run engine (both Lab + Production start together)
CMD ["python", "run.py"]
