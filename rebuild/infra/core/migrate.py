"""Run explicit forward-only migrations, never at API import/startup."""
from pathlib import Path
from alembic import command
from alembic.config import Config


def main():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "migrations"))
    command.upgrade(config, "head")
    print("Migration upgrade completed")


if __name__ == "__main__":
    main()
