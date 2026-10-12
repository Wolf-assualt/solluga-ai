FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl, ffmpeg (for audio processing) and sqlite3
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure data directory exists
RUN mkdir -p data

# Expose web dashboard & webhook port
EXPOSE 8000

# Default command starts the web dashboard and health endpoint
CMD ["sh", "-c", "python data/seed.py && uvicorn web.app:app --host 0.0.0.0 --port 8000"]
