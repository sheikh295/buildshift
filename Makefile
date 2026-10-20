.PHONY: help up down down-wipe build logs ps health task kill smoke smoke-plan smoke-merge-queue smoke-office smoke-hud migrate shell

COMPOSE ?= docker compose
BUILDSHIFT_URL ?= http://127.0.0.1:8080
DASHBOARD_URL ?= http://127.0.0.1:3000
HOST_DATA_DIR ?= $(CURDIR)/data
export BUILDSHIFT_URL
export DASHBOARD_URL
export HOST_DATA_DIR

help:
	@echo "Buildshift — portable Compose stack"
	@echo ""
	@echo "  make up                Build images and start stack (incl. office UI)"
	@echo "  make down              Stop stack (keep volumes)"
	@echo "  make down-wipe         Stop and remove volumes"
	@echo "  make logs              Follow orchestrator logs"
	@echo "  make ps                Show compose services"
	@echo "  make health            Hit /health"
	@echo "  make smoke             Enqueue mock task and wait"
	@echo "  make smoke-plan        Index PRD → approve plan → multi-role merge"
	@echo "  make smoke-merge-queue 12 tasks land on proving base"
	@echo "  make smoke-office      Settings + SSE + HITL + office up"
	@echo "  make smoke-hud         Projects / sprints / HITL tree / usage"
	@echo "  make task ARGS='create \"title\" -c \"...\"'"
	@echo "  make kill ARGS='true|false'"

up: build
	$(COMPOSE) up -d postgres litellm orchestrator dashboard
	@echo "Orchestrator: $(BUILDSHIFT_URL)"
	@echo "Office UI:    $(DASHBOARD_URL)"

build:
	$(COMPOSE) build worker orchestrator dashboard
	@# Tag is set by compose image: for worker; ensure local name exists
	$(COMPOSE) build worker

down:
	$(COMPOSE) down

down-wipe:
	$(COMPOSE) down -v
	rm -rf data/repos data/worktrees data/remotes data/tmp-seed-demo

logs:
	$(COMPOSE) logs -f orchestrator dashboard

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

smoke-plan:
	./scripts/smoke-plan.sh

smoke-merge-queue:
	./scripts/smoke-merge-queue.sh

smoke-office:
	./scripts/smoke-office.sh

smoke-hud:
	./scripts/smoke-hud.sh

shell:
	$(COMPOSE) exec orchestrator bash
