FROM python:3.13-slim

LABEL org.opencontainers.image.title="s3mirror" \
      org.opencontainers.image.description="Automation-friendly S3 bucket mirroring for S3-compatible endpoints" \
      org.opencontainers.image.source="https://github.com/netspeedy/s3mirror" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system s3mirror \
    && useradd --system --gid s3mirror --home-dir /app --no-create-home s3mirror

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY s3mirror.py ./

USER s3mirror

ENTRYPOINT ["python", "/app/s3mirror.py"]
CMD ["--help"]
