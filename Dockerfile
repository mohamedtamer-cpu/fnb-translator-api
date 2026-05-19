# Use the official Playwright Python image (comes with all OS dependencies pre-installed)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Just install the browser binaries (dependencies are already pre-baked into the base image!)
RUN playwright install chromium

# Copy the rest of your application code
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]