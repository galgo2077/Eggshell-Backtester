# Use official slim Python 3.11 image
FROM python:3.11-slim

# Set runtime environment config
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Install build tools for numerical acceleration packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Designate container base operations
WORKDIR /app

# Optimized Dependency Cache Injection (Flat layout compatible)
COPY config/requirements.txt ./config/requirements.txt

# Direct library stack resolution
RUN pip install --no-cache-dir -r config/requirements.txt

# Bulk merge application sources
COPY . .

# System Command Target (TUI integration enabled)
CMD ["python", "src/main.py"]
