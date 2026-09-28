from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    full_name = Column(String)
    phone = Column(String)
    role = Column(String)  # 'customer', 'rider', 'admin'
    is_active = Column(Boolean, default=True)
    vehicle_registration_number = Column(String, nullable=True)
    drivers_license_number = Column(String, nullable=True)
    rider_verification_status = Column(String, default="not_required")
    rider_verification_notes = Column(Text, nullable=True)
    rider_submitted_at = Column(DateTime(timezone=True), nullable=True)
    rider_verified_at = Column(DateTime(timezone=True), nullable=True)
    rider_verified_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"))
    rider_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    pickup_address = Column(String)
    pickup_lat = Column(Float)
    pickup_lng = Column(Float)
    delivery_address = Column(String)
    delivery_lat = Column(Float)
    delivery_lng = Column(Float)
    status = Column(String, default="pending")  # pending, assigned, picked_up, delivered, cancelled
    item_description = Column(Text)
    estimated_value = Column(Float)
    delivery_fee = Column(Float)
    total_amount = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    customer = relationship("User", foreign_keys=[customer_id])
    rider = relationship("User", foreign_keys=[rider_id])

class RiderLocation(Base):
    __tablename__ = "rider_locations"

    id = Column(Integer, primary_key=True, index=True)
    rider_id = Column(Integer, ForeignKey("users.id"))
    latitude = Column(Float)
    longitude = Column(Float)
    is_available = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    rider = relationship("User")

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    amount = Column(Float)
    amount_usd = Column(Float, nullable=True)
    currency = Column(String, default="USD")
    exchange_rate = Column(Float, default=1.0)
    payment_method = Column(String)  # 'card', 'cash', etc.
    mobile_money_provider = Column(String, nullable=True)
    mobile_money_number = Column(String, nullable=True)
    provider_reference = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, completed, failed
    transaction_id = Column(String, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order")


class MobileMoneyAccount(Base):
    __tablename__ = "mobile_money_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "account_number", name="uq_mobile_money_provider_account"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    provider = Column(String, index=True)
    account_number = Column(String, index=True)
    pin_hash = Column(String)
    balance_usd = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")

class Rating(Base):
    __tablename__ = "ratings"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    customer_id = Column(Integer, ForeignKey("users.id"))
    rider_id = Column(Integer, ForeignKey("users.id"))
    rating = Column(Integer)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order")
    customer = relationship("User", foreign_keys=[customer_id])
    rider = relationship("User", foreign_keys=[rider_id])


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    title = Column(String)
    message = Column(Text)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    order = relationship("Order")


class FavoriteRider(Base):
    __tablename__ = "favorite_riders"
    __table_args__ = (
        UniqueConstraint("customer_id", "rider_id", name="uq_favorite_customer_rider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"))
    rider_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    customer = relationship("User", foreign_keys=[customer_id])
    rider = relationship("User", foreign_keys=[rider_id])
