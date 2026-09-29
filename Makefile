.PHONY: install run check evals evals-real demo

install:
	uv sync

run:
	uv run uvicorn app.main:create_app --factory --reload

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest --cov

evals:
	uv run python -m evals.run --provider fake --out evals/report.md

evals-real:
	uv run python -m evals.run --provider real --out evals/report.md

demo:
	docker compose up --build
