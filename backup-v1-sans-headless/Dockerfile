FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/src

# ffmpeg + fonts for the karaoke render path.
# fonts-montserrat matches the safe_zone metrics; DejaVu is the fallback.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-montserrat \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install uv from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Resolve deps first so source-only changes don't bust the cache.
COPY pyproject.toml README.md ./
COPY src/ /app/src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache .

# Copy the rest of the project (entry shim, scripts).
COPY . /app/

EXPOSE 8002

CMD ["python", "main.py"]
