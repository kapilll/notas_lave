# Stage 1: Build dependencies (has gcc/g++ for pandas/numpy)
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install . 2>/dev/null || pip install --no-cache-dir --prefix=/install -e .

# Stage 2: Runtime (no gcc/g++, smaller image)
FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

RUN mkdir -p data

EXPOSE 8000

CMD ["python", "run.py"]
