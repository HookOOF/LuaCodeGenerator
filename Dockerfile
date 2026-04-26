FROM python:3.11-slim

RUN apt update && \
    apt install -y --no-install-recommends lua5.4 curl wget dpkg zstd gnupg2 && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://ollama.com/install.sh | sh

RUN wget https://github.com/qdrant/qdrant/releases/download/v1.14.0/qdrant_1.14.0-1_amd64.deb
RUN dpkg -i qdrant_1.14.0-1_amd64.deb


WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY knowledge/ knowledge/
COPY scripts/ scripts/

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
