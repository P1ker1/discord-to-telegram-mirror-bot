FROM python:3.12-slim-bookworm

# Prevent Python from writing .pyc files and enable unbuffered logging for docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source code and modular packages
COPY src/ ./src/
COPY main.py ./

# Create data directory for SQLite database persistence
RUN mkdir -p /app/data

# Run the bot
CMD ["python", "main.py"]
