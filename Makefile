.PHONY: help run backend frontend test test-backend test-frontend migrate docker-up docker-down

help:
	@echo "Available commands:"
	@echo "  make run            - Run both Backend and Frontend locally"
	@echo "  make backend        - Run Backend API server locally (port 8000)"
	@echo "  make frontend       - Run Frontend Vite server locally (port 5173)"
	@echo "  make migrate        - Run Alembic database migrations"
	@echo "  make test           - Run full test suite (backend + frontend)"
	@echo "  make test-backend   - Run backend pytest suite"
	@echo "  make test-frontend  - Run frontend vitest suite"
	@echo "  make docker-up      - Start local Postgres (pgvector) and Redis in Docker"
	@echo "  make docker-down    - Stop local Docker services"

run:
	./run_local.sh

backend:
	.venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

migrate:
	.venv/bin/alembic -c backend/alembic.ini upgrade head

test: test-backend test-frontend

test-backend:
	.venv/bin/pytest backend/tests/ -q --no-cov

test-frontend:
	cd frontend && npx vitest run

docker-up:
	docker compose up -d

docker-down:
	docker compose down
