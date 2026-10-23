from alembic import context
from services.api.db import engine_for
from services.api.settings import Settings

settings = Settings.from_env()
if settings is None:
    raise RuntimeError("OMNIFORGE_CONFIG is required")
engine = engine_for(settings)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
