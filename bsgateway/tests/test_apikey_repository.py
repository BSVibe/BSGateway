"""API key repository schema initialization."""

from bsgateway.apikey.repository import split_sql_statements


def test_split_sql_statements_ignores_semicolons_inside_line_comments() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS api_keys (id UUID PRIMARY KEY);

    -- Legacy hashes had a UNIQUE(key_hash) constraint; drop if present.
    ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_key_hash_key;

    -- Drop obsolete hash index; lookup now uses prefix.
    DROP INDEX IF EXISTS idx_api_keys_hash;
    """

    statements = split_sql_statements(sql)

    assert statements == [
        "CREATE TABLE IF NOT EXISTS api_keys (id UUID PRIMARY KEY)",
        (
            "-- Legacy hashes had a UNIQUE(key_hash) constraint; drop if present.\n"
            "    ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_key_hash_key"
        ),
        (
            "-- Drop obsolete hash index; lookup now uses prefix.\n"
            "    DROP INDEX IF EXISTS idx_api_keys_hash"
        ),
    ]
