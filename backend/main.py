from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import admin, orders, riders, payments, ratings, auth, notifications
from database import engine, Base, SessionLocal, ensure_schema_upgrades
from models import User
from routers.auth import get_password_hash

app = FastAPI(title="Swift Local Deliveries API", version="1.0.0")


def bootstrap_default_admin():
    db = SessionLocal()
    try:
        existing_admin = db.query(User).filter(User.role == "admin").first()
        if existing_admin:
            return

        db.add(
            User(
                email="admin@motorush.local",
                username="admin",
                hashed_password=get_password_hash("admin1234"),
                full_name="MotoRush Admin",
                phone="0000000000",
                role="admin",
                is_active=True,
                rider_verification_status="not_required",
            )
        )
        db.commit()
    finally:
        db.close()

# Create database tables
Base.metadata.create_all(bind=engine)
ensure_schema_upgrades()
bootstrap_default_admin()

# CORS middleware for React frontend (allow local dev origins)
# Using allow_origins=["*"] simplifies local development and avoids port mismatch issues.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(orders.router)
app.include_router(riders.router)
app.include_router(payments.router)
app.include_router(ratings.router)
app.include_router(notifications.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to Swift Local Deliveries API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008)
