FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-pol \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

ENV PATH="/opt/venv/bin:$PATH"
COPY src ./src
COPY classes ./classes
COPY config ./config

ENTRYPOINT ["python", "-m", "src"]
CMD ["run"]
