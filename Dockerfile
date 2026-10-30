FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-inference.txt .
RUN python3 -m pip install -r requirements-inference.txt && \
    python3 -m pip uninstall -y onnxruntime onnxruntime-gpu && \
    python3 -m pip install "onnxruntime-gpu[cuda,cudnn]>=1.23.2,<1.24"

COPY inference_server.py .
CMD ["python3", "inference_server.py"]
