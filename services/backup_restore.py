import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.sql.sqltypes import JSON, Date, DateTime, Numeric

from extensions import db


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"__type__": "decimal", "value": str(value)}
    if isinstance(value, (bytes, bytearray)):
        return {"__type__": "bytes", "value": value.hex()}
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
    tables = {}
    for table in db.metadata.sorted_tables:
        rows = db.session.execute(table.select()).mappings().all()
        tables[table.name] = [{k: _jsonable(v) for k, v in row.items()} for row in rows]
    return {
        "format": "denmart-database-v2",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "dialect": db.engine.url.get_backend_name(),
        "tables": tables,
    }


# Fresh installs may have no tables yet; create the current schema before replacement.
def restore_database_json(payload):
    db.create_all()
    if not isinstance(payload, dict) or payload.get("format") not in {"denmart-database-v2", "real-mart-json-v1"}:
        raise ValueError("Unsupported backup format.")
    tables_data = payload.get("tables") or {}
    known = {t.name: t for t in db.metadata.sorted_tables}
    missing = [name for name in tables_data if name not in known]
    if missing:
        raise ValueError(f"Backup contains unknown tables: {', '.join(missing[:8])}")

    # Disable FK checks for the duration of the replacement so the snapshot can
    # be restored exactly as captured, regardless of dependency order.
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


def create_sqlite_snapshot(path: str | Path):
    path = Path(path)
    if path.exists():
        path.unlink()
    engine = create_engine(f"sqlite:///{path}")
    db.metadata.create_all(engine)
    source_conn = db.session.connection()
    with engine.begin() as target:
        for table in db.metadata.sorted_tables:
            rows = source_conn.execute(table.select()).mappings().all()
            if not rows:
                continue
            columns = {c.name: c for c in table.columns}
            cleaned = []
            for row in rows:
                item = {}
                for k, value in row.items():
                    if isinstance(value, (datetime, date)):
                        item[k] = value.isoformat()
                    elif isinstance(value, Decimal):
                        item[k] = str(value)
                    elif isinstance(columns[k].type, JSON) and value is not None:
                        item[k] = json.dumps(value, default=str)
                    else:
                        item[k] = value
                cleaned.append(item)
            target.execute(table.insert(), cleaned)
    engine.dispose()


def inspect_sqlite_tables(path: str | Path):
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


# Make a fresh deployment schema-ready before importing a portable snapshot.
def restore_sqlite_snapshot(path: str | Path):
    db.create_all()
    path = Path(path)
    if not path.exists():
        raise ValueError("SQLite backup file not found.")
    source = create_engine(f"sqlite:///{path}")
    available = set(inspect(source).get_table_names())
    known = {t.name: t for t in db.metadata.sorted_tables}
    if "businesses" not in available:
        source.dispose()
        raise ValueError("This is not a Denmart database snapshot.")
    unknown = available - set(known)
    if unknown:
        source.dispose()
        raise ValueError(f"SQLite backup contains unsupported tables: {', '.join(sorted(unknown)[:8])}")

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
        with source.connect() as conn:
            for table in db.metadata.sorted_tables:
                if table.name not in available:
                    continue
                rows = conn.execute(table.select()).mappings().all()
                if not rows:
                    continue
                columns = {c.name: c for c in table.columns}
                cleaned = []
                for row in rows:
                    item = {k: _restore_value(columns[k], v) for k, v in row.items() if k in columns}
                    cleaned.append(item)
                if cleaned:
                    db.session.execute(table.insert(), cleaned)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        source.dispose()
        if dialect == "sqlite":
            db.session.execute(text("PRAGMA foreign_keys=ON"))
            db.session.commit()
