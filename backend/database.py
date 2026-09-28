import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Use SQLite for offline functionality
DATABASE_URL = "sqlite:///./local_database.db"

print("Connecting to SQLite database...")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def ensure_schema_upgrades():
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "payments" in table_names:
            payment_columns = {column["name"] for column in inspector.get_columns("payments")}
            payment_column_definitions = {
                "amount_usd": "FLOAT",
                "currency": "VARCHAR DEFAULT 'USD'",
                "exchange_rate": "FLOAT DEFAULT 1.0",
                "mobile_money_provider": "VARCHAR",
                "mobile_money_number": "VARCHAR",
                "provider_reference": "VARCHAR",
            }

            for column_name, definition in payment_column_definitions.items():
                if column_name in payment_columns:
                    continue
                connection.execute(text(f"ALTER TABLE payments ADD COLUMN {column_name} {definition}"))

        if "users" in table_names:
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            user_column_definitions = {
                "vehicle_registration_number": "VARCHAR",
                "drivers_license_number": "VARCHAR",
                "rider_verification_status": "VARCHAR DEFAULT 'not_required'",
                "rider_verification_notes": "TEXT",
                "rider_submitted_at": "DATETIME",
                "rider_verified_at": "DATETIME",
                "rider_verified_by_id": "INTEGER",
            }

            for column_name, definition in user_column_definitions.items():
                if column_name in user_columns:
                    continue
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {definition}"))

            connection.execute(
                text(
                    """
                    UPDATE users
                    SET rider_verification_status = 'pending'
                    WHERE role = 'rider'
                      AND (rider_verification_status IS NULL OR rider_verification_status = '' OR rider_verification_status = 'not_required')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE users
                    SET rider_submitted_at = COALESCE(rider_submitted_at, created_at)
                    WHERE role = 'rider'
                      AND rider_verification_status = 'pending'
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE users
                    SET rider_verification_status = 'not_required'
                    WHERE role != 'rider'
                      AND (rider_verification_status IS NULL OR rider_verification_status = '')
                    """
                )
            )

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
