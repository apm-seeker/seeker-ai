import logging
from pathlib import Path
from typing import Final

from sqlalchemy.engine.url import make_url

from app.config import get_settings

logger = logging.getLogger(__name__)

BASE_DIR: Final[Path] = Path(__file__).resolve().parents[2]


def ensure_database() -> None:
    """Create the application database if it does not exist (MySQL only).

    Idempotent. Called at startup so the rest of the boot sequence (migrations,
    engine creation) can assume the database exists.
    """
    settings = get_settings()
    url = make_url(settings.database_url)

    if not url.drivername.startswith("mysql"):
        logger.info(
            "ensure_database: skipping non-MySQL driver %r", url.drivername
        )
        return

    db_name = url.database
    if not db_name:
        raise RuntimeError(
            f"DATABASE_URL has no database name: {settings.database_url!r}"
        )

    if not all(ch.isalnum() or ch == "_" for ch in db_name):
        raise RuntimeError(
            f"refusing to CREATE DATABASE with non [A-Za-z0-9_] name: {db_name!r}"
        )

    import pymysql

    try:
        conn = pymysql.connect(
            host=url.host or "127.0.0.1",
            port=url.port or 3306,
            user=url.username,
            password=url.password,
            connect_timeout=5,
        )
    except Exception as exc:
        raise RuntimeError(
            f"cannot reach MySQL at {url.host}:{url.port or 3306} "
            f"to ensure database {db_name!r}: {exc}"
        ) from exc

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        logger.info("ensure_database: database %r is ready", db_name)
    finally:
        conn.close()


def run_migrations() -> None:
    """Run Alembic upgrade to head against the configured DATABASE_URL.

    Uses absolute paths so it works regardless of the current working
    directory the server was started from.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))

    logger.info("alembic: upgrade head")
    command.upgrade(cfg, "head")
    logger.info("alembic: upgrade complete")
