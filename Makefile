include Makefile.config
-include .env
.SILENT:

.PHONY: dev init-db doctor \
        docker-env docker-build docker-pull docker-up docker-up-s3 \
        docker-down docker-down-s3 docker-ps docker-logs docker-shell \
        docker-admin docker-doctor \
        build-frontend \
        check-all lint-all lint-python format-python type-check test-all test-oa \
        clean clean-install make-p

# --- Development & Operations ---
dev:
	sh scripts/dev.sh

init-db:
	$(QUIREBASE) init-db

doctor:
	$(QUIREBASE) doctor

# --- Containers (Docker or Podman) ---
docker-env:
	@if [ -f $(DOCKER_ENV) ]; then \
		chmod 600 $(DOCKER_ENV); \
		echo "$(DOCKER_ENV) already exists; leaving it unchanged."; \
	else \
		umask 077; \
		cp .env.docker.example $(DOCKER_ENV); \
		printf 'POSTGRES_PASSWORD=%s\n' "$$(openssl rand -hex 24)" >> $(DOCKER_ENV); \
		echo "Created $(DOCKER_ENV) (mode 0600) with a generated POSTGRES_PASSWORD."; \
	fi

docker-build: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(COMPOSE_FILES) build

docker-pull: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(COMPOSE_FILES) pull

docker-up: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(COMPOSE_FILES) up --detach

# Bundled single-node Garage plus S3 object storage.
docker-up-s3: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(S3_COMPOSE_FILES) up --detach

# Pass DOWN_ARGS=--volumes to delete the database and object volumes.
docker-down: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(COMPOSE_FILES) down $(DOWN_ARGS)

docker-down-s3: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(S3_COMPOSE_FILES) down $(DOWN_ARGS)

docker-ps: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(COMPOSE_FILES) ps

docker-logs: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(COMPOSE_FILES) logs --follow --tail 100

docker-shell: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(COMPOSE_FILES) exec web sh

# Prompts for the password; the value never reaches the command line or make arguments.
docker-admin: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(COMPOSE_FILES) exec web quirebase create-admin --username "$(ADMIN_USERNAME)"

docker-doctor: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) $(COMPOSE_FILES) exec web quirebase doctor

# Launch parallel targets and terminate all if any one exits
make-p:
	set -m; (for p in $(P); do ($(MAKE) $$p || kill 0)& done; wait)

# --- Frontend application ---
build-frontend:
	$(BUN) run --cwd frontend build

# --- Code Quality & Verification ---
check-all: lint-all type-check test-all

lint-all: lint-python

lint-python:
	$(RUFF) check .
	$(RUFF) format --check .

format-python:
	$(RUFF) format .
	$(RUFF) check --fix .

type-check:
	$(MYPY) $(SRC_DIR)

test-all:
	$(PYTEST) -q -m "not oa" -n 4 --dist loadscope

test-oa:
	$(PYTEST) -q -m oa

# --- Housekeeping ---
clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .cache
	rm -rf $(SRC_DIR)/__pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

clean-install: clean
	rm -rf node_modules frontend/node_modules
	rm -rf $(VENV)
	rm -rf dist *.egg-info
