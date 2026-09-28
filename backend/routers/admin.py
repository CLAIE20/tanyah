from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import User
from routers.auth import (
    get_current_user,
    normalize_drivers_license_number,
    normalize_vehicle_registration_number,
    require_admin_user,
)

router = APIRouter(prefix="/admin", tags=["admin"])

ALLOWED_REVIEW_STATUSES = {"approved", "rejected"}
ALLOWED_LIST_STATUSES = {"pending", "approved", "rejected"}


class AdminUserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: str
    phone: str
    role: str
    is_active: bool
    vehicle_registration_number: Optional[str] = None
    drivers_license_number: Optional[str] = None
    rider_verification_status: Optional[str] = None
    rider_verification_notes: Optional[str] = None
    rider_submitted_at: Optional[datetime] = None
    rider_verified_at: Optional[datetime] = None


class RiderVerificationReviewRequest(BaseModel):
    status: str
    notes: Optional[str] = None


def serialize_admin_user(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        phone=user.phone,
        role=user.role,
        is_active=user.is_active,
        vehicle_registration_number=user.vehicle_registration_number,
        drivers_license_number=user.drivers_license_number,
        rider_verification_status=user.rider_verification_status,
        rider_verification_notes=user.rider_verification_notes,
        rider_submitted_at=user.rider_submitted_at,
        rider_verified_at=user.rider_verified_at,
    )


def ensure_unique_rider_documents(db: Session, rider: User):
    normalized_vehicle_registration = normalize_vehicle_registration_number(rider.vehicle_registration_number)
    normalized_licence = normalize_drivers_license_number(rider.drivers_license_number)

    if not normalized_vehicle_registration:
        raise HTTPException(status_code=400, detail="Vehicle registration number is missing")
    if not normalized_licence:
        raise HTTPException(status_code=400, detail="Licence number is missing")

    rider.vehicle_registration_number = normalized_vehicle_registration
    rider.drivers_license_number = normalized_licence

    duplicate_vehicle = (
        db.query(User)
        .filter(
            User.id != rider.id,
            User.role == "rider",
            User.vehicle_registration_number == normalized_vehicle_registration,
        )
        .first()
    )
    if duplicate_vehicle:
        raise HTTPException(status_code=400, detail="Vehicle registration number is already linked to another rider")

    duplicate_licence = (
        db.query(User)
        .filter(
            User.id != rider.id,
            User.role == "rider",
            User.drivers_license_number == normalized_licence,
        )
        .first()
    )
    if duplicate_licence:
        raise HTTPException(status_code=400, detail="Licence number is already linked to another rider")


@router.get("/users", response_model=List[AdminUserResponse])
def list_users(
    search: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_user(current_user)

    query = db.query(User)
    if search:
        search_term = f"%{search.strip()}%"
        query = query.filter(
            (User.full_name.ilike(search_term))
            | (User.email.ilike(search_term))
            | (User.username.ilike(search_term))
        )

    users = query.order_by(User.created_at.desc(), User.id.desc()).all()
    return [serialize_admin_user(user) for user in users]


@router.get("/riders", response_model=List[AdminUserResponse])
def list_riders_for_verification(
    status: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_user(current_user)

    query = db.query(User).filter(User.role == "rider")
    if status:
        normalized_status = status.strip().lower()
        if normalized_status not in ALLOWED_LIST_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid rider verification filter")
        query = query.filter(User.rider_verification_status == normalized_status)

    riders = query.order_by(User.rider_submitted_at.desc(), User.created_at.desc(), User.id.desc()).all()
    return [serialize_admin_user(rider) for rider in riders]


@router.put("/riders/{rider_id}/verification", response_model=AdminUserResponse)
def review_rider_verification(
    rider_id: int,
    review: RiderVerificationReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin_user(current_user)

    rider = db.query(User).filter(User.id == rider_id, User.role == "rider").first()
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    normalized_status = review.status.strip().lower()
    if normalized_status not in ALLOWED_REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="Verification status must be approved or rejected")

    if normalized_status == "approved":
        ensure_unique_rider_documents(db, rider)

    rider.rider_verification_status = normalized_status
    rider.rider_verification_notes = (review.notes or "").strip() or None
    rider.rider_verified_at = datetime.utcnow()
    rider.rider_verified_by_id = current_user.id

    db.commit()
    db.refresh(rider)
    return serialize_admin_user(rider)
