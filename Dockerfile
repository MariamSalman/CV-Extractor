FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Install tectonic using the statically-linked musl build (no shared lib dependencies)
ARG TECTONIC_VERSION=0.15.0
RUN curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic@${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
    -o /tmp/tectonic.tar.gz \
    && tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic \
    && chmod +x /usr/local/bin/tectonic \
    && rm -f /tmp/tectonic.tar.gz \
    && tectonic --version

# Pre-cache LaTeX packages
RUN printf '%s\n' \
    '\documentclass[10pt,a4paper]{article}' \
    '\usepackage[T1]{fontenc}' \
    '\usepackage[utf8]{inputenc}' \
    '\usepackage[english,french]{babel}' \
    '\usepackage{geometry}' \
    '\usepackage{enumitem}' \
    '\usepackage{xcolor}' \
    '\usepackage{hyperref}' \
    '\usepackage{titlesec}' \
    '\usepackage{tabularx}' \
    '\usepackage{graphicx}' \
    '\usepackage{fontawesome5}' \
    '\usepackage{array}' \
    '\begin{document}' \
    'Hello World' \
    '\end{document}' > /tmp/warmup.tex \
    && tectonic /tmp/warmup.tex \
    && rm -f /tmp/warmup.*

WORKDIR /app

# Install python deps
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy source
COPY . .

# Defaults
EXPOSE 5000

CMD ["python", "smart_cv_app/app.py"]
