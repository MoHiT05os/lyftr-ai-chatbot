.PHONY: up down restart logs test clean

up:
	docker compose up --build -d

down:
	docker compose down

restart:
	docker compose down && docker compose up --build -d

logs:
	docker compose logs -f

test:
	python -m pytest backend/tests -v

clean:
	docker compose down -v
