FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Зависимости отдельным слоем: пересобираются только при изменении lock-файла.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY app ./app
COPY data ./data

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
