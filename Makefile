COMPOSE = docker compose
APP = bot

.PHONY: build up down restart logs migrate migration shell db-shell redis-cli clean status ps pull

build:
	$(COMPOSE) build --no-cache --parallel

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart $(APP)

logs:
	$(COMPOSE) logs -f $(APP) --tail=100

logs-all:
	$(COMPOSE) logs -f --tail=50

migrate:
	$(COMPOSE) exec $(APP) python -m alembic upgrade head

migration:
	$(COMPOSE) exec $(APP) python -m alembic revision --autogenerate -m "$(name)"

shell:
	$(COMPOSE) exec $(APP) /bin/bash

db-shell:
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-botuser} $${POSTGRES_DB:-saas_bot}

redis-cli:
	$(COMPOSE) exec redis redis-cli

redis-flush:
	$(COMPOSE) exec redis redis-cli flushdb

clean:
	$(COMPOSE) down -v --remove-orphans

ps:
	$(COMPOSE) ps

status:
	$(COMPOSE) ps
	@echo ""
	@echo "=== Bot logs (last 30 lines) ==="
	$(COMPOSE) logs --tail=30 $(APP)

pull:
	git pull && $(COMPOSE) up -d --build

deploy: pull migrate

health:
	curl -s http://localhost:8080/health | python3 -m json.tool
