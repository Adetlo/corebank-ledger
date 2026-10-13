"""ASGI entry point: ``uvicorn corebank.main:app``."""

from corebank.api.app import create_app

app = create_app()
