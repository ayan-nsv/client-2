FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install PostgreSQL client for wait script
RUN apt-get update && apt-get install -y postgresql-client && rm -rf /var/lib/apt/lists/*

# Image to text
RUN apt-get update && apt-get install -y tesseract-ocr && rm -rf /var/lib/apt/lists/*

# product scrapper — pin Chromium at image build time (Candidate from apt at build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    chromium \
    chromium-driver \
    fonts-liberation \
 && chromium --version \
 && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

COPY requirements.txt /app/
# Use --no-cache-dir and upgrade pip to avoid hash mismatch from stale cache
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --default-timeout=300 -r requirements.txt


# Copy project
COPY . /app/

# Optional full-repo filter. Prefer exporting a subset tree with
# scripts/export_client_tree.py so the build context never contains unpaid code.
# When INSTALL_PRODUCTS is set here, unpaid packages are deleted inside the image.
ARG INSTALL_PRODUCTS=
ENV INSTALL_PRODUCTS=${INSTALL_PRODUCTS}
RUN python /app/scripts/filter_shipped_products.py

# Make wait script executable; run app as non-root (Chrome --no-sandbox is gated by non-root + seccomp)
RUN chmod +x /app/wait-for-db.sh

# RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser \
#     && chown -R appuser:appuser /app

# USER appuser

EXPOSE 8000
#CMD ["/app/wait-for-db.sh", "host.docker.internal", "5432", "user", "marketing_planner", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
CMD ["./wait-for-db.sh", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
