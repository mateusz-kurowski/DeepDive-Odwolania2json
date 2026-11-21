FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock .python-version ./
# extra `api`: FastAPI, uvicorn, boto3 (obraz służy i CLI, i API)
RUN uv sync --frozen --no-dev --extra api

ENV PATH="/opt/venv/bin:$PATH"
COPY src ./src
COPY classes ./classes
COPY config ./config

ENTRYPOINT ["python", "-m", "src"]
CMD ["run"]
