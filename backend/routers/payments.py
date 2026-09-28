import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import MobileMoneyAccount, Notification, Order, Payment, User
from pricing import USD_TO_ZIG_RATE, convert_usd_to_zig
from routers.auth import get_current_user, get_secret_hash, verify_secret

router = APIRouter(prefix="/payments", tags=["payments"])

SUPPORTED_PAYMENT_METHODS = {"cash", "card", "mobile_money"}
SUPPORTED_CURRENCIES = {"USD", "ZiG"}
SUPPORTED_MOBILE_MONEY_PROVIDERS = {"ecocash", "onemoney", "innbucks"}
DEFAULT_DEMO_WALLET_BALANCE_USD = 150.0


class PaymentCreate(BaseModel):
    order_id: int
    payment_method: str  # 'card', 'cash', 'mobile_money'
    currency: str = "USD"
    mobile_money_provider: Optional[str] = None
    mobile_money_number: Optional[str] = None
    mobile_money_pin: Optional[str] = None


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    amount: float
    amount_usd: float
    currency: str
    exchange_rate: float
    payment_method: str
    mobile_money_provider: Optional[str] = None
    mobile_money_number: Optional[str] = None
    provider_reference: Optional[str] = None
    status: str
    transaction_id: str
    created_at: Optional[datetime] = None


def normalize_currency(currency: str) -> str:
    normalized = (currency or "USD").strip()
    if normalized.upper() == "USD":
        return "USD"
    if normalized.upper() == "ZIG":
        return "ZiG"
    return normalized


def serialize_payment(payment: Payment) -> PaymentResponse:
    amount_usd = payment.amount_usd if payment.amount_usd is not None else payment.amount
    exchange_rate = payment.exchange_rate if payment.exchange_rate is not None else 1.0

    return PaymentResponse(
        id=payment.id,
        order_id=payment.order_id,
        amount=payment.amount,
        amount_usd=amount_usd,
        currency=payment.currency or "USD",
        exchange_rate=exchange_rate,
        payment_method=payment.payment_method,
        mobile_money_provider=payment.mobile_money_provider,
        mobile_money_number=payment.mobile_money_number,
        provider_reference=payment.provider_reference,
        status=payment.status,
        transaction_id=payment.transaction_id,
        created_at=payment.created_at,
    )


def validate_payment_request(payment: PaymentCreate):
    payment_method = payment.payment_method.strip().lower()
    currency = normalize_currency(payment.currency)
    provider = payment.mobile_money_provider.strip().lower() if payment.mobile_money_provider else None
    mobile_number = payment.mobile_money_number.strip() if payment.mobile_money_number else None
    mobile_pin = payment.mobile_money_pin.strip() if payment.mobile_money_pin else None

    if payment_method not in SUPPORTED_PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Unsupported payment method")

    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail="Unsupported currency")

    if payment_method == "mobile_money":
        if not provider or provider not in SUPPORTED_MOBILE_MONEY_PROVIDERS:
            raise HTTPException(status_code=400, detail="Select a supported mobile money provider")
        if not mobile_number or len(mobile_number) < 8:
            raise HTTPException(status_code=400, detail="Enter a valid mobile money number")
        if not mobile_pin or len(mobile_pin) < 4:
            raise HTTPException(status_code=400, detail="Enter the mobile money PIN for this account")

    return payment_method, currency, provider, mobile_number, mobile_pin


def get_or_create_mobile_money_account(
    db: Session,
    *,
    user: User,
    provider: str,
    mobile_number: str,
    mobile_pin: str,
) -> MobileMoneyAccount:
    account = (
        db.query(MobileMoneyAccount)
        .filter(
            MobileMoneyAccount.provider == provider,
            MobileMoneyAccount.account_number == mobile_number,
        )
        .first()
    )

    if account is None:
        account = MobileMoneyAccount(
            user_id=user.id,
            provider=provider,
            account_number=mobile_number,
            pin_hash=get_secret_hash(mobile_pin),
            balance_usd=DEFAULT_DEMO_WALLET_BALANCE_USD,
        )
        db.add(account)
        db.flush()
        return account

    if account.user_id != user.id:
        raise HTTPException(status_code=403, detail="That mobile money account is linked to another customer")

    if not verify_secret(mobile_pin, account.pin_hash):
        raise HTTPException(status_code=400, detail="Incorrect mobile money PIN")

    return account


def create_notification(
    db: Session,
    *,
    user_id: Optional[int],
    order_id: int,
    title: str,
    message: str,
):
    if user_id is None:
        return

    db.add(
        Notification(
            user_id=user_id,
            order_id=order_id,
            title=title,
            message=message,
        )
    )


@router.post("/", response_model=PaymentResponse)
def create_payment(
    payment: PaymentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payment_method, currency, provider, mobile_number, mobile_pin = validate_payment_request(payment)

    order = db.query(Order).filter(Order.id == payment.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if order.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cancelled orders cannot be paid for")

    existing_payment = db.query(Payment).filter(Payment.order_id == payment.order_id).first()
    if existing_payment:
        raise HTTPException(status_code=400, detail="Payment already exists")

    amount_usd = round(order.total_amount, 2)
    exchange_rate = 1.0 if currency == "USD" else USD_TO_ZIG_RATE
    amount = amount_usd if currency == "USD" else convert_usd_to_zig(amount_usd)
    provider_reference = (
        f"MM-{uuid.uuid4().hex[:10].upper()}" if payment_method == "mobile_money" else None
    )

    if payment_method == "mobile_money":
        account = get_or_create_mobile_money_account(
            db,
            user=current_user,
            provider=provider,
            mobile_number=mobile_number,
            mobile_pin=mobile_pin,
        )
        if account.balance_usd < amount_usd:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient funds in your {provider.title()} account. "
                    f"Available balance is ${account.balance_usd:.2f}."
                ),
            )
        account.balance_usd = round(account.balance_usd - amount_usd, 2)

    db_payment = Payment(
        order_id=payment.order_id,
        amount=amount,
        amount_usd=amount_usd,
        currency=currency,
        exchange_rate=exchange_rate,
        payment_method=payment_method,
        mobile_money_provider=provider,
        mobile_money_number=mobile_number,
        provider_reference=provider_reference,
        status="completed",
        transaction_id=str(uuid.uuid4()),
    )
    db.add(db_payment)
    create_notification(
        db,
        user_id=current_user.id,
        order_id=order.id,
        title="Payment successful",
        message=(
            f"Your payment for request MR-{order.id} was received successfully. "
            f"{'The rider has been notified and can now transport your goods.' if order.rider_id else 'A rider will be notified once one is assigned.'}"
        ),
    )
    create_notification(
        db,
        user_id=order.rider_id,
        order_id=order.id,
        title="Payment confirmed",
        message=f"Payment for request MR-{order.id} has been completed. You can now transport the required goods.",
    )
    db.commit()
    db.refresh(db_payment)
    return serialize_payment(db_payment)


@router.get("/", response_model=List[PaymentResponse])
def list_payments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Payment).join(Order, Order.id == Payment.order_id)
    if current_user.role == "customer":
        query = query.filter(Order.customer_id == current_user.id)
    elif current_user.role == "rider":
        query = query.filter(Order.rider_id == current_user.id)

    payments = query.order_by(Payment.created_at.desc()).all()
    return [serialize_payment(payment) for payment in payments]


@router.get("/{order_id}", response_model=PaymentResponse)
def get_payment(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if (
        order.customer_id != current_user.id
        and order.rider_id != current_user.id
        and current_user.role != "admin"
    ):
        raise HTTPException(status_code=403, detail="Not authorized")

    return serialize_payment(payment)
