from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    security_key_hash = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    votes = db.relationship("Vote", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def set_security_key(self, security_key: str | None) -> None:
        if security_key:
            self.security_key_hash = generate_password_hash(security_key.strip())
        else:
            self.security_key_hash = None

    def verify_security_key(self, security_key: str | None) -> bool:
        if not security_key or not self.security_key_hash:
            return False
        return check_password_hash(self.security_key_hash, security_key.strip())

