.PHONY: help up down down-wipe build logs ps health task kill smoke smoke-week2 smoke-week25 smoke-week3 migrate shell

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
	@echo "  make up           Build images and start stack (incl. office UI)"
	@echo "  make down         Stop stack (keep volumes)"
	@echo "  make down-wipe    Stop and remove volumes"
	@echo "  make logs         Follow orchestrator logs"
	@echo "  make ps           Show compose services"
	@echo "  make health       Hit /health"
	@echo "  make smoke        Week 1: enqueue mock task and wait"
	@echo "  make smoke-week2  Week 2: index PRD → approve plan → multi-role merge"
	@echo "  make smoke-week25 Week 2.5: 12 tasks land on proving base"
	@echo "  make smoke-week3  Week 3: settings + SSE + HITL + office up"
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

smoke-week2:
	./scripts/smoke-week2.sh

smoke-week25:
	./scripts/smoke-week25.sh

smoke-week3:
	./scripts/smoke-week3.sh

shell:
	$(COMPOSE) exec orchestrator bash
