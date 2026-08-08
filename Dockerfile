# Cobalt web service. One image, two roles: the long-lived web server and the
# one-shot ETL run — they share code, so they must share an image.
#
# python:3.12-slim is multi-arch (amd64 + arm64), which is most of what "runs on
# any hardware" means here.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is cached and only busts when requirements
# change, so editing pages or app code rebuilds in seconds rather than minutes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY etl/ etl/
COPY web/ web/

# Run unprivileged. /data must exist and be owned here, because Docker seeds a
# fresh named volume from the image's directory ownership — without this, the
# volume mounts root-owned and a non-root process cannot write the database.
RUN useradd --create-home --uid 10001 cobalt \
 && mkdir -p /data \
 && chown -R cobalt:cobalt /data /app
USER cobalt

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
