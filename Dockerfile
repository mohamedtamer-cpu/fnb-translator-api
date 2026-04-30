# Base image khafta w saria [cite: 3]
FROM python:3.11-slim

# Set working directory gowa el container [cite: 3]
WORKDIR /app

# Copy requirements w satab-ha [cite: 3]
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt [cite: 4]

# Copy el code
COPY main.py .

# Efta7 port 8000 [cite: 5]
EXPOSE 8000

# Run el API [cite: 5]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]