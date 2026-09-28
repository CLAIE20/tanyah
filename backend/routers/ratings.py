from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import User, Order, Rating
from routers.auth import get_current_user

router = APIRouter(prefix="/ratings", tags=["ratings"])

class RatingCreate(BaseModel):
    order_id: int
    rating: int  # 1-5
    comment: str = None

class RatingResponse(BaseModel):
    id: int
    order_id: int
    customer_id: int
    rider_id: int
    rating: int
    comment: str = None

@router.post("/", response_model=RatingResponse)
def create_rating(rating_data: RatingCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can rate riders")
    
    order = db.query(Order).filter(Order.id == rating_data.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if order.status != "delivered":
        raise HTTPException(status_code=400, detail="Order not yet delivered")
    if not order.rider_id:
        raise HTTPException(status_code=400, detail="Order has no rider assigned")
    
    # Check if rating already exists
    existing_rating = db.query(Rating).filter(Rating.order_id == rating_data.order_id).first()
    if existing_rating:
        raise HTTPException(status_code=400, detail="Rating already exists for this order")
    
    if rating_data.rating < 1 or rating_data.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    
    db_rating = Rating(
        order_id=rating_data.order_id,
        customer_id=current_user.id,
        rider_id=order.rider_id,
        rating=rating_data.rating,
        comment=rating_data.comment
    )
    db.add(db_rating)
    db.commit()
    db.refresh(db_rating)
    return db_rating

@router.get("/rider/{rider_id}")
def get_rider_ratings(rider_id: int, db: Session = Depends(get_db)):
    ratings = db.query(Rating).filter(Rating.rider_id == rider_id).all()
    if not ratings:
        return {"average_rating": 0, "total_ratings": 0, "ratings": []}
    
    average = sum(r.rating for r in ratings) / len(ratings)
    return {
        "average_rating": round(average, 2),
        "total_ratings": len(ratings),
        "ratings": ratings
    }