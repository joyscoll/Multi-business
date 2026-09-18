import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.sql.sqltypes import JSON, Date, DateTime, Numeric

from extensions import db


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"__type__": "decimal", "value": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__type__": "bytes", "value": bytes(value).hex()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


def _restore_value(column, value):
    if isinstance(value, dict) and "__type__" in value:
        t = value.get("__type__")
        raw = value.get("value")
        if t == "datetime":
            return datetime.fromisoformat(raw)
        if t == "decimal":
            return Decimal(raw)
        if t == "bytes":
            return bytes.fromhex(raw)
    if value is None:
        return None
    typ = column.type
    if isinstance(typ, JSON):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value
    if isinstance(typ, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(typ, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(typ, Numeric) and isinstance(value, str):
        return Decimal(value)
    if getattr(typ, "python_type", None) is bool and isinstance(value, (int, str)):
        return str(value).lower() in {"1", "true", "yes", "on"}
    return value


def export_database_json():
    """Export every application table and row as a portable JSON snapshot."""
    tables = {}
    for table in db.metadata.sorted_tables:
        rows = db.session.execute(table.select()).mappings().all()
        tables[table.name] = [{k: _jsonable(v) for k, v in row.items()} for row in rows]
    return {
        "format": "denmart-database-v2",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "dialect": db.engine.url.get_backend_name(),
        "table_counts": {name: len(rows) for name, rows in tables.items()},
        "tables": tables,
    }


def restore_database_json(payload):
    """Replace the live database with a compatible JSON snapshot."""
    db.create_all()
    if not isinstance(payload, dict) or payload.get("format") not in {"denmart-database-v2", "real-mart-json-v1"}:
        raise ValueError("Unsupported backup format. Choose a Real Mart JSON backup.")
    tables_data = payload.get("tables") or {}
    known = {t.name: t for t in db.metadata.sorted_tables}
    missing = [name for name in tables_data if name not in known]
    if missing:
        raise ValueError(f"Backup contains unknown tables: {', '.join(missing[:8])}")

    db.session.rollback()
    dialect = db.engine.url.get_backend_name()
    if dialect == "sqlite":
        db.session.execute(text("PRAGMA foreign_keys=OFF"))
    elif dialect == "postgresql":
        names = ", ".join('"' + t.name.replace('"', '""') + '"' for t in db.metadata.sorted_tables)
        if names:
            db.session.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))

    try:
        if dialect != "postgresql":
            for table in reversed(db.metadata.sorted_tables):
                db.session.execute(table.delete())
        for table in db.metadata.sorted_tables:
            rows = tables_data.get(table.name, [])
            if not rows:
                continue
            columns = {c.name: c for c in table.columns}
            cleaned = []
            for raw in rows:
                item = {k: _restore_value(columns[k], v) for k, v in raw.items() if k in columns}
                cleaned.append(item)
            db.session.execute(table.insert(), cleaned)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        if dialect == "sqlite":
            db.session.execute(text("PRAGMA foreign_keys=ON"))
            db.session.commit()


def _sqlite_value(column, value):
    # SQLite's SQLAlchemy Date/DateTime bind processors expect Python date/datetime
    # objects and will serialize them correctly for the target database.
    if isinstance(column.type, (DateTime, Date)) and isinstance(value, (datetime, date)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(column.type, JSON) and value is not None:
        return _jsonable(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    return value


def _stream_table_rows(connection, table, batch_size=2000):
    result = connection.execution_options(stream_results=True).execute(table.select()).mappings()
    while True:
        batch = result.fetchmany(batch_size)
        if not batch:
            break
        yield batch


def _write_backup_manifest(connection, counts, source_dialect):
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS __denmart_backup_manifest ("
        "id INTEGER PRIMARY KEY, format TEXT NOT NULL, exported_at TEXT NOT NULL, "
        "source_dialect TEXT NOT NULL, table_counts TEXT NOT NULL)"
    )
    manifest = json.dumps(counts, ensure_ascii=False, separators=(",", ":"))
    connection.exec_driver_sql(
        "INSERT INTO __denmart_backup_manifest "
        "(format, exported_at, source_dialect, table_counts) VALUES (?, ?, ?, ?)",
        ("denmart-sqlite-v3", datetime.now(timezone.utc).isoformat(), source_dialect, manifest),
    )


def create_sqlite_snapshot(path: str | Path, batch_size: int = 2000):
    """Create and verify a complete SQLite snapshot of every application table."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    source_engine = db.engine
    target_engine = create_engine(f"sqlite:///{path}", future=True)
    counts = {}
    try:
        db.metadata.create_all(target_engine)
        source_conn = db.session.connection()
        for table in db.metadata.sorted_tables:
            columns = {c.name: c for c in table.columns}
            written = 0
            with target_engine.begin() as target:
                for rows in _stream_table_rows(source_conn, table, batch_size=batch_size):
                    cleaned = [{k: _sqlite_value(columns[k], v) for k, v in row.items()} for row in rows]
                    if cleaned:
                        target.execute(table.insert(), cleaned)
                        written += len(cleaned)
            counts[table.name] = written

        with target_engine.begin() as target:
            _write_backup_manifest(target, counts, source_engine.url.get_backend_name())

        with sqlite3.connect(str(path)) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("SQLite integrity check failed while creating the backup.")
            fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_errors:
                raise ValueError("SQLite foreign-key verification failed while creating the backup.")
            for table_name, expected in counts.items():
                quoted = table_name.replace('"', '""')
                actual = conn.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]
                if actual != expected:
                    raise ValueError(f"SQLite backup verification failed for {table_name}.")
    finally:
        target_engine.dispose()


def inspect_sqlite_tables(path: str | Path):
    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE '__denmart_%' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]


def restore_sqlite_snapshot(path: str | Path, batch_size: int = 2000):
    """Replace the application database from a complete verified SQLite snapshot."""
    db.create_all()
    path = Path(path)
    if not path.exists():
        raise ValueError("SQLite backup file not found.")

    with sqlite3.connect(str(path)) as raw:
        integrity = raw.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("The SQLite backup failed its integrity check and was not restored.")
        if raw.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("The SQLite backup contains foreign-key errors and was not restored.")

    source = create_engine(f"sqlite:///{path}")
    available = set(inspect_sqlite_tables(path))
    known = {t.name: t for t in db.metadata.sorted_tables}
    if "businesses" not in available:
        source.dispose()
        raise ValueError("This is not a Real Mart database snapshot.")
    missing_known = [t.name for t in db.metadata.sorted_tables if t.name not in available]
    if missing_known:
        source.dispose()
        raise ValueError(
            "SQLite backup is incomplete; missing tables: " + ", ".join(missing_known[:8])
            + (" …" if len(missing_known) > 8 else "")
        )
    unknown = available - set(known)
    if unknown:
        source.dispose()
        raise ValueError(
            "SQLite backup contains unsupported tables: " + ", ".join(sorted(unknown)[:8])
            + (" …" if len(unknown) > 8 else "")
        )

    db.session.rollback()
    dialect = db.engine.url.get_backend_name()
    if dialect == "sqlite":
        db.session.execute(text("PRAGMA foreign_keys=OFF"))
    elif dialect == "postgresql":
        names = ", ".join('"' + t.name.replace('"', '""') + '"' for t in db.metadata.sorted_tables)
        if names:
            db.session.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))

    try:
        if dialect != "postgresql":
            for table in reversed(db.metadata.sorted_tables):
                db.session.execute(table.delete())

        target_conn = db.session.connection()
        with source.connect() as source_conn:
            for table in db.metadata.sorted_tables:
                columns = {c.name: c for c in table.columns}
                for rows in _stream_table_rows(source_conn, table, batch_size=batch_size):
                    cleaned = [{k: _restore_value(columns[k], v) for k, v in row.items() if k in columns} for row in rows]
                    if cleaned:
                        target_conn.execute(table.insert(), cleaned)

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        source.dispose()
        if dialect == "sqlite":
            db.session.execute(text("PRAGMA foreign_keys=ON"))
            db.session.commit()
