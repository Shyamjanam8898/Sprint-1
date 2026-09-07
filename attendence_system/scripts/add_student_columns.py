"""
Lightweight migration to add `Added_by` and `Created_at` to Student_reg.
Usage:
  (activate your venv)
  python scripts/add_student_columns.py

This connects using the `local_uri` from `config.json` and safely adds the two columns
if they don't already exist. It's written for MySQL (INFORMATION_SCHEMA) and uses
SQLAlchemy to connect so it respects the same connection string your app uses.
"""
import json
import sys
from sqlalchemy import create_engine, text


def main():
    try:
        with open('config.json', 'r') as f:
            cfg = json.load(f).get('parameters', {})
    except Exception as e:
        print('Failed to read config.json:', e)
        sys.exit(1)

    uri = cfg.get('local_uri') or cfg.get('local_uri')
    if not uri:
        print('No `local_uri` found in config.json parameters.')
        sys.exit(1)

    try:
        engine = create_engine(uri)
    except Exception as e:
        print('Failed to create engine from URI:', e)
        sys.exit(1)

    db_name = engine.url.database
    if not db_name:
        print('Could not determine database name from URI.')
        sys.exit(1)

    checks = [
        ('Added_by', "ALTER TABLE Student_reg ADD COLUMN Added_by VARCHAR(80) NULL"),
        ('Created_at', "ALTER TABLE Student_reg ADD COLUMN Created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP")
    ]

    with engine.connect() as conn:
        for col, ddl in checks:
            try:
                q = text("SELECT COUNT(*) as c FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=:schema AND TABLE_NAME='Student_reg' AND COLUMN_NAME=:col")
                res = conn.execute(q, {'schema': db_name, 'col': col}).scalar()
                if res and int(res) > 0:
                    print(f"Column `{col}` already exists — skipping.")
                    continue
            except Exception as e:
                print('Warning: failed to check INFORMATION_SCHEMA, attempting to add column anyway. Error:', e)

            try:
                print(f"Adding column {col}...")
                conn.execute(text(ddl))
                print(f"Added column {col}.")
            except Exception as e:
                print(f"Failed to add column {col}:", e)
                print('Rolling on to next column.')

    print('Migration script finished.')


if __name__ == '__main__':
    main()
