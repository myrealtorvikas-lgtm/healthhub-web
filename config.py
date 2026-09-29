"""
All configuration comes from environment variables (see .env.example), never
hard-coded — so the same code works locally and on Render, and no secret
ever ends up committed to a repo.
"""
import os
from dotenv import load_dotenv

load_dotenv()  # no-op in production if there's no .env file; Render sets real env vars


def _require(name, default=None):
    val = os.environ.get(name, default)
    if val is None:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in for local testing, "
            f"or set it in your hosting platform's dashboard."
        )
    return val


class Config:
    SECRET_KEY = _require("FLASK_SECRET_KEY", "dev-only-insecure-key-change-me")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///healthhub.db")
    # Render (and most Postgres hosts) hand out "postgres://" but SQLAlchemy 2.x
    # wants "postgresql://" — normalize so we don't have to think about it again.
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Where uploaded export files (Whoop, Oura, Apple Health, ...) are saved
    # before/until a parser exists for them. Local disk by default; on a
    # real host this should point at persistent storage (a mounted volume
    # or object storage), since Render's own local disk doesn't survive
    # a redeploy.
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "uploads"))

    # How much history to show per person in the report (currently only
    # bounds the CGM window — see report_builder.py for what's actually
    # wired up).
    REPORT_WINDOW_DAYS = 90
