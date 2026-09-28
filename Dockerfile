FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

WORKDIR /app
COPY requirements.txt ./
# Keep the Python package aligned with the Chromium bundled in the base image.
RUN python -m pip install --no-cache-dir -r requirements.txt "playwright==1.63.0"

COPY *.py ./

# The image already contains this unprivileged user and the browser binaries.
USER pwuser
WORKDIR /output
ENTRYPOINT ["python", "/app/enrich_dealers.py"]
