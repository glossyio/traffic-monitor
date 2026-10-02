import pytest


@pytest.fixture
def db_path(tmp_path):
    """A not-yet-created tmdb.sqlite in a db/ directory, laid out like the device."""
    (tmp_path / "db").mkdir()
    return tmp_path / "db" / "tmdb.sqlite"


@pytest.fixture
def make_migrations(tmp_path):
    """Write {file name: SQL} into a migrations directory and return the directory."""

    def make(files):
        directory = tmp_path / "migrations"
        directory.mkdir(exist_ok=True)
        for name, sql in files.items():
            (directory / name).write_text(sql)
        return directory

    return make
