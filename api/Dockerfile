FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required (e.g., for pandas or ccxt)
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Make sure we install fastapi and uvicorn even if they are missing from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt fastapi uvicorn pydantic

# In the docker-compose, the context is the root directory
COPY api ./api

# Allow Python to find the api module
ENV PYTHONPATH=/app

EXPOSE 8000

# uvicorn needs to listen on 0.0.0.0 for Docker port mapping to work
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
