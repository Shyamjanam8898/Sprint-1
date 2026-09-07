"""Initialize the database tables defined in main.py.

Run this file from the project root using:
    python create_db.py
"""

from main import app, db
from main import *

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        print("Database tables created successfully.")
