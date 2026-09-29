.PHONY: install run check evals evals-real demo

install:
	uv sync

run:
	uv run uvicorn app.main:app --reload

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest

evals:
	@test -f evals/run.py || { echo "evals появятся на этапе M4"; exit 1; }
	uv run python -m evals.run --provider fake

evals-real:
	@test -f evals/run.py || { echo "evals появятся на этапе M4"; exit 1; }
	uv run python -m evals.run --provider real

demo:
	docker compose up --build
