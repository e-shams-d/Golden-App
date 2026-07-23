"""Environment-loaded Celery CLI entrypoint."""

from app.core.config import load_settings
from app.workers.celery_app import create_celery_app

celery_app = create_celery_app(load_settings())
