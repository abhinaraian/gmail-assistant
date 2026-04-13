FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer — only rebuilt when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/   ./src/
COPY server.py .
COPY main.py .

# The credentials/ directory is volume-mounted at runtime — create a placeholder
RUN mkdir -p credentials

EXPOSE 8000

CMD ["python", "server.py"]
