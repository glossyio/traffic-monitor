from helpers import SCHEMA_DIR, migrate


def test_schema_sql_matches_the_migrations(capsys):
    # schema.sql is the readable data model; it must not lag behind the migrations.
    assert migrate("--dump-schema") == 0

    assert capsys.readouterr().out == (SCHEMA_DIR / "schema.sql").read_text(), (
        "schema.sql is out of date. Regenerate it with:\n"
        "  python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema"
        " > container/node-red-tm/schema/schema.sql"
    )
