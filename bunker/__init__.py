"""Athlete Bunker — local triathlon training analytics."""
from pathlib import Path

from flask import Flask

from . import db as database
from .fmt import register_filters


def create_app(db_path=None):
    root = Path(__file__).resolve().parent.parent
    app = Flask(__name__,
                template_folder=str(root / "templates"),
                static_folder=str(root / "static"))
    app.config["DATABASE"] = str(db_path or root / "data" / "athlete_bunker.db")
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # batch uploads

    database.init_db(app.config["DATABASE"])
    app.teardown_appcontext(database.close_db)
    register_filters(app)

    from .routes import bp
    app.register_blueprint(bp)
    return app
