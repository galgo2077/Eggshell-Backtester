# Use official slim Python 3.11 image
FROM python:3.11-slim

# Prevent bytecode files and force buffered log outputs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/Eggshell-Backtester/src

# Install necessary build utilities for high-performance compute libraries (numpy, vectorbt)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Define working container scope
WORKDIR /app

# Pre-seed dependency list to optimize docker caching pipeline
COPY Eggshell-Backtester/config/requirements.txt ./Eggshell-Backtester/config/requirements.txt

# Install the numerical stack libraries without caching local downloads
RUN pip install --no-cache-dir -r Eggshell-Backtester/config/requirements.txt

# Merge remaining software assets into container
COPY . .

# Establish runtime executable vector (Requires -it run flags for full viewport experience)
CMD ["python", "Eggshell-Backtester/src/main.py"]
