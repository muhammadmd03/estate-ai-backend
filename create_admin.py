from app.db import SessionLocal
from app.models import User
from app.auth import hash_password
db = SessionLocal()

user = db.query(User).filter(User.email == "admin@test.com").first()

user.password_hash = hash_password("123456")

db.commit()
db.close()

print("Password reset successful")

existing = db.query(User).filter(User.email == "admin@test.com").first()

if existing:
    print("Admin already exists")
else:
    admin = User(
        email="admin@test.com",
        password_hash=hash_password("123456"),
        client_id="client_001"
    )

    db.add(admin)
    db.commit()
    print("Admin created successfully")

db.close()