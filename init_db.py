"""Explicit first-boot initializer for Render/Postgres or local SQLite."""
from app import app
from bootstrap import bootstrap_database, database_summary


if __name__ == "__main__":
    with app.app_context():
        bootstrap_database()
        summary = database_summary()
        print(
            "Denmart database ready: "
            f"dialect={summary['dialect']} stores={summary['store_count']} "
            f"business={summary['has_business']}"
        )
