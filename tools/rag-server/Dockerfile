FROM python:3.12-slim

# System deps for chromadb (hnswlib requires g++ to build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY store.py main.py job_store.py ./

# Optional: pre-download the default ONNX embedding model so the first
# request doesn't stall. Only runs when EMBEDDING_PROVIDER=default.
# ARG PREFETCH_ONNX=false
# RUN if [ "$PREFETCH_ONNX" = "true" ]; then \
#       python -c "from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()"; \
#     fi

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=8s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "main.py"]
