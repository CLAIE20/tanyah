from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from geopy.distance import geodesic
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models import Notification, Order, Payment, RiderLocation, User
from pricing import calculate_delivery_fee
from routers.auth import get_current_user, require_approved_rider

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderCreate(BaseModel):
    pickup_address: str
    pickup_lat: float
    pickup_lng: float
    delivery_address: str
    delivery_lat: float
    delivery_lng: float
    item_description: str
    estimated_value: float
    route_distance_km: Optional[float] = None
    selected_rider_id: Optional[int] = None


class OrderStatusUpdate(BaseModel):
    status: str


class OrderResponse(BaseModel):
    id: int
    customer_id: int
    rider_id: Optional[int]
    pickup_address: str
    pickup_lat: float
    pickup_lng: float
    delivery_address: str
    delivery_lat: float
    delivery_lng: float
    status: str
    item_description: str
    estimated_value: float
    delivery_fee: float
    total_amount: float
    created_at: Optional[datetime]
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    rider_name: Optional[str] = None
    rider_phone: Optional[str] = None
    rider_latitude: Optional[float] = None
    rider_longitude: Optional[float] = None
    rider_location_updated_at: Optional[datetime] = None


def serialize_order(order: Order, rider_location: Optional[RiderLocation] = None) -> OrderResponse:
    customer = order.customer
    rider = order.rider
    return OrderResponse(
        id=order.id,
        customer_id=order.customer_id,
        rider_id=order.rider_id,
        pickup_address=order.pickup_address,
        pickup_lat=order.pickup_lat,
        pickup_lng=order.pickup_lng,
        delivery_address=order.delivery_address,
        delivery_lat=order.delivery_lat,
        delivery_lng=order.delivery_lng,
        status=order.status,
        item_description=order.item_description,
        estimated_value=order.estimated_value,
        delivery_fee=order.delivery_fee,
        total_amount=order.total_amount,
        created_at=order.created_at,
        customer_name=customer.full_name if customer else None,
        customer_phone=customer.phone if customer else None,
        rider_name=rider.full_name if rider else None,
        rider_phone=rider.phone if rider else None,
        rider_latitude=rider_location.latitude if rider_location else None,
        rider_longitude=rider_location.longitude if rider_location else None,
        rider_location_updated_at=rider_location.updated_at if rider_location else None,
    )


def build_rider_location_map(db: Session, orders: List[Order]) -> Dict[int, RiderLocation]:
    rider_ids = sorted({order.rider_id for order in orders if order.rider_id is not None})
    if not rider_ids:
        return {}

    rider_locations = (
        db.query(RiderLocation)
        .filter(RiderLocation.rider_id.in_(rider_ids))
        .all()
    )
    return {location.rider_id: location for location in rider_locations}


def create_customer_notification(
    db: Session,
    *,
    customer_id: int,
    order_id: int,
    title: str,
    message: str,
):
    db.add(
        Notification(
            user_id=customer_id,
            order_id=order_id,
            title=title,
            message=message,
        )
    )


def create_user_notification(
    db: Session,
    *,
    user_id: int,
    order_id: int,
    title: str,
    message: str,
):
    db.add(
        Notification(
            user_id=user_id,
            order_id=order_id,
            title=title,
            message=message,
        )
    )


def set_rider_availability(db: Session, rider_id: Optional[int], *, is_available: bool):
    if rider_id is None:
        return

    rider_loc = db.query(RiderLocation).filter(RiderLocation.rider_id == rider_id).first()
    if rider_loc:
        rider_loc.is_available = is_available


def has_completed_payment(db: Session, order_id: int) -> bool:
    return (
        db.query(Payment)
        .filter(Payment.order_id == order_id, Payment.status == "completed")
        .first()
        is not None
    )


def find_nearest_rider(db: Session, pickup_lat: float, pickup_lng: float) -> Optional[int]:
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
    if not riders:
        return None

    nearest_rider = None
    min_distance = float("inf")
    for rider_loc in riders:
        distance = geodesic((pickup_lat, pickup_lng), (rider_loc.latitude, rider_loc.longitude)).km
        if distance < min_distance:
            min_distance = distance
            nearest_rider = rider_loc.rider_id
    return nearest_rider


