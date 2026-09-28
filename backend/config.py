import os
from dotenv import load_dotenv

load_dotenv()

# Local configuration for offline mode
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30