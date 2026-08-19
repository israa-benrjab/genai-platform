FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch FIRST
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install everything else (including JWT, but without passlib)
RUN pip install --no-cache-dir \
    fastapi uvicorn httpx pydantic python-multipart \
    pypdf python-docx pandas python-pptx Pillow \
    sentence-transformers \
    qdrant-client \
    langgraph langchain langchain-community \
    tiktoken \
    python-jose[cryptography]

COPY fastapi-backend.py /app/main.py

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
