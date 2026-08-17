from src.core.database import SessionLocal, engine, Base
from src.models.entities import User
from src.core.security import get_password_hash

def init_users():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if not db.query(User).filter(User.username == "admin").first():
        admin_user = User(
            username="admin",
            hashed_password=get_password_hash("admin123"),
            role="admin"
        )
        db.add(admin_user)

    if not db.query(User).filter(User.username == "jaakko").first():
        guest_user = User(
            username="jaakko",
            hashed_password=get_password_hash("jaakko126"),
            role="user"
        )
        db.add(guest_user)

    db.commit()
    print("✅ Käyttäjät 'admin' ja 'vieras' luotu onnistuneesti tietokantaan!")
    db.close()

if __name__ == "__main__":
    init_users()