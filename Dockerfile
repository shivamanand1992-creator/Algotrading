# Multi-stage build for Python backend + React frontend
FROM node:18-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --prefer-offline
COPY frontend/ ./
RUN npm run build

# Python runtime
FROM python:3.10-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir 'setuptools<68' && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/
COPY data/ ./data/
COPY execution/ ./execution/
COPY features/ ./features/
COPY models/ ./models/
COPY strategies/ ./strategies/

# Copy frontend build from builder stage
COPY --from=frontend-builder /app/frontend/build ./frontend/build/

# Create necessary directories
RUN mkdir -p logs /data/trained_models

EXPOSE 8080

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
