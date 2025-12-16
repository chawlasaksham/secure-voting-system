from collections import defaultdict
from datetime import datetime
from functools import wraps

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import inspect, text
from sqlalchemy.orm import joinedload

from config import Config
from extensions import db, login_manager


load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    login_manager.init_app(app)
    cipher = Fernet(app.config["ENCRYPTION_KEY"])

    from models.user_model import User
    from models.vote_model import Campaign, Candidate, Vote

    DEFAULT_CAMPAIGN_NAME = "General Election"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    def setup():
        db.create_all()
        default_campaign = ensure_campaign_infrastructure()
        ensure_vote_cipher_column()
        ensure_user_security_key_column()
        if Candidate.query.count() == 0:
            seed_candidates(default_campaign)
        enforce_primary_admin()

    def seed_candidates(campaign: Campaign):
        db.session.add_all(
            [
                Candidate(
                    name="Alice Johnson",
                    manifesto="Transparency and trust.",
                    campaign=campaign,
                ),
                Candidate(
                    name="Brian Smith",
                    manifesto="Innovation in voting.",
                    campaign=campaign,
                ),
                Candidate(
                    name="Carla Ruiz",
                    manifesto="Community-first approach.",
                    campaign=campaign,
                ),
            ]
        )
        db.session.commit()

    def enforce_primary_admin():
        primary_email = "1@gmail.com"
        primary_user = User.query.filter_by(email=primary_email).first()
        if not primary_user:
            return

        changes = False
        non_primary_admins = User.query.filter(
            User.email != primary_email, User.is_admin.is_(True)
        ).all()
        for user in non_primary_admins:
            user.is_admin = False
            changes = True
        if primary_user and not primary_user.is_admin:
            primary_user.is_admin = True
            changes = True
        if changes:
            db.session.commit()

    def ensure_campaign_infrastructure() -> Campaign:
        ensure_campaign_table()
        default_campaign = ensure_default_campaign()
        ensure_candidate_campaign_column(default_campaign.id)
        ensure_vote_campaign_column(default_campaign.id)
        return default_campaign

    def ensure_campaign_table():
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        if "campaigns" not in tables:
            Campaign.__table__.create(db.engine)

    def ensure_default_campaign() -> Campaign:
        campaign = Campaign.query.filter_by(name=DEFAULT_CAMPAIGN_NAME).first()
        if not campaign:
            campaign = Campaign(
                name=DEFAULT_CAMPAIGN_NAME,
                description="Default campaign created automatically.",
                is_active=True,
            )
            db.session.add(campaign)
            db.session.commit()
        return campaign

    def ensure_candidate_campaign_column(default_campaign_id: int) -> None:
        inspector = inspect(db.engine)
        columns = {col["name"] for col in inspector.get_columns("candidates")}
        if "campaign_id" not in columns:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE candidates ADD COLUMN campaign_id INTEGER REFERENCES campaigns(id)"
                    )
                )
        candidates_needing_update = (
            Candidate.query.filter(
                (Candidate.campaign_id.is_(None)) | (Candidate.campaign_id == 0)
            ).all()
        )
        for candidate in candidates_needing_update:
            candidate.campaign_id = default_campaign_id
        if candidates_needing_update:
            db.session.commit()

    def ensure_vote_campaign_column(default_campaign_id: int) -> None:
        inspector = inspect(db.engine)
        columns = {col["name"] for col in inspector.get_columns("votes")}
        if "campaign_id" not in columns:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE votes ADD COLUMN campaign_id INTEGER REFERENCES campaigns(id)"
                    )
                )
        votes_needing_update = (
            Vote.query.filter(
                (Vote.campaign_id.is_(None)) | (Vote.campaign_id == 0)
            ).all()
        )
        updated = False
        for vote in votes_needing_update:
            if vote.candidate and vote.candidate.campaign_id:
                vote.campaign_id = vote.candidate.campaign_id
            else:
                vote.campaign_id = default_campaign_id
            updated = True
        if updated:
            db.session.commit()
    def ensure_vote_cipher_column():
        inspector = inspect(db.engine)
        columns = {col["name"] for col in inspector.get_columns("votes")}
        if "encrypted_choice" not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE votes ADD COLUMN encrypted_choice TEXT"))

    def ensure_user_security_key_column():
        inspector = inspect(db.engine)
        columns = {col["name"] for col in inspector.get_columns("users")}
        if "security_key_hash" not in columns:
            with db.engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN security_key_hash VARCHAR(255)")
                )

    def encrypt_choice(candidate_name: str) -> str:
        return cipher.encrypt(candidate_name.encode()).decode()

    def decrypt_choice(token: str | None) -> str | None:
        if not token:
            return None
        try:
            return cipher.decrypt(token.encode()).decode()
        except Exception:
            return None

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            if current_user.is_admin:
                return redirect(url_for("admin_voters"))
            return redirect(url_for("user_dashboard"))
        return redirect(url_for("login"))

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            security_key = request.form.get("security_key", "").strip()

            errors = []
            if not username or not email or not password:
                errors.append("All fields are required.")
            if User.query.filter_by(email=email).first():
                errors.append("Email is already registered.")
            is_primary_admin = email == "1@gmail.com"
            if not is_primary_admin and not security_key:
                errors.append("Security key is required for voters.")

            if errors:
                for err in errors:
                    flash(err, "danger")
                return render_template("signup.html")

            user = User(username=username, email=email)
            user.is_admin = is_primary_admin
            user.set_password(password)
            if is_primary_admin:
                user.set_security_key(None)
            else:
                user.set_security_key(security_key)
            db.session.add(user)
            db.session.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
        return render_template("signup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            security_key = request.form.get("security_key", "").strip()
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                if not user.is_admin and not user.verify_security_key(security_key):
                    flash("Invalid security key.", "danger")
                else:
                    login_user(user)
                    flash("Welcome back!", "success")
                    next_page = request.args.get("next")
                    if next_page:
                        return redirect(next_page)
                    if user.is_admin:
                        return redirect(url_for("admin_voters"))
                    return redirect(url_for("user_dashboard"))
            flash("Invalid email or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("You have been logged out.", "info")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def user_dashboard():
        if current_user.is_admin:
            return redirect(url_for("admin_voters"))

        campaigns = (
            Campaign.query.options(joinedload(Campaign.candidates))
            .order_by(Campaign.is_active.desc(), Campaign.created_at.desc())
            .all()
        )
        votes_by_campaign = {
            vote.campaign_id: vote
            for vote in Vote.query.filter_by(user_id=current_user.id).all()
        }
        return render_template(
            "user_dashboard.html",
            campaigns=campaigns,
            votes_by_campaign=votes_by_campaign,
        )

    @app.route("/vote/<int:candidate_id>", methods=["POST"])
    @login_required
    def cast_vote(candidate_id):
        if current_user.is_admin:
            flash("Admins cannot vote.", "warning")
            return redirect(url_for("admin_voters"))

        security_key = request.form.get("security_key", "").strip()
        if not current_user.verify_security_key(security_key):
            flash("Security key mismatch.", "danger")
            return redirect(url_for("user_dashboard"))

        candidate = Candidate.query.options(joinedload(Candidate.campaign)).get_or_404(
            candidate_id
        )
        campaign = candidate.campaign
        if not campaign or not campaign.is_active:
            flash("This campaign is not accepting votes.", "warning")
            return redirect(url_for("user_dashboard"))

        existing_vote = Vote.query.filter_by(
            user_id=current_user.id, campaign_id=campaign.id
        ).first()
        if existing_vote:
            flash("You have already voted in this campaign.", "info")
            return redirect(url_for("user_dashboard"))

        vote = Vote(
            user_id=current_user.id,
            candidate_id=candidate.id,
            campaign_id=campaign.id,
            timestamp=datetime.utcnow(),
            encrypted_choice=encrypt_choice(candidate.name),
        )
        db.session.add(vote)
        db.session.commit()
        flash("Vote submitted successfully!", "success")
        return redirect(url_for("user_dashboard"))

    def admin_required(func):
        @wraps(func)
        @login_required
        def wrapper(*args, **kwargs):
            if not current_user.is_admin:
                flash("Admin access required.", "danger")
                return redirect(url_for("index"))
            return func(*args, **kwargs)
        return wrapper

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        from sqlalchemy import func

        total_users = User.query.count()
        total_votes = Vote.query.count()
        campaigns = (
            Campaign.query.order_by(Campaign.is_active.desc(), Campaign.created_at.desc())
            .all()
        )
        campaign_stats = []
        for campaign in campaigns:
            candidate_totals = (
                db.session.query(Candidate, func.count(Vote.id).label("votes"))
                .outerjoin(Vote, Vote.candidate_id == Candidate.id)
                .filter(Candidate.campaign_id == campaign.id)
                .group_by(Candidate.id)
                .all()
            )
            campaign_stats.append({"campaign": campaign, "stats": candidate_totals})
        return render_template(
            "admin_dashboard.html",
            campaign_stats=campaign_stats,
            total_users=total_users,
            total_votes=total_votes,
            voter_votes=[
                {
                    "user": vote.user,
                    "candidate": vote.candidate.name,
                    "campaign": vote.campaign.name if vote.campaign else "Unknown",
                    "encrypted": vote.encrypted_choice,
                    "decrypted": decrypt_choice(vote.encrypted_choice),
                    "timestamp": vote.timestamp,
                }
                for vote in Vote.query.order_by(Vote.timestamp.desc()).all()
            ],
        )

    @app.route("/admin/voters", methods=["GET", "POST"])
    @admin_required
    def admin_voters():
        if request.method == "POST":
            action = request.form.get("action")
            user_id = request.form.get("user_id")
            target = User.query.get_or_404(user_id)

            if target.id == current_user.id:
                flash("You cannot modify your own role.", "warning")
                return redirect(url_for("admin_voters"))

            if action == "toggle_admin":
                target.is_admin = not target.is_admin
                db.session.commit()
                flash("User role updated.", "success")
            elif action == "delete":
                db.session.delete(target)
                db.session.commit()
                flash("User deleted.", "info")
        users = User.query.order_by(User.username.asc()).all()
        votes_by_user = defaultdict(list)
        for vote in Vote.query.order_by(Vote.timestamp.desc()).all():
            votes_by_user[vote.user_id].append(
                {
                    "campaign": vote.campaign.name if vote.campaign else "Unknown",
                    "choice": decrypt_choice(vote.encrypted_choice),
                    "timestamp": vote.timestamp,
                }
            )
        return render_template(
            "admin_voters.html",
            users=users,
            votes_by_user=dict(votes_by_user),
        )

    @app.route("/admin/campaigns", methods=["GET", "POST"])
    @admin_required
    def admin_campaigns():
        if request.method == "POST":
            action = request.form.get("action")
            name = (request.form.get("name") or "").strip()
            description = (request.form.get("description") or "").strip()
            is_active = request.form.get("is_active") == "on"
            campaign_id_raw = request.form.get("campaign_id")
            try:
                campaign_id = int(campaign_id_raw) if campaign_id_raw else None
            except (TypeError, ValueError):
                campaign_id = None

            if action == "create":
                if not name:
                    flash("Campaign name is required.", "danger")
                elif Campaign.query.filter_by(name=name).first():
                    flash("Campaign name must be unique.", "danger")
                else:
                    db.session.add(
                        Campaign(
                            name=name,
                            description=description or None,
                            is_active=is_active,
                        )
                    )
                    db.session.commit()
                    flash("Campaign created.", "success")
                return redirect(url_for("admin_campaigns"))

            campaign = Campaign.query.get_or_404(campaign_id)

            if action == "update":
                if not name:
                    flash("Campaign name cannot be empty.", "danger")
                else:
                    campaign.name = name
                    campaign.description = description or None
                    campaign.is_active = is_active
                    db.session.commit()
                    flash("Campaign updated.", "success")
            elif action == "toggle_active":
                campaign.is_active = not campaign.is_active
                db.session.commit()
                state = "activated" if campaign.is_active else "paused"
                flash(f"Campaign {state}.", "info")
            elif action == "delete":
                if campaign.votes:
                    flash(
                        "Cannot delete a campaign that already has votes recorded.",
                        "danger",
                    )
                else:
                    db.session.delete(campaign)
                    db.session.commit()
                    flash("Campaign deleted.", "info")
            return redirect(url_for("admin_campaigns"))

        campaigns = Campaign.query.order_by(
            Campaign.is_active.desc(), Campaign.created_at.desc()
        ).all()
        return render_template("admin_campaigns.html", campaigns=campaigns)

    @app.route("/admin/candidates", methods=["GET", "POST"])
    @admin_required
    def admin_candidates():
        campaigns = Campaign.query.order_by(
            Campaign.created_at.desc()
        ).all()
        if not campaigns:
            flash("Create a campaign before adding candidates.", "warning")
            return redirect(url_for("admin_campaigns"))

        selected_campaign_id = request.args.get("campaign_id", type=int)
        if campaigns:
            campaign_ids = {campaign.id for campaign in campaigns}
            if selected_campaign_id is None or selected_campaign_id not in campaign_ids:
                selected_campaign_id = campaigns[0].id

        if request.method == "POST":
            action = request.form.get("action")
            name = request.form.get("name", "").strip()
            manifesto = request.form.get("manifesto", "").strip()
            candidate_id = request.form.get("candidate_id")
            campaign_id_raw = request.form.get("campaign_id")
            try:
                campaign_id = (
                    int(campaign_id_raw)
                    if campaign_id_raw
                    else selected_campaign_id
                )
            except (TypeError, ValueError):
                campaign_id = selected_campaign_id

            if action == "create":
                if not name:
                    flash("Candidate name is required.", "danger")
                elif not campaign_id:
                    flash("Select a campaign for this candidate.", "danger")
                else:
                    db.session.add(
                        Candidate(
                            name=name,
                            manifesto=manifesto or None,
                            campaign_id=campaign_id,
                        )
                    )
                    db.session.commit()
                    flash("Candidate added.", "success")
                return redirect(
                    url_for("admin_candidates", campaign_id=campaign_id)
                )

            candidate = Candidate.query.get_or_404(candidate_id)

            if action == "update":
                if not name:
                    flash("Name cannot be empty.", "danger")
                else:
                    candidate.name = name
                    candidate.manifesto = manifesto or None
                    if campaign_id:
                        candidate.campaign_id = campaign_id
                    db.session.commit()
                    flash("Candidate updated.", "success")
            elif action == "delete":
                db.session.delete(candidate)
                db.session.commit()
                flash("Candidate removed.", "info")
            return redirect(url_for("admin_candidates", campaign_id=campaign_id))

        candidates_query = Candidate.query.options(joinedload(Candidate.campaign))
        if selected_campaign_id:
            candidates_query = candidates_query.filter(
                Candidate.campaign_id == selected_campaign_id
            )
        candidates = candidates_query.order_by(Candidate.name.asc()).all()
        return render_template(
            "admin_candidates.html",
            candidates=candidates,
            campaigns=campaigns,
            selected_campaign_id=selected_campaign_id,
        )

    with app.app_context():
        setup()

    return app


app = create_app()

if __name__ == "__main__":
    app.run()

