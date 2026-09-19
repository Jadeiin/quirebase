# syntax=docker/dockerfile:1.7

# Build the standalone Svelte application without writing into the Python source tree.
FROM oven/bun:1.4.2 AS assets
WORKDIR /build/frontend
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend ./
RUN bun run build

# The project environment lives at the same path in both stages so the copied
# console-script shebangs stay valid.
FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.14 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependency layer: manifests only, workspace packages are installed below.
COPY pyproject.toml uv.lock ./
COPY packages/inquiro/pyproject.toml packages/inquiro/pyproject.toml
COPY packages/rubrica/pyproject.toml packages/rubrica/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --extra postgres --extra citation

# Non-editable workspace install: Hatch includes frontend/build in the application wheel.
COPY . .
COPY --from=assets /build/frontend/build ./frontend/build
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --extra postgres --extra citation

FROM python:3.14-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QUIREBASE_DATA_DIR=/data \
    QUIREBASE_DATABASE_URL=sqlite:////data/quirebase.db

# pg_dump/pg_restore back up and restore PostgreSQL deployments, so the client
# major must not be older than the postgres:18 server in docker-compose.yml.
RUN set -eux; \
    apt-get update; \
    install -d /usr/share/postgresql-common/pgdg; \
    python -c "import urllib.request; urllib.request.urlretrieve('https://www.postgresql.org/media/keys/ACCC4CF8.asc', '/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc')"; \
    . /etc/os-release; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-18; \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 quirebase \
 && useradd --system --uid 10001 --gid quirebase --home-dir /data --shell /usr/sbin/nologin quirebase \
 && install -d -o quirebase -g quirebase /data
COPY --from=builder /opt/venv /opt/venv
USER 10001:10001
WORKDIR /data
VOLUME ["/data"]
EXPOSE 9060
STOPSIGNAL SIGTERM
CMD ["quirebase", "serve", "--host", "0.0.0.0", "--port", "9060"]
