from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from jose import JWTError, jwt
import hashlib
import secrets
from database import get_db
from models import MobileMoneyAccount, User
from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/auth", tags=["auth"])

security = HTTPBearer()

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

def verify_password(plain_password, hashed_password):
    return verify_secret(plain_password, hashed_password)

def verify_secret(plain_value, hashed_value):
    # Support both legacy "$salt$hash" values and the corrected "salt$hash" format.
    parts = hashed_value.split('$')
    if len(parts) == 3 and parts[0] == "":
        _, salt, hashed = parts
    elif len(parts) == 2:
        salt, hashed = parts
    else:
        return False
    return hashlib.sha256((plain_value + salt).encode()).hexdigest() == hashed

def get_password_hash(password):
    return get_secret_hash(password)

def get_secret_hash(value):
    # Simple SHA256 hashing with salt
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((value + salt).encode()).hexdigest()
    return f"{salt}${hashed}"

def provision_demo_mobile_money_accounts(db: Session, user: User):
    normalized_phone = (user.phone or "").strip()
    if not normalized_phone:
        return

    for provider in ("ecocash", "onemoney"):
        existing_account = (
            db.query(MobileMoneyAccount)
            .filter(
                MobileMoneyAccount.provider == provider,
                MobileMoneyAccount.account_number == normalized_phone,
            )
            .first()
        )
        if existing_account:
            continue

        db.add(
            MobileMoneyAccount(
                user_id=user.id,
                provider=provider,
                account_number=normalized_phone,
                pin_hash=get_secret_hash("1234"),
                balance_usd=150.0,
            )
        )

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

class UserCreate(BaseModel):
    email: str
    username: str
    full_name: str
    phone: str
    password: str
    role: str  # 'customer', 'rider', 'admin'
    vehicle_registration_number: Optional[str] = None
    drivers_license_number: Optional[str] = None

class UserResponse(BaseModel):
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


def normalize_vehicle_registration_number(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    normalized = "".join(character for character in value.upper().strip() if character.isalnum())
    if not normalized:
        return None
    if len(normalized) < 5 or len(normalized) > 12:
        raise HTTPException(
            status_code=400,
            detail="Vehicle registration number must be 5 to 12 letters or numbers",
        )
    return normalized


def normalize_drivers_license_number(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    normalized = "".join(character for character in value.upper().strip() if character.isalnum())
    if not normalized:
        return None
    if len(normalized) < 6 or len(normalized) > 20:
        raise HTTPException(
            status_code=400,
            detail="Licence number must be 6 to 20 letters or numbers",
        )
    return normalized


def require_admin_user(current_user: User):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def require_approved_rider(current_user: User):
    if current_user.role != "rider":
        raise HTTPException(status_code=403, detail="Only riders can perform this action")
    if current_user.rider_verification_status != "approved":
        raise HTTPException(
            status_code=403,
            detail="Your rider account is still awaiting approval. An admin must verify your vehicle registration number and licence first.",
        )

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    try:
        if user.role not in {"customer", "rider", "admin"}:
            raise HTTPException(status_code=400, detail="Invalid role selected")

        # Check for existing email
        db_user = db.query(User).filter(User.email == user.email).first()
        if db_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Check for existing username
        db_user = db.query(User).filter(User.username == user.username).first()
        if db_user:
            raise HTTPException(status_code=400, detail="Username already registered")

        vehicle_registration_number = normalize_vehicle_registration_number(user.vehicle_registration_number)
        drivers_license_number = normalize_drivers_license_number(user.drivers_license_number)

        if user.role == "rider":
            if not vehicle_registration_number:
                raise HTTPException(status_code=400, detail="Vehicle registration number is required for riders")
            if not drivers_license_number:
                raise HTTPException(status_code=400, detail="Licence number is required for riders")
            duplicate_vehicle = (
                db.query(User)
                .filter(User.vehicle_registration_number == vehicle_registration_number)
                .first()
            )
            if duplicate_vehicle:
                raise HTTPException(status_code=400, detail="That vehicle registration number is already in use")
            duplicate_licence = (
                db.query(User)
                .filter(User.drivers_license_number == drivers_license_number)
                .first()
            )
            if duplicate_licence:
                raise HTTPException(status_code=400, detail="That licence number is already in use")

        # Create new user
        hashed_password = get_password_hash(user.password)
        db_user = User(
            email=user.email,
            username=user.username,
            hashed_password=hashed_password,
            full_name=user.full_name,
            phone=user.phone,
            role=user.role,
            is_active=True,
            vehicle_registration_number=vehicle_registration_number,
            drivers_license_number=drivers_license_number,
            rider_verification_status="pending" if user.role == "rider" else "not_required",
            rider_submitted_at=datetime.utcnow() if user.role == "rider" else None,
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        provision_demo_mobile_money_accounts(db, db_user)
        db.commit()
        return db_user
    except HTTPException:
        raise
    except Exception as e:
        print(f"Registration error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@router.post("/login", response_model=Token)
def login(user_credentials: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_credentials.email).first()
    if not user or not verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user
