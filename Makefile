include Makefile.config
-include .env
.SILENT:

.PHONY: dev init-db doctor \
        docker-env docker-build docker-pull docker-up docker-down \
        docker-ps docker-logs docker-shell docker-admin docker-doctor \
        i18n-extract i18n-update i18n-compile i18n-init i18n-sync \
        build-client build-assets \
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
		echo "$(DOCKER_ENV) already exists; leaving it unchanged."; \
	else \
		cp .env.docker.example $(DOCKER_ENV); \
		printf 'POSTGRES_PASSWORD=%s\n' "$$(openssl rand -hex 24)" >> $(DOCKER_ENV); \
		echo "Created $(DOCKER_ENV) with a generated POSTGRES_PASSWORD."; \
	fi

docker-build: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) build

docker-pull: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) pull

docker-up: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) up --detach

# Pass DOWN_ARGS=--volumes to delete the database and object volumes.
docker-down: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) down $(DOWN_ARGS)

docker-ps: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) ps

docker-logs: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) logs --follow --tail 100

docker-shell: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) exec web sh

# Prompts for the password; the value never reaches the command line or make arguments.
docker-admin: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) exec web quirebase create-admin --username "$(ADMIN_USERNAME)"

docker-doctor: docker-env
	$(COMPOSE) --env-file $(DOCKER_ENV) exec web quirebase doctor

# Launch parallel targets and terminate all if any one exits
make-p:
	set -m; (for p in $(P); do ($(MAKE) $$p || kill 0)& done; wait)

# --- i18n / Babel Workflow ---
i18n-extract:
	$(PYBABEL) extract -F $(BABEL_CFG) -o $(POT_FILE) --project quirebase $(SRC_DIR)

i18n-update:
	$(PYBABEL) update -i $(POT_FILE) -d $(LOCALES_DIR)

i18n-compile:
	$(PYBABEL) compile -d $(LOCALES_DIR)

i18n-init:
	@if [ -z "$(LOCALE)" ]; then \
		echo "Error: Please specify a locale with LOCALE=<lang_code>, e.g. make i18n-init LOCALE=fr"; \
		exit 1; \
	fi
	$(PYBABEL) init -i $(POT_FILE) -d $(LOCALES_DIR) -l $(LOCALE)

i18n-sync: i18n-extract
	$(MAKE) i18n-update i18n-compile

# --- Client & Frontend Assets ---
build-assets: build-client

build-client:
	$(BUN) scripts/build-assets.mjs
	$(BUN) run build:app

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
	$(PYTEST) -q -m "not oa"

test-oa:
	$(PYTEST) -q -m oa

# --- Housekeeping ---
clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .cache
	rm -rf $(SRC_DIR)/__pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

clean-install: clean
	rm -rf node_modules
	rm -rf $(VENV)
	rm -rf dist *.egg-info
