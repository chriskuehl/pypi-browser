.PHONY: test
test:
	poetry run coverage run -m pytest tests
	poetry run coverage report
	poetry run mypy pypi_view
	poetry run pre-commit run --all-files

.PHONY: start-dev
start-dev:
	PYPI_VIEW_DEBUG=1 poetry run uvicorn --reload --port 5000 pypi_view.app:app
