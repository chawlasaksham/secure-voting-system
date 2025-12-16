from extensions import db


class Campaign(db.Model):
    __tablename__ = "campaigns"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    start_at = db.Column(db.DateTime, nullable=True)
    end_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    candidates = db.relationship(
        "Candidate", back_populates="campaign", cascade="all, delete-orphan"
    )
    votes = db.relationship("Vote", back_populates="campaign", cascade="all, delete")


class Candidate(db.Model):
    __tablename__ = "candidates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    manifesto = db.Column(db.Text, nullable=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)

    votes = db.relationship("Vote", back_populates="candidate", cascade="all, delete")
    campaign = db.relationship("Campaign", back_populates="candidates")


class Vote(db.Model):
    __tablename__ = "votes"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidates.id"), nullable=False)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    encrypted_choice = db.Column(db.Text, nullable=True)

    user = db.relationship("User", back_populates="votes")
    candidate = db.relationship("Candidate", back_populates="votes")
    campaign = db.relationship("Campaign", back_populates="votes")

