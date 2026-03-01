FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PyEz if needed
RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt-dev \
    libz-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared models and backend code
COPY shared/ /app/shared/
COPY backend/app/ /app/backend/app/

ENV PYTHONPATH=/app

CMD ["uvicorn", "backend.app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