@router.post("/", response_model=OrderResponse)
def create_order(
    order: OrderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can create orders")

    fallback_distance = geodesic((order.pickup_lat, order.pickup_lng), (order.delivery_lat, order.delivery_lng)).km
    distance_km = order.route_distance_km if order.route_distance_km and order.route_distance_km > 0 else fallback_distance
    delivery_fee = calculate_delivery_fee(distance_km)
    total_amount = delivery_fee

    rider_id = order.selected_rider_id
    if rider_id is not None:
        rider_loc = (
            db.query(RiderLocation)
            .join(User, User.id == RiderLocation.rider_id)
            .filter(
                RiderLocation.rider_id == rider_id,
                RiderLocation.is_available == True,
                User.role == "rider",
                User.rider_verification_status == "approved",
            )
            .first()
        )
        if not rider_loc:
            raise HTTPException(status_code=400, detail="Selected rider is no longer available")
    else:
        rider_id = find_nearest_rider(db, order.pickup_lat, order.pickup_lng)

    db_order = Order(
        customer_id=current_user.id,
        rider_id=rider_id,
        pickup_address=order.pickup_address,
        pickup_lat=order.pickup_lat,
        pickup_lng=order.pickup_lng,
        delivery_address=order.delivery_address,
        delivery_lat=order.delivery_lat,
        delivery_lng=order.delivery_lng,
        item_description=order.item_description,
        estimated_value=order.estimated_value,
        delivery_fee=delivery_fee,
        total_amount=total_amount,
        status="pending",
    )
    db.add(db_order)
    db.flush()

    if rider_id is not None:
        request_reason = (
            f"{current_user.full_name} requested you specifically"
            if order.selected_rider_id is not None
            else f"{current_user.full_name} was matched with you automatically"
        )
        create_user_notification(
            db,
            user_id=rider_id,
            order_id=db_order.id,
            title="New delivery request",
            message=(
                f"{request_reason} for request MR-{db_order.id}. "
                f"Pickup: {order.pickup_address}. Drop-off: {order.delivery_address}."
            ),
        )

    db.commit()

    db.refresh(db_order)
    rider_location = (
        db.query(RiderLocation).filter(RiderLocation.rider_id == db_order.rider_id).first()
        if db_order.rider_id is not None
        else None
    )
    return serialize_order(db_order, rider_location)


@router.get("/", response_model=List[OrderResponse])
def list_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "customer":
        orders = db.query(Order).filter(Order.customer_id == current_user.id).order_by(Order.created_at.desc()).all()
    elif current_user.role == "rider":
        rider_filters = [Order.rider_id == current_user.id]
        if current_user.rider_verification_status == "approved":
            rider_filters.append(Order.rider_id.is_(None) & (Order.status == "pending"))

        orders = db.query(Order).filter(or_(*rider_filters)).order_by(Order.created_at.desc()).all()
    else:
        orders = db.query(Order).order_by(Order.created_at.desc()).all()
    rider_location_map = build_rider_location_map(db, orders)
    return [serialize_order(order, rider_location_map.get(order.rider_id)) for order in orders]


@router.put("/{order_id}", response_model=OrderResponse)
def update_order(
    order_id: int,
    update: OrderStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if current_user.role == "customer" and order.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    valid_statuses = ["pending", "assigned", "picked_up", "delivered", "cancelled"]
    if update.status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")

    if current_user.role == "rider":
        require_approved_rider(current_user)
        is_targeted_to_other_rider = order.rider_id is not None and order.rider_id != current_user.id
        if is_targeted_to_other_rider:
            raise HTTPException(status_code=403, detail="Not authorized")

        if update.status == "assigned":
            if order.status != "pending":
                raise HTTPException(status_code=400, detail="Only pending requests can be accepted")
            order.rider_id = current_user.id
            order.status = "assigned"
            set_rider_availability(db, current_user.id, is_available=False)
            create_customer_notification(
                db,
                customer_id=order.customer_id,
                order_id=order.id,
                title="Rider accepted your request",
                message=f"{current_user.full_name} accepted delivery request MR-{order.id}.",
            )
        elif update.status == "cancelled":
            if order.rider_id != current_user.id:
                raise HTTPException(status_code=403, detail="Only the assigned rider can cancel this request")
            if order.status == "delivered":
                raise HTTPException(status_code=400, detail="Delivered orders cannot be cancelled")
            order.status = "cancelled"
            set_rider_availability(db, current_user.id, is_available=True)
            create_customer_notification(
                db,
                customer_id=order.customer_id,
                order_id=order.id,
                title="Rider cancelled your request",
                message=f"{current_user.full_name} cancelled delivery request MR-{order.id}.",
            )
        elif update.status == "picked_up":
            if order.rider_id != current_user.id:
                raise HTTPException(status_code=403, detail="Only the assigned rider can update this order")
            if order.status != "assigned":
                raise HTTPException(status_code=400, detail="Only assigned orders can be moved to transport")
            if not has_completed_payment(db, order.id):
                raise HTTPException(
                    status_code=400,
                    detail="Customer payment is still pending. Wait for payment confirmation before transporting goods.",
                )
            order.status = "picked_up"
            set_rider_availability(db, current_user.id, is_available=False)
            create_customer_notification(
                db,
                customer_id=order.customer_id,
                order_id=order.id,
                title="Goods in transit",
                message=f"{current_user.full_name} has started transporting the goods for request MR-{order.id}.",
            )
        elif update.status == "delivered":
            if order.rider_id != current_user.id:
                raise HTTPException(status_code=403, detail="Only the assigned rider can complete this order")
            if order.status != "picked_up":
                raise HTTPException(status_code=400, detail="Mark the goods as in transit before completing delivery")
            order.status = "delivered"
            set_rider_availability(db, current_user.id, is_available=True)
            create_customer_notification(
                db,
                customer_id=order.customer_id,
                order_id=order.id,
                title="Delivery completed",
                message=f"Your delivery request MR-{order.id} has been marked as delivered.",
            )
        else:
            raise HTTPException(status_code=403, detail="Riders cannot set that status")
    else:
        if current_user.role == "customer":
            if update.status != "cancelled":
                raise HTTPException(status_code=403, detail="Customers can only cancel their own orders")
            if order.status == "delivered":
                raise HTTPException(status_code=400, detail="Delivered orders cannot be cancelled")
            order.status = "cancelled"
            set_rider_availability(db, order.rider_id, is_available=True)
        else:
            order.status = update.status
            if update.status in {"pending", "cancelled", "delivered"}:
                set_rider_availability(db, order.rider_id, is_available=True)

    db.commit()
    db.refresh(order)
    rider_location = (
        db.query(RiderLocation).filter(RiderLocation.rider_id == order.rider_id).first()
        if order.rider_id is not None
        else None
    )
    return serialize_order(order, rider_location)
