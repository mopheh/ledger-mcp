from tests.conftest import run_alembic


def test_models_match_migrated_schema():
    """Fails when a model changes without a migration."""
    result = run_alembic("check")
    assert result.returncode == 0, result.stdout + result.stderr
