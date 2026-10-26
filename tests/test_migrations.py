import os
import subprocess


def test_migrations_use_postgresql_boolean_default():
    output = subprocess.run(
        [".venv/bin/alembic", "upgrade", "head", "--sql"],
        env={**os.environ, "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test"},
        capture_output=True,
        text=True,
        check=True,
    )
    ddl = output.stdout
    assert "is_current BOOLEAN DEFAULT true NOT NULL" in ddl


def test_sqlite_migrations_upgrade_and_downgrade(tmp_path, monkeypatch):
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'migration.sqlite3'}"}
    for command in [("upgrade", "head"), ("check",), ("downgrade", "base"), ("upgrade", "head")]:
        result = subprocess.run(
            [".venv/bin/alembic", *command], env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
