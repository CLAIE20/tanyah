from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from geopy.distance import geodesic
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import FavoriteRider, Order, RiderLocation, User
from routers.auth import get_current_user, require_approved_rider

router = APIRouter(prefix="/riders", tags=["riders"])


class LocationUpdate(BaseModel):
    latitude: float
    longitude: float
    is_available: bool = True


class RiderLocationResponse(BaseModel):
    rider_id: int
    rider_name: Optional[str] = None
    phone: Optional[str] = None
    latitude: float
    longitude: float
    is_available: bool
    distance_km: Optional[float] = None


def serialize_rider_location(rider_loc: RiderLocation, distance_km: Optional[float] = None) -> RiderLocationResponse:
    rider = rider_loc.rider
    return RiderLocationResponse(
        rider_id=rider_loc.rider_id,
        rider_name=rider.full_name if rider else None,
        phone=rider.phone if rider else None,
        latitude=rider_loc.latitude,
        longitude=rider_loc.longitude,
        is_available=rider_loc.is_available,
        distance_km=distance_km,
    )    


class FavoriteRiderResponse(BaseModel):
    rider_id: int
    rider_name: Optional[str] = None
    phone: Optional[str] = None
    is_available: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    updated_at: Optional[datetime] = None


class FavoriteRiderToggleResponse(BaseModel):
    rider_id: int
    is_favorite: bool


def serialize_favorite_rider(
    favorite: FavoriteRider,
    rider_location: Optional[RiderLocation] = None,
) -> FavoriteRiderResponse:
    rider = favorite.rider
    return FavoriteRiderResponse(
        rider_id=favorite.rider_id,
        rider_name=rider.full_name if rider else None,
        phone=rider.phone if rider else None,
        is_available=bool(rider_location.is_available) if rider_location else False,
        latitude=rider_location.latitude if rider_location else None,
        longitude=rider_location.longitude if rider_location else None,
        updated_at=rider_location.updated_at if rider_location else None,
    )


@router.post("/location", response_model=RiderLocationResponse)
def update_location(
    location: LocationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_approved_rider(current_user)

    has_active_order = (
        db.query(Order)
        .filter(Order.rider_id == current_user.id, Order.status.in_(["assigned", "picked_up"]))
        .first()
        is not None
    )
    effective_availability = location.is_available and not has_active_order

    rider_loc = db.query(RiderLocation).filter(RiderLocation.rider_id == current_user.id).first()
    if rider_loc:
        rider_loc.latitude = location.latitude
        rider_loc.longitude = location.longitude
        rider_loc.is_available = effective_availability
        rider_loc.updated_at = datetime.utcnow()
    else:
        rider_loc = RiderLocation(
            rider_id=current_user.id,
            latitude=location.latitude,
            longitude=location.longitude,
            is_available=effective_availability,
            updated_at=datetime.utcnow(),
        )
        db.add(rider_loc)

    db.commit()
    db.refresh(rider_loc)
    return serialize_rider_location(rider_loc)


@router.get("/nearby", response_model=List[RiderLocationResponse])
def get_nearby_riders(lat: float, lng: float, radius_km: float = 5.0, db: Session = Depends(get_db)):
    riders = (
        db.query(RiderLocation)
        .join(User, User.id == RiderLocation.rider_id)
        .filter(
            RiderLocation.is_available == True,
            User.role == "rider",
            User.rider_verification_status == "approved",
        )
        .all()
    )
    nearby_riders = []

    for rider in riders:
        distance = geodesic((lat, lng), (rider.latitude, rider.longitude)).km
        if distance <= radius_km:
            nearby_riders.append((distance, rider))

    nearby_riders.sort(key=lambda item: item[0])
    return [serialize_rider_location(rider, round(distance, 2)) for distance, rider in nearby_riders]


@router.get("/favorites", response_model=List[FavoriteRiderResponse])
def list_favorite_riders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can manage favorite riders")

    favorites = (
        db.query(FavoriteRider)
        .filter(FavoriteRider.customer_id == current_user.id)
        .order_by(FavoriteRider.created_at.desc(), FavoriteRider.id.desc())
        .all()
    )

    rider_ids = [favorite.rider_id for favorite in favorites]
    rider_locations = (
        db.query(RiderLocation)
        .join(User, User.id == RiderLocation.rider_id)
        .filter(
            RiderLocation.rider_id.in_(rider_ids),
            User.rider_verification_status == "approved",
        )
        .all()
        if rider_ids
        else []
    )
    location_by_rider_id = {location.rider_id: location for location in rider_locations}

    return [
        serialize_favorite_rider(favorite, location_by_rider_id.get(favorite.rider_id))
        for favorite in favorites
    ]


@router.post("/{rider_id}/favorite", response_model=FavoriteRiderToggleResponse)
def add_favorite_rider(
    rider_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can manage favorite riders")

    rider = db.query(User).filter(User.id == rider_id, User.role == "rider").first()
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    favorite = (
        db.query(FavoriteRider)
        .filter(FavoriteRider.customer_id == current_user.id, FavoriteRider.rider_id == rider_id)
        .first()
    )
    if not favorite:
        db.add(FavoriteRider(customer_id=current_user.id, rider_id=rider_id))
        db.commit()

    return FavoriteRiderToggleResponse(rider_id=rider_id, is_favorite=True)


@router.delete("/{rider_id}/favorite", response_model=FavoriteRiderToggleResponse)
def remove_favorite_rider(
    rider_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can manage favorite riders")

    favorite = (
        db.query(FavoriteRider)
        .filter(FavoriteRider.customer_id == current_user.id, FavoriteRider.rider_id == rider_id)
        .first()
    )
    if favorite:
        db.delete(favorite)
        db.commit()

    return FavoriteRiderToggleResponse(rider_id=rider_id, is_favorite=False)
