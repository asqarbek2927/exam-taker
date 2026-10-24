.PHONY: install run migrate superuser seed test lint format schema

install:
	pip install -r requirements-dev.txt

run:
	python manage.py runserver

migrate:
	python manage.py migrate

superuser:
	python manage.py createsuperuser

seed:
	python manage.py seed_demo

test:
	DJANGO_SETTINGS_MODULE=config.settings.test pytest

lint:
	ruff check .
	ruff format --check .

format:
	ruff check . --fix
	ruff format .

schema:
	DJANGO_SETTINGS_MODULE=config.settings.test python manage.py spectacular --validate --fail-on-warn --file schema.yml
