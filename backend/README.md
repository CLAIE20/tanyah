# Swift Local Deliveries Backend

A FastAPI backend for the Swift Local Deliveries application, providing REST APIs for user authentication, order management, rider tracking, payments, and ratings.

## Features

- **User Authentication**: Register and login for customers, riders, and admins
- **Order Management**: Create, update, and list delivery orders
- **Rider Tracking**: Update rider locations and find nearby available riders
- **Payment Integration**: Mock payment processing for completed deliveries
- **Instant Matching**: Automatically assign orders to the nearest available rider
- **Rider Rating**: Rate riders after successful deliveries

## Tech Stack

- **FastAPI**: Modern, fast web framework for building APIs
- **SQLAlchemy**: SQL toolkit and ORM
- **SQLite**: Lightweight database
- **JWT**: JSON Web Tokens for authentication
- **Geopy**: Geolocation calculations for rider matching

## Installation

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

Start the server with:
```bash
python main.py
```

The API will be available at `http://localhost:8000`

## API Documentation

Once the server is running, visit `http://localhost:8000/docs` for interactive API documentation powered by Swagger UI.

## Database

The application uses SQLite database (`swift_deliveries.db`) which will be created automatically when you first run the application.

## Authentication

The API uses JWT tokens for authentication. Include the token in the Authorization header:
```
Authorization: Bearer <your-jwt-token>
```

## API Endpoints

### Authentication
- `POST /auth/register` - Register a new user
- `POST /auth/token` - Login and get access token
- `GET /auth/me` - Get current user info

### Orders
- `POST /orders/` - Create a new order (auto-assigns nearest rider)
- `GET /orders/` - List orders (filtered by user role)
- `PUT /orders/{order_id}` - Update order status

### Riders
- `POST /riders/location` - Update rider location and availability
- `GET /riders/nearby` - Get nearby available riders

### Payments
- `POST /payments/` - Process payment for delivered order
- `GET /payments/{order_id}` - Get payment details

### Ratings
- `POST /ratings/` - Rate a rider after delivery
- `GET /ratings/rider/{rider_id}` - Get rider's average rating and reviews

## Integration with Frontend

The API is designed to work with the React frontend. Make sure to update CORS origins in `main.py` if your frontend runs on a different port.

## Security Notes

- Change the `SECRET_KEY` in `routers/auth.py` for production
- Implement proper password policies
- Add rate limiting for production deployment
- Use HTTPS in production