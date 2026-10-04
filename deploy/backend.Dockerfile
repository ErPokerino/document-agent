# The DocuFlow API as a plain OCI image: runs on any container platform —
# Cloud Run, ECS/Fargate, Azure Container Apps, Kubernetes, or Docker on a VM.
# Nothing in it names a cloud; where state lives and who may call the API come
# from DOCUFLOW_* variables (backend/app/config.py).
FROM python:3.13-slim

# LightGBM links OpenMP at run time.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.lock.txt ./requirements.lock.txt
RUN pip install --no-cache-dir --requirement requirements.lock.txt

COPY backend/app ./app

# State lives on a mounted volume, never in the image.
ENV DOCUFLOW_DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PORT=8000
RUN useradd --create-home --uid 10001 docuflow \
    && mkdir -p /data \
    && chown docuflow /data
USER docuflow
VOLUME ["/data"]
EXPOSE 8000

# PORT is the convention most managed container platforms set.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
