.PHONY: help up down down-wipe build logs ps health task kill smoke migrate shell

COMPOSE ?= docker compose
BUILDSHIFT_URL ?= http://127.0.0.1:8080
HOST_DATA_DIR ?= $(CURDIR)/data
export BUILDSHIFT_URL
export HOST_DATA_DIR

help:
	@echo "Buildshift — portable Compose stack"
	@echo ""
	@echo "  make up          Build images and start stack"
	@echo "  make down        Stop stack (keep volumes)"
	@echo "  make down-wipe   Stop and remove volumes"
	@echo "  make logs        Follow orchestrator logs"
	@echo "  make ps          Show compose services"
	@echo "  make health      Hit /health"
	@echo "  make smoke       Enqueue mock task and wait for completion"
	@echo "  make task ARGS='create \"title\" -c \"...\"'"
	@echo "  make kill ARGS='true|false'"

up: build
	$(COMPOSE) up -d postgres litellm orchestrator
	@echo "Orchestrator: $(BUILDSHIFT_URL)"

build:
	$(COMPOSE) build worker orchestrator
	@# Tag is set by compose image: for worker; ensure local name exists
	$(COMPOSE) build worker

down:
	$(COMPOSE) down

down-wipe:
	$(COMPOSE) down -v
	rm -rf data/repos data/worktrees data/remotes data/tmp-seed-demo

logs:
	$(COMPOSE) logs -f orchestrator

ps:
	$(COMPOSE) ps

health:
	curl -sf $(BUILDSHIFT_URL)/health | python3 -m json.tool

task:
	$(COMPOSE) run --rm --no-deps -e BUILDSHIFT_URL=http://orchestrator:8080 orchestrator \
		buildshift task $(ARGS)

kill:
	curl -sf -X POST $(BUILDSHIFT_URL)/control/kill \
		-H 'content-type: application/json' \
		-d '{"enabled": $(ARGS)}' | python3 -m json.tool

smoke:
	./scripts/smoke.sh

shell:
	$(COMPOSE) exec orchestrator bash
