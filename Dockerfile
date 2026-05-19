FROM python:3.10-slim

WORKDIR /app

# Install system dependencies needed for Playwright/Chromium
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and its Chromium dependencies
RUN playwright install --with-deps chromium

# Copy the rest of your application code
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]