FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000

# System deps: LaTeX toolchain for tectonic and fontconfig
ARG TECTONIC_VERSION=0.15.0
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    fontconfig \
    && rm -rf /var/lib/apt/lists/* \
    && set -eux; \
    case "$TARGETARCH" in \
      amd64)  T_ARCH="x86_64-unknown-linux-gnu" ;; \
      arm64)  T_ARCH="aarch64-unknown-linux-musl" ;; \
      *) echo "Unsupported arch $TARGETARCH" && exit 1 ;; \
    esac; \
    T_TAG="tectonic@${TECTONIC_VERSION}"; \
    FILE="tectonic-${TECTONIC_VERSION}-${T_ARCH}.tar.gz"; \
    BASE="https://github.com/tectonic-typesetting/tectonic/releases/download/${T_TAG}"; \
    curl -fL -o /tmp/tectonic.tar.gz "${BASE}/${FILE}"; \
    tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic; \
    chmod +x /usr/local/bin/tectonic; \
    rm -f /tmp/tectonic.tar.gz

# Pre-cache LaTeX packages by compiling a sample document with all required packages
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
