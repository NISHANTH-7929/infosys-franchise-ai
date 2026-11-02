from database import SessionLocal, engine, Base, settings
from models import User
from security import hash_password


def seed_admin():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == settings.ADMIN_EMAIL.lower()).first()
        if existing:
            print(f"[seed] Admin already exists: {existing.email}")
            return
        admin = User(
            email=settings.ADMIN_EMAIL.lower(),
            username=settings.ADMIN_USERNAME,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            role="admin",
            outlet=settings.ADMIN_OUTLET,
            locked=False,
            failed_attempts=0,
            security_question="What is your favourite color?",
            security_answer_hash=hash_password("blue"),
        )
        db.add(admin)
        db.commit()
        print(f"[seed] ✅ Admin created: {admin.email}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_admin()
