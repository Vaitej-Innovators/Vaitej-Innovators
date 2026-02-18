from flask import (
    Flask, render_template, redirect,
    url_for, request, session, flash, jsonify,send_file,Response
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os, json
from flask import request, redirect, url_for, flash, jsonify
from sqlalchemy import text
from flask_socketio import SocketIO, emit, join_room

# Assuming these exist in your project validators.py and config.py
from validators import (
    validate_common,
    validate_founder,
    validate_investor
)
from config import Config

from datetime import date, timedelta, datetime
import os, time, json,csv, io

from google.genai import types
import json
import boto3
from google.genai import Client
# Then update your get_ai_client function:
def get_ai_client():
    return Client(api_key=app.config.get("GEMINI_API_KEY"))
# -------------------------------------------------
# APP SETUP
# -------------------------------------------------
app = Flask(__name__)
app.config.from_object(Config)

# Session + flash security
app.secret_key = app.config.get("SECRET_KEY", "dev-secret-key")
app.jinja_env.filters["loads"] = json.loads
app.jinja_env.filters["fromjson"] = json.loads  # <--- ADD THIS LINE
# -------------------------------------------------
# FILE UPLOAD CONFIG
# -------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)

# Helper to get AI Client
def get_ai_client():
    return genai.Client(api_key=app.config.get("GEMINI_API_KEY"))
from datetime import datetime

def calculate_moic(invested, current_value):
    if not invested or invested == 0:
        return None
    return round(current_value / invested, 2)

def calculate_irr_proxy(invested, current_value, invested_at):
    if not invested or not current_value or not invested_at:
        return None

    years = max((datetime.utcnow() - invested_at).days / 365, 0.1)
    irr = ((current_value / invested) ** (1 / years)) - 1
    return round(irr * 100, 1)
def calculate_investor_profile_completion(inv):
    score = 0

    if inv.get("title"):
        score += 10

    if inv.get("fund_name") and inv.get("fund_size"):
        score += 20

    if inv.get("typical_check_min") and inv.get("typical_check_max"):
        score += 15

    if inv.get("investment_stage") and inv.get("sector_focus") and inv.get("geography_focus"):
        score += 20

    if inv.get("investment_thesis") and inv.get("notable_investments"):
        score += 25

    if inv.get("activity_status"):
        score += 10

    return min(score, 100)

def calculate_founder_profile_completion_db(f):
    score = 0

    if f.company_name:
        score += 10
    if f.tagline:
        score += 10
    if f.stage:
        score += 10
    if f.sector:
        score += 10
    if f.business_model:
        score += 10
    if f.product_stage:
        score += 10
    if f.team_size and f.team_size > 0:
        score += 10
    if f.raise_target and f.raise_target > 0:
        score += 10
    if f.min_check_size and f.min_check_size > 0:
        score += 10
    if f.website_url or f.linkedin_url:
        score += 10

    return min(score, 100)

def investor_ranking_boost(inv):
    boost = 0

    if inv.get("verification_status") == "verified":
        boost += 15

    if inv.get("profile_completion", 0) >= 80:
        boost += 10

    if inv.get("activity_status") == "active":
        boost += 5

    return boost

# -------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------
def safe_float(val):
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

def safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0

def safe_json_load(data):
    if not data: return []
    if isinstance(data, (list, dict)): return data
    try: return json.loads(data)
    except: return []

def calculate_match_score(founder, investor, pitch_score):
    score = 0
    reasons = []

    # 1. Stage fit (30)
    if founder.stage and founder.stage in investor.investment_stage:
        score += 30
        reasons.append("Stage alignment")

    # 2. Sector fit (25)
    if founder.sector and investor.sector_focus:
        if founder.sector.lower() in investor.sector_focus.lower():
            score += 25
            reasons.append("Sector alignment")

    # 3. Check size fit (15)
    if (investor.typical_check_min and investor.typical_check_max and founder.min_check_size):
        if investor.typical_check_min <= founder.min_check_size <= investor.typical_check_max:
            score += 15
            reasons.append("Check size compatibility")

    # 4. Geography fit (10)
    if founder.location and investor.geography_focus: 
        if founder.location.lower() in investor.geography_focus.lower():
            score += 10
            reasons.append("Geographic focus")

    # 5. Trust & activity (10)
    if investor.verification_status == "verified":
        score += 6
        reasons.append("Verified investor")

    if investor.activity_status == "active":
        score += 4

    # 6. Founder readiness boost (10)
    if pitch_score >= 80:
        score += 10
        reasons.append("Strong pitch readiness")
    elif pitch_score >= 60:
        score += 5

    return score, ", ".join(reasons)
class Match(db.Model):
    __tablename__ = 'matches'
    id = db.Column(db.Integer, primary_key=True)
    
    # Note: These link to profiles, not the User table directly
    founder_id = db.Column(db.Integer, db.ForeignKey('founder_profiles.id'), nullable=False)
    investor_id = db.Column(db.Integer, db.ForeignKey('investor_profiles.id'), nullable=False)
    
    match_score = db.Column(db.Integer, default=0)
    
    # Your schema uses: 'new', 'interested', 'saved', 'declined', 'due_diligence', 'invested', 'connected'
    status = db.Column(db.String(50), default='new') 
    
    ai_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships to access names/logos easily
    founder = db.relationship('FounderProfile', backref='matches')
    investor = db.relationship('InvestorProfile', backref='matches')
# -------------------------------------------------
# ENTRY & AUTH ROUTES
# -------------------------------------------------
@app.route("/")
def entry():
    return render_template("entry.html")

@app.route("/continue/<role>")
def continue_as(role):
    if role not in ["founder", "investor"]:
        return redirect(url_for("entry"))
    session.clear()
    session["selected_role"] = role
    return redirect(url_for("register", role=role))

@app.route("/login", methods=["GET", "POST"])
def login():
    role = session.get("selected_role")

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            return render_template("login.html", error="Email and password are required.", role=role)

        user = db.session.execute(
            text("SELECT id, role, password_hash FROM users WHERE email = :email"),
            {"email": email}
        ).fetchone()

        if not user or not check_password_hash(user.password_hash, password):
            return render_template("login.html", error="Invalid email or password.", role=role)

        session.clear()
        session["user_id"] = user.id
        session["role"] = user.role

        if user.role == "founder":
            return redirect(url_for("founder_home"))
        if user.role == "investor":
            return redirect(url_for("investor_home"))

    return render_template("login.html", role=role)

@app.route("/register/<role>", methods=["GET", "POST"])
def register(role):
    if role not in ["founder", "investor"]:
        return redirect(url_for("entry"))

    if request.method == "POST":
        form = request.form

        # Basic Validation
        if not validate_common(form):
            return render_template(f"register_{role}.html", error="Please fill all required fields.")
        
        if role == "founder" and not validate_founder(form):
            return render_template("register_founder.html", error="Please complete all founder fields.")
        
        if role == "investor" and not validate_investor(form):
            return render_template("register_investor.html", error="Please complete all investor fields.")

        try:
            # Check existing user
            existing = db.session.execute(text("SELECT id FROM users WHERE email = :email"), {"email": form["email"]}).fetchone()
            if existing:
                return render_template(f"register_{role}.html", error="An account with this email already exists.")

            # Create User
            result = db.session.execute(
                text("""
                    INSERT INTO users (role, full_name, email, password_hash, phone, country, referral_source)
                    VALUES (:role, :full_name, :email, :password, :phone, :country, :referral)
                """),
                {
                    "role": role, "full_name": form["full_name"], "email": form["email"],
                    "password": generate_password_hash(form["password"]), "phone": form["phone"],
                    "country": form["country"], "referral": form.get("referral")
                }
            )
            user_id = result.lastrowid

            # Create Profile
            if role == "founder":
                actively_raising = True if form.get("actively_raising") == "yes" else False
                fundraising_status = "raising" if actively_raising else "preparing"
                db.session.execute(
                    text("""
                        INSERT INTO founder_profiles 
                        (user_id, company_name, founding_year, stage, sector, business_model, actively_raising, fundraising_status, raise_target, raise_raised, min_check_size)
                        VALUES (:user_id, :company_name, :founding_year, :stage, :sector, :business_model, :actively_raising, :fundraising_status, 0, 0, NULL)
                    """),
                    {
                        "user_id": user_id, "company_name": form["company_name"], "founding_year": form["founding_year"],
                        "stage": form["stage"], "sector": form["sector"], "business_model": form["business_model"],
                        "actively_raising": actively_raising, "fundraising_status": fundraising_status
                    }
                )

            if role == "investor":
                db.session.execute(
                    text("""
                        INSERT INTO investor_profiles 
                        (user_id, fund_name, investment_stage, sector_focus, geography_focus, typical_check_min, accredited)
                        VALUES (:user_id, :fund_name, :investment_stage, :sector_focus, :geography_focus, :check_size, :accredited)
                    """),
                    {
                        "user_id": user_id, "fund_name": form["fund_name"], "investment_stage": form["investment_stage"],
                        "sector_focus": form["sector_focus"], "geography_focus": form["geography_focus"],
                        "check_size": form["check_size"], "accredited": form["accredited"]
                    }
                )

            db.session.commit()
            return render_template(f"register_{role}.html", success=True)

        except Exception as e:
            db.session.rollback()
            return render_template(f"register_{role}.html", error=f"Database Error: {str(e)}")

    return render_template(f"register_{role}.html")

# -------------------------------------------------
# 1. FOUNDER HOME
# -------------------------------------------------
# -------------------------------------------------
# 🟢 FOUNDER HOME (UPDATED WITH REQUESTS)
# -------------------------------------------------
@app.route("/founder/home")
def founder_home():
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")

    # 1. Fetch Profile
    founder = db.session.execute(text("""
        SELECT f.id as profile_id, f.*, u.full_name, u.email, u.phone, u.country
        FROM users u
        JOIN founder_profiles f ON u.id = f.user_id
        WHERE u.id = :uid
    """), {"uid": user_id}).fetchone()
    
    if not founder: return redirect(url_for("login"))
    fid = founder.profile_id

    # 2. Fetch Incoming Requests (Investors who clicked "Connect")
    requests = db.session.execute(text("""
        SELECT m.id as match_id, m.match_score, m.ai_reason, 
               i.fund_name, i.title, i.user_id as inv_user_id,
               u.full_name, u.profile_photo, u.country
        FROM matches m
        JOIN investor_profiles i ON m.investor_id = i.id
        JOIN users u ON i.user_id = u.id
        WHERE m.founder_id = :fid AND m.status = 'interested'
    """), {"fid": fid}).mappings().all()

    # 3. Fetch Traction Data (For the snapshot table)
    traction = db.session.execute(text("""
        SELECT * FROM traction_metrics WHERE founder_id = :fid ORDER BY id DESC LIMIT 5
    """), {"fid": fid}).mappings().all()

    # --- Existing Logic (Scores, Completion, Activity) ---
    fields_to_check = [
        founder.full_name, founder.phone, founder.country,
        founder.logo_url, founder.company_name, founder.website_url,
        founder.stage, founder.sector, founder.business_model,
        founder.raise_target, founder.linkedin_url
    ]
    filled_count = sum(1 for f in fields_to_check if f and str(f).strip())
    completion_percent = int((filled_count / len(fields_to_check)) * 100)

    missing_fields = []
    if not founder.logo_url: missing_fields.append("Company Logo")
    if not founder.website_url: missing_fields.append("Website URL")
    
    has_deck = db.session.execute(text("SELECT id FROM pitch_decks WHERE founder_id = :fid LIMIT 1"), {"fid": fid}).scalar()
    if not has_deck: missing_fields.append("Pitch Deck")

    pitch_score = 0
    if founder.company_name: pitch_score += 10
    if founder.stage: pitch_score += 10
    if founder.sector: pitch_score += 10
    if founder.actively_raising: pitch_score += 10
    if founder.founding_year: pitch_score += 5
    if completion_percent >= 90: pitch_score += 15
    if has_deck: pitch_score += 30

    pitch_label = "Investor-Ready" if pitch_score >= 80 else "Good" if pitch_score >= 50 else "Needs Work"

    weeks_elapsed = 0
    if founder.fundraising_start_date:
        weeks_elapsed = (date.today() - founder.fundraising_start_date).days // 7

    recent_views_count = db.session.execute(text("SELECT COUNT(*) FROM investor_profile_views WHERE founder_id=:fid AND viewed_at >= NOW() - INTERVAL 7 DAY"), {"fid": fid}).scalar() or 0
    expressed_interest_count = len(requests) # Updated to use the requests list length
    total_matches = db.session.execute(text("SELECT COUNT(*) FROM matches WHERE founder_id=:fid"), {"fid": fid}).scalar() or 0
    active_chats_count = db.session.execute(text("SELECT COUNT(*) FROM matches WHERE founder_id=:fid AND status='connected'"), {"fid": fid}).scalar() or 0

    # Activity Feed
    views = db.session.execute(text("SELECT 'view' as type, v.viewed_at as created_at, ip.fund_name as detail FROM investor_profile_views v JOIN investor_profiles ip ON v.investor_id = ip.id WHERE v.founder_id = :fid ORDER BY v.viewed_at DESC LIMIT 3"), {"fid": fid}).fetchall()
    matches_feed = db.session.execute(text("SELECT 'match' as type, m.created_at, CONCAT(ip.fund_name, ' (', m.match_score, '% Match)') as detail FROM matches m JOIN investor_profiles ip ON m.investor_id = ip.id WHERE m.founder_id = :fid AND m.match_score > 70 ORDER BY m.created_at DESC LIMIT 3"), {"fid": fid}).fetchall()
    msgs = db.session.execute(text("SELECT 'message' as type, m.created_at, u.full_name as detail FROM messages m JOIN conversations c ON m.conversation_id = c.id JOIN users u ON m.sender_id = u.id WHERE c.founder_id = :fid AND m.sender_id != :uid ORDER BY m.created_at DESC LIMIT 3"), {"fid": fid, "uid": user_id}).fetchall()
    activity_feed = sorted(views + matches_feed + msgs, key=lambda x: x.created_at, reverse=True)[:6]

    ai_alert = None
    if requests:
        ai_alert = f"🔥 You have {len(requests)} new connection request(s)! Review them immediately."
    elif pitch_score < 50:
        ai_alert = "Your Pitch Score is low. Upload a deck and fill missing fields to rank higher."
    elif recent_views_count > 5 and not has_deck:
        ai_alert = "📈 Traffic spike! Investors are looking. Upload your deck now."
    else:
        ai_alert = "Profile is active. Keep your traction metrics updated."

    return render_template(
        "dashboard/founder_home.html",
        founder=founder,
        requests=requests,      # Passed to template
        traction=traction,      # Passed to template
        completion_percent=completion_percent,
        missing_fields=missing_fields,
        pitch_score=pitch_score,
        pitch_label=pitch_label,
        raise_target=founder.raise_target or 1,
        raise_raised=founder.raise_raised or 0,
        raise_percent=int(((founder.raise_raised or 0) / (founder.raise_target or 1) * 100)),
        weeks_elapsed=weeks_elapsed,
        recent_views=recent_views_count,
        expressed_interest=expressed_interest_count,
        active_chats=active_chats_count,
        ai_alert=ai_alert,
        activity_feed=activity_feed,
        has_deck=has_deck,
        total_matches=total_matches
    )
# -------------------------------------------------
# 🟢 FOUNDER RESPOND TO REQUEST
# -------------------------------------------------
@app.route("/founder/request/<int:match_id>/<action>")
def founder_respond_match(match_id, action):
    if session.get("role") != "founder": 
        return redirect(url_for("login"))
    
    # 1. Verify Match Ownership
    match = db.session.execute(text("""
        SELECT m.*, f.user_id 
        FROM matches m 
        JOIN founder_profiles f ON m.founder_id = f.id
        WHERE m.id = :mid
    """), {"mid": match_id}).mappings().first()

    # Security check: Ensure the current logged-in user owns this founder profile
    if not match or match.user_id != session.get("user_id"):
        flash("Unauthorized request.", "error")
        return redirect(url_for("founder_home"))

    if action == 'accept':
        # 2. Update Match Status
        db.session.execute(text("UPDATE matches SET status = 'connected' WHERE id = :mid"), {"mid": match_id})
        
        # 3. Safe Conversation Creation (Check existence first)
        existing_convo = db.session.execute(text("""
            SELECT id FROM conversations 
            WHERE founder_id = :fid AND investor_id = :iid
        """), {"fid": match.founder_id, "iid": match.investor_id}).fetchone()

        if not existing_convo:
            # Create new conversation
            db.session.execute(text("""
                INSERT INTO conversations (founder_id, investor_id, created_at)
                VALUES (:fid, :iid, NOW())
            """), {"fid": match.founder_id, "iid": match.investor_id})
        
        db.session.commit()
        
        flash("Connection accepted! You can now chat.", "success")
        return redirect(url_for("founder_messages"))

    elif action == 'decline':
        # 4. Handle Decline
        db.session.execute(text("UPDATE matches SET status = 'declined' WHERE id = :mid"), {"mid": match_id})
        
        # Remove conversation if it existed previously
        db.session.execute(text("DELETE FROM conversations WHERE founder_id=:fid AND investor_id=:iid"), 
                           {"fid": match.founder_id, "iid": match.investor_id})
        
        db.session.commit()
        flash("Request declined.", "info")

    return redirect(url_for("founder_home"))


# -------------------------------------------------
# 2. FOUNDER MATCHES
# -------------------------------------------------
@app.route("/founder/matches")
def founder_matches():
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")

    # Use nested SELECT to get founder_id correctly
    matches = db.session.execute(text("""
        SELECT m.id AS match_id, m.match_score, m.status, m.ai_reason,
               u.full_name AS investor_name, ip.fund_name, ip.investment_stage,
               ip.sector_focus, ip.geography_focus, ip.typical_check_min
        FROM matches m
        JOIN investor_profiles ip ON m.investor_id = ip.id
        JOIN users u ON ip.user_id = u.id
        WHERE m.founder_id = (SELECT id FROM founder_profiles WHERE user_id = :uid)
          AND m.status != 'declined'
        ORDER BY CASE WHEN m.status = 'saved' THEN 1 ELSE 0 END DESC, m.match_score DESC
        LIMIT 50
    """), {"uid": user_id}).fetchall()

    return render_template("dashboard/founder_matches.html", matches=matches)

@app.route("/founder/matches/generate")
def generate_matches():
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")

    founder = db.session.execute(text("SELECT * FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).mappings().first()
    if not founder: return redirect(url_for("founder_home"))
    
    investors = db.session.execute(text("SELECT * FROM investor_profiles WHERE activity_status='active'")).mappings().all()
    pitch_score = 70 

    for inv in investors:
        score, reason = calculate_match_score(founder, inv, pitch_score)
        if score >= 40:
            db.session.execute(text("""
                INSERT INTO matches (founder_id, investor_id, match_score, status, ai_reason)
                VALUES (:fid, :iid, :sc, 'new', :rs)
                ON DUPLICATE KEY UPDATE match_score=:sc, ai_reason=:rs
            """), {"fid": founder["id"], "iid": inv["id"], "sc": score, "rs": reason})
    
    db.session.commit()
    return redirect(url_for("founder_matches"))

@app.route("/founder/matches/update/<int:match_id>/<action>")
def update_match_status(match_id, action):
    if session.get("role") != "founder": return redirect(url_for("login"))
    
    match = db.session.execute(text("SELECT * FROM matches WHERE id=:mid"), {"mid": match_id}).mappings().first()
    if not match: return redirect(url_for("founder_matches"))

    db.session.execute(text("UPDATE matches SET status = :st, updated_at = NOW() WHERE id = :mid"), {"st": action, "mid": match_id})
    
    if action == "interested":
        exists = db.session.execute(text("""
            SELECT id FROM conversations WHERE founder_id=:fid AND investor_id=:iid
        """), {"fid": match.founder_id, "iid": match.investor_id}).fetchone()

        if not exists:
            db.session.execute(text("""
                INSERT INTO conversations (founder_id, investor_id, created_at)
                VALUES (:fid, :iid, NOW())
            """), {"fid": match.founder_id, "iid": match.investor_id})

    db.session.commit()
    return redirect(url_for("founder_matches"))

# -------------------------------------------------
# 3. PITCH HUB & PUBLISHING
# -------------------------------------------------
# -------------------------------------------------
# 3. PITCH HUB & PUBLISHING
# -------------------------------------------------
@app.route("/founder/pitch")
def founder_pitch():
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")

    founder = db.session.execute(text("SELECT id FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    
    # 1. Get Latest Deck
    deck = db.session.execute(text("""
        SELECT * FROM pitch_decks WHERE founder_id = :fid ORDER BY created_at DESC LIMIT 1
    """), {"fid": founder.id}).fetchone()

    analysis = None
    report = None
    official_qa = None
    last_simulation = None

    if deck:
        if deck.analysis_json:
            analysis = safe_json_load(deck.analysis_json)
            
        # 2. Get Report (if exists)
        report = db.session.execute(text("SELECT id FROM investment_reports WHERE deck_id=:did ORDER BY id DESC LIMIT 1"), {"did": deck.id}).fetchone()
        
        # 3. Get Latest OFFICIAL Q&A (Required for Publishing)
        official_qa = db.session.execute(text("""
            SELECT * FROM qa_sessions 
            WHERE deck_id=:did AND session_type='official' 
            ORDER BY id DESC LIMIT 1
        """), {"did": deck.id}).fetchone()

        # 4. Get Latest TRAINING Q&A (For Practice Stats)
        last_simulation = db.session.execute(text("""
            SELECT * FROM qa_sessions 
            WHERE deck_id=:did AND session_type='training' 
            ORDER BY id DESC LIMIT 1
        """), {"did": deck.id}).fetchone()

    return render_template("dashboard/founder_pitch.html", 
                           deck=deck, 
                           analysis=analysis, 
                           report=report, 
                           official_qa=official_qa,       # Passed as 'official_qa'
                           last_simulation=last_simulation) # Passed as 'last_simulation'

@app.route("/founder/pitch/upload", methods=["POST"])
def upload_pitch():
    if session.get("role") != "founder": return redirect(url_for("login"))
    
    file = request.files.get("pitch_deck")
    if not file or not file.filename.lower().endswith(".pdf"):
        flash("Only PDF files are allowed.")
        return redirect(url_for("founder_pitch"))

    user_id = session.get("user_id")
    founder = db.session.execute(text("SELECT id FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()

    # 1. Save File
    original_filename = secure_filename(file.filename)
    filename = f"pitch_{user_id}_{int(time.time())}_{original_filename}"
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(file_path)
    
    try:
        # 2. AI Analysis
        client = get_ai_client()
        uploaded_file = client.files.upload(file=file_path)

        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = client.files.get(name=uploaded_file.name)

        if uploaded_file.state.name == "FAILED":
            raise Exception("AI failed to process the PDF.")

        prompt = """
        You are a Venture Capital Analyst. Analyze this pitch deck PDF.
        Output strict JSON:
        {
            "score": <0-100 integer>,
            "summary": "<2 sentence summary>",
            "strengths": ["<str1>", "<str2>", "<str3>"],
            "weaknesses": ["<weak1>", "<weak2>", "<weak3>"],
            "verdict": "<Invest/Maybe/Pass>"
        }
        """
        
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=[uploaded_file, prompt]
        )
        
        raw_text = response.text.replace("```json", "").replace("```", "").strip()
        analysis_data = json.loads(raw_text)
        
    except Exception as e:
        print(f"AI Error: {e}")
        analysis_data = {"score": 0, "summary": "Analysis failed.", "strengths": [], "weaknesses": [], "verdict": "Error"}

    # 3. Save Deck to DB
    file_url = f"/static/uploads/{filename}"
    
    result = db.session.execute(text("""
        INSERT INTO pitch_decks (founder_id, file_url, deck_score, analysis_json, feedback_summary, is_published) 
        VALUES (:fid, :url, :score, :json, :summ, 0)
    """), {
        "fid": founder.id, "url": file_url, 
        "score": analysis_data.get("score", 0),
        "json": json.dumps(analysis_data),
        "summ": analysis_data.get("summary")
    })
    
    deck_id = result.lastrowid

    # 4. AUTO-START Q&A SESSION (New Logic)
    qa_result = db.session.execute(text("""
        INSERT INTO qa_sessions (founder_id, deck_id, transcript_json, status, session_score)
        VALUES (:fid, :did, '[]', 'in_progress', 0)
    """), {"fid": founder.id, "did": deck_id})
    
    db.session.commit()

    flash("Deck analyzed! Now, please answer a few investor questions to complete your report.", "info")
    return redirect(url_for("founder_qa_interface", session_id=qa_result.lastrowid))


@app.route("/founder/pitch/review/<int:deck_id>")
def review_pitch_report(deck_id):
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")
    
    founder = db.session.execute(text("SELECT id FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    
    # Fetch Deck
    deck = db.session.execute(text("SELECT * FROM pitch_decks WHERE id=:did AND founder_id=:fid"), {"did": deck_id, "fid": founder.id}).fetchone()
    
    # Fetch OFFICIAL Q&A Session (Updated Logic)
    qa_session = db.session.execute(text("""
        SELECT * FROM qa_sessions 
        WHERE deck_id=:did AND session_type='official' 
        ORDER BY id DESC LIMIT 1
    """), {"did": deck_id}).fetchone()
    
    if not deck: return redirect(url_for("founder_pitch"))

    # Validation: Ensure Official Q&A is done
    if not qa_session or qa_session.status != 'completed':
        flash("You must complete the Official Q&A session before generating the report.", "warning")
        return redirect(url_for("founder_pitch"))

    # Generate Combined Report (Deck Analysis + Q&A Performance)
    try:
        qa_transcript = qa_session.transcript_json if qa_session else "[]"
        deck_analysis = deck.analysis_json
        
        client = get_ai_client()
        prompt = f"""
        Generate a final 'Investment Memo' for investors based on this startup's data.
        
        1. Pitch Deck Analysis: {deck_analysis}
        2. Founder Q&A Transcript: {qa_transcript}
        
        Output valid HTML (no markdown, no ```html tags) with these exact sections:
        <div class="report-section">
            <h3>Executive Summary</h3>
            <p>...</p>
        </div>
        <div class="report-section">
            <h3>Key Strengths (Validated)</h3>
            <ul>...</ul>
        </div>
        <div class="report-section">
            <h3>Founder Defense & Q&A Highlights</h3>
            <p>Summarize how the founder handled hard questions.</p>
        </div>
        <div class="report-section">
            <h3>Risk Assessment</h3>
            <p>...</p>
        </div>
        """
        
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        report_preview = response.text.replace("```html", "").replace("```", "").strip()
        
    except Exception as e:
        report_preview = f"<p>Error generating report: {str(e)}</p>"

    return render_template("dashboard/founder_report_review.html", 
                           deck=deck, 
                           report_html=report_preview, 
                           qa_session=qa_session)


@app.route("/founder/pitch/publish/<int:deck_id>", methods=["POST"])
def publish_deck(deck_id):
    if session.get("role") != "founder": return redirect(url_for("login"))
    
    user_id = session.get("user_id")
    founder = db.session.execute(text("SELECT id FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    
    # Get the approved report HTML from the form
    final_report_html = request.form.get("report_content")
    
    # 1. Save Report to Investment Reports Table
    db.session.execute(text("""
        INSERT INTO investment_reports (founder_id, deck_id, report_content, created_at)
        VALUES (:fid, :did, :content, NOW())
    """), {"fid": founder.id, "did": deck_id, "content": final_report_html})
    
    # 2. Mark Deck as Published
    db.session.execute(text("""
        UPDATE pitch_decks SET is_published = 1 WHERE id = :did AND founder_id = :fid
    """), {"did": deck_id, "fid": founder.id})
    
    db.session.commit()
    
    flash("Success! Your Pitch Deck and Investment Report are now live for investors.", "success")
    return redirect(url_for("founder_pitch"))

# @app.route("/founder/pitch/publish/<int:deck_id>")
# def publish_deck(deck_id):
#     if session.get("role") != "founder": return redirect(url_for("login"))
#     user_id = session.get("user_id")
    
#     founder = db.session.execute(text("SELECT id FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
#     deck = db.session.execute(text("SELECT id, deck_score FROM pitch_decks WHERE id=:did AND founder_id=:fid"), {"did": deck_id, "fid": founder.id}).fetchone()
    
#     if not deck or deck.deck_score < 70:
#         flash("Score too low to publish.")
#         return redirect(url_for("founder_pitch"))

#     db.session.execute(text("UPDATE pitch_decks SET is_published=1 WHERE id=:did"), {"did": deck_id})
#     db.session.commit()
#     flash("Deck published to high-match investors!")
#     return redirect(url_for("founder_pitch"))

# -------------------------------------------------
# 2. UPDATED START SESSION (Accepts Mode)
# -------------------------------------------------
@app.route("/founder/qa/start/<mode>")
def start_qa_session(mode):
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")
    
    # Validate Mode
    if mode not in ['training', 'official']:
        mode = 'training'

    founder = db.session.execute(text("SELECT id FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    deck = db.session.execute(text("SELECT id FROM pitch_decks WHERE founder_id=:fid ORDER BY created_at DESC LIMIT 1"), {"fid": founder.id}).fetchone()
    
    if not deck:
        flash("Upload a pitch deck first.")
        return redirect(url_for("founder_pitch"))

    # Create Session with Type
    result = db.session.execute(text("""
        INSERT INTO qa_sessions (founder_id, deck_id, transcript_json, status, session_score, session_type)
        VALUES (:fid, :did, '[]', 'in_progress', 0, :stype)
    """), {"fid": founder.id, "did": deck.id, "stype": mode})
    db.session.commit()
    
    # Redirect to the Chat Interface
    return redirect(url_for("founder_qa_interface", session_id=result.lastrowid))

    
@app.route("/founder/qa/<int:session_id>")
def founder_qa_interface(session_id):
    if session.get("role") != "founder": return redirect(url_for("login"))
    
    row = db.session.execute(text("SELECT * FROM qa_sessions WHERE id=:sid"), {"sid": session_id}).fetchone()
    if not row: return redirect(url_for("founder_pitch"))
        
    transcript = safe_json_load(row.transcript_json)
    return render_template("dashboard/founder_qa.html", qa_session=row, transcript=transcript)

# In app.py (Replace the api_qa_chat function)

@app.route("/api/qa/chat", methods=["POST"])
def api_qa_chat():
    data = request.json
    session_id = data.get("session_id")
    user_msg = data.get("message")
    
    qa_session = db.session.execute(text("SELECT * FROM qa_sessions WHERE id=:sid"), {"sid": session_id}).fetchone()
    deck = db.session.execute(text("SELECT analysis_json FROM pitch_decks WHERE id=:did"), {"did": qa_session.deck_id}).fetchone()
    
    transcript = safe_json_load(qa_session.transcript_json)
    
    # Update transcript with user message immediately
    if user_msg: 
        transcript.append({"role": "founder", "text": user_msg})

    # 1. Calculate Turns
    turn_count = len(transcript) // 2
    max_turns = 15
    min_turns = 10
    
    # 2. Check Termination Condition
    if turn_count >= max_turns:
        db.session.execute(text("UPDATE qa_sessions SET status='completed', session_score=85, transcript_json=:tj WHERE id=:sid"), {"tj": json.dumps(transcript), "sid": session_id})
        db.session.commit()
        return jsonify({"reply": "Alright, I've seen enough. I'll review your file and get back to you. (Session Ended)", "finished": True})

    # 3. Context & Prompt Engineering
    deck_context = deck.analysis_json if deck and deck.analysis_json else "No analysis available."
    
    # Adaptive Stage Logic
    if turn_count < 3:
        focus = "The Basics & Vision. Test their clarity."
    elif turn_count < 10:
        focus = "The Drill. Pick ONE specific weakness (Competition, Financials, or Go-To-Market) and hammer it. Be skeptical."
    else:
        focus = "Closing. Ask about deal terms, timeline, or exit strategy. If satisfied, type [FINISHED]."

    system_prompt = f"""
    You are a cynical, sharp Venture Capital Partner. You are interviewing a founder.
    
    YOUR PERSONA:
    - You are not a generic AI. You sound like a human investor who is tired of buzzwords.
    - You acknowledge the founder's answer briefly ("Okay, fair point on revenue...") but then immediately find the next hole in their logic ("...but your CAC is significantly higher than industry average.").
    - You are direct, slightly impatient, and focused on risk.

    CONTEXT:
    - Deck Analysis: {deck_context}
    - Current Turn: {turn_count + 1} / {max_turns}
    - Focus for this turn: {focus}
    - History: {json.dumps(transcript)}

    INSTRUCTIONS:
    1. **Bridge & Pivot**: Start by reacting to their last point (agree, disagree, or dismiss). Then pivot to your new question.
    2. **One Question Only**: Ask ONE complex, multi-part question if needed, but do not ask a list of 5 separate things.
    3. **No Fluff**: Do not say "That is an interesting answer." Say "That's ambitious, but..."
    4. **Termination**: You must continue until at least turn {min_turns}. After turn {min_turns}, if you have enough info, end with [FINISHED].
    
    Output plain text only. No markdown formatting like **bold** or # Headers.
    """
    
    try:
        client = get_ai_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=system_prompt
        )
        ai_text = response.text.strip()
        
        finished = False
        if "[FINISHED]" in ai_text:
            ai_text = ai_text.replace("[FINISHED]", "").strip()
            finished = True
            final_score = min(100, 50 + (len(transcript) * 2))
            db.session.execute(text("UPDATE qa_sessions SET status='completed', session_score=:sc WHERE id=:sid"), {"sc": final_score, "sid": session_id})
        
        transcript.append({"role": "investor", "text": ai_text})
        
        db.session.execute(text("UPDATE qa_sessions SET transcript_json=:tj WHERE id=:sid"), {"tj": json.dumps(transcript), "sid": session_id})
        db.session.commit()
        
        return jsonify({"reply": ai_text, "finished": finished})

    except Exception as e:
        print(f"QA Error: {e}")
        return jsonify({"error": str(e)}), 500
    

# -------------------------------------------------
# 5. REPORT GENERATION
# -------------------------------------------------
@app.route("/founder/report/generate/<int:deck_id>")
def generate_report(deck_id):
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")
    founder = db.session.execute(text("SELECT id FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    
    deck = db.session.execute(text("SELECT * FROM pitch_decks WHERE id=:did"), {"did": deck_id}).fetchone()
    qa_sessions = db.session.execute(text("SELECT * FROM qa_sessions WHERE deck_id=:did ORDER BY id DESC LIMIT 5"), {"did": deck_id}).fetchall()
    
    qa_summary = json.dumps([s.transcript_json for s in qa_sessions]) if qa_sessions else "No Q&A data."

    try:
        client = get_ai_client()
        prompt = f"""
        Generate an 'Investment Readiness Report' in HTML for this startup.
        Deck: {deck.analysis_json}
        Q&A: {qa_summary}
        Output valid HTML (no markdown) with sections: Executive Summary, Risks, Founder Defense, Action Plan.
        """
        
        # Fixed Model Name
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        report_html = response.text.replace("```html", "").replace("```", "").strip()
        
        db.session.execute(text("""
            INSERT INTO investment_reports (founder_id, deck_id, report_content) VALUES (:fid, :did, :rpt)
        """), {"fid": founder.id, "did": deck_id, "rpt": report_html})
        db.session.commit()
        return redirect(url_for("view_report", deck_id=deck_id))
        
    except Exception as e:
        flash(f"Error: {str(e)}")
        return redirect(url_for("founder_pitch"))

@app.route("/founder/report/view/<int:deck_id>")
def view_report(deck_id):
    if session.get("role") != "founder": return redirect(url_for("login"))
    report = db.session.execute(text("SELECT * FROM investment_reports WHERE deck_id=:did ORDER BY id DESC LIMIT 1"), {"did": deck_id}).fetchone()
    return render_template("dashboard/founder_report.html", report=report)

# -------------------------------------------------
# 6. TRACTION & METRICS
# -------------------------------------------------
@app.route("/founder/traction", methods=["GET", "POST"])
def founder_traction():
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")
    
    founder_profile = db.session.execute(text("SELECT id, raise_target, traction_report FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()

    if request.method == "POST" and "add_metric" in request.form:
        # Fixed: Added safe_float and safe_int wrappers
        db.session.execute(text("""
            INSERT INTO traction_metrics (founder_id, month_label, revenue, expenses, active_users)
            VALUES (:fid, :m, :r, :e, :u)
        """), {
            "fid": founder_profile.id, 
            "m": request.form.get("month"),
            "r": safe_float(request.form.get("revenue")), 
            "e": safe_float(request.form.get("expenses")), 
            "u": safe_int(request.form.get("users"))
        })
        db.session.commit()
        return redirect(url_for("founder_traction"))

    metrics = db.session.execute(text("SELECT * FROM traction_metrics WHERE founder_id=:fid ORDER BY id ASC"), {"fid": founder_profile.id}).fetchall()
    
    labels = [m.month_label for m in metrics]
    revenue = [float(m.revenue) for m in metrics]
    expenses = [float(m.expenses) for m in metrics]
    
    kpis = {"mrr": 0, "burn": 0, "runway": 0, "growth": 0, "users": 0, "profit": False}
    if metrics:
        last = metrics[-1]
        kpis["mrr"] = float(last.revenue)
        kpis["users"] = last.active_users
        kpis["burn"] = float(last.expenses) - float(last.revenue)
        cash = float(founder_profile.raise_target or 0) * 0.5 
        if kpis["burn"] > 0: kpis["runway"] = cash / kpis["burn"]
        else: kpis["profit"] = True
        
        if len(metrics) > 1:
            prev = float(metrics[-2].revenue)
            if prev > 0: kpis["growth"] = int(((kpis["mrr"] - prev) / prev) * 100)

    return render_template("dashboard/founder_traction.html", labels=json.dumps(labels), revenue=json.dumps(revenue), expenses=json.dumps(expenses), metrics=metrics, kpis=kpis, traction_report=founder_profile.traction_report)

@app.route("/founder/traction/delete/<int:metric_id>")
def delete_traction(metric_id):
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")
    founder = db.session.execute(text("SELECT id FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    db.session.execute(text("DELETE FROM traction_metrics WHERE id=:mid AND founder_id=:fid"), {"mid": metric_id, "fid": founder.id})
    db.session.commit()
    return redirect(url_for("founder_traction"))

@app.route("/founder/traction/analyze", methods=["POST"])
def analyze_traction():
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")
    founder = db.session.execute(text("SELECT id, stage FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    metrics = db.session.execute(text("SELECT * FROM traction_metrics WHERE founder_id=:fid LIMIT 12"), {"fid": founder.id}).fetchall()
    
    if not metrics: return redirect(url_for("founder_traction"))

    data_str = "\n".join([f"{m.month_label}: Rev ${m.revenue}, Exp ${m.expenses}" for m in metrics])
    try:
        client = get_ai_client()
        prompt = f"Analyze these startup financials (Stage: {founder.stage}):\n{data_str}\nOutput HTML with classes 'cfo-insight' highlighting 1 Good Thing, 1 Kill Switch risk, and War Room Orders."
        
        # Fixed Model Name
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        report = response.text.replace("```html", "").replace("```", "").strip()
        db.session.execute(text("UPDATE founder_profiles SET traction_report=:rpt WHERE id=:fid"), {"rpt": report, "fid": founder.id})
        db.session.commit()
    except Exception as e:
        print(e)

    return redirect(url_for("founder_traction"))

# -------------------------------------------------
# 7. MESSAGES & SETTINGS
# -------------------------------------------------
# In app.py

@app.route("/founder/messages")
@app.route("/founder/messages/<int:conversation_id>", methods=["GET", "POST"])  # 1. Allow POST
def founder_messages(conversation_id=None):
    if session.get("role") != "founder": return redirect(url_for("login"))
    user_id = session.get("user_id")

    # 2. Handle Message Sending (POST)
    if request.method == "POST" and conversation_id:
        message_text = request.form.get("message")
        if message_text:
            db.session.execute(text("""
                INSERT INTO messages (conversation_id, sender_id, message)
                VALUES (:cid, :uid, :msg)
            """), {"cid": conversation_id, "uid": user_id, "msg": message_text})
            db.session.commit()
            # Redirect to prevent form resubmission
            return redirect(url_for("founder_messages", conversation_id=conversation_id))

    founder = db.session.execute(text("SELECT id FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()

    # Fetch Conversations List
    conversations = db.session.execute(text("""
        SELECT c.id, u.full_name, ip.fund_name, 
        (SELECT message FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) AS last_msg,
        (SELECT created_at FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) AS last_time,
        (SELECT COUNT(*) FROM messages WHERE conversation_id=c.id AND is_read=0 AND sender_id!=:uid) AS unread_count
        FROM conversations c JOIN investor_profiles ip ON c.investor_id=ip.id JOIN users u ON ip.user_id=u.id
        WHERE c.founder_id=:fid ORDER BY last_time DESC
    """), {"fid": founder.id, "uid": user_id}).fetchall()

    active_partner = None
    active_chat = []  # Initialize empty list

    if conversation_id:
        # Mark as read
        db.session.execute(text("UPDATE messages SET is_read=1 WHERE conversation_id=:cid AND sender_id!=:uid"), {"cid": conversation_id, "uid": user_id})
        db.session.commit()
        
        # Get Partner Details
        active_partner = db.session.execute(text("SELECT u.full_name, ip.fund_name FROM conversations c JOIN investor_profiles ip ON c.investor_id=ip.id JOIN users u ON ip.user_id=u.id WHERE c.id=:cid"), {"cid": conversation_id}).fetchone()

        # 3. CRITICAL FIX: Fetch Messages for this conversation
        active_chat = db.session.execute(text("""
            SELECT * FROM messages WHERE conversation_id=:cid ORDER BY created_at ASC
        """), {"cid": conversation_id}).fetchall()

    return render_template(
        "dashboard/founder_messages.html", 
        conversations=conversations, 
        current_convo=conversation_id, 
        active_partner=active_partner, 
        active_chat=active_chat,   # 4. Pass messages to template
        user_id=user_id
    )
# -------------------------------------------------
# 🟢 API: CHAT (SHARED BY FOUNDER & INVESTOR)
# -------------------------------------------------
# In app.py - Find the API routes (approx line 730) and update them:

@app.route("/api/chat/<int:conversation_id>")
def api_get_chat(conversation_id):  # Renamed for clarity
    # FIX: Allow both roles
    if session.get("role") not in ["founder", "investor"]: 
        return {"error": "Unauthorized"}, 401
        
    user_id = session.get("user_id")
    db.session.execute(text("UPDATE messages SET is_read=1 WHERE conversation_id=:cid AND sender_id!=:uid"), {"cid": conversation_id, "uid": user_id})
    db.session.commit()
    
    msgs = db.session.execute(text("SELECT id, message, created_at, sender_id FROM messages WHERE conversation_id=:cid ORDER BY created_at ASC"), {"cid": conversation_id}).fetchall()
    return {"messages": [{"id": m.id, "text": m.message, "is_me": (m.sender_id == user_id), "time": m.created_at.strftime('%H:%M')} for m in msgs]}

@app.route("/api/chat/send", methods=["POST"])
def api_send_message():
    # FIX: Allow both roles
    if session.get("role") not in ["founder", "investor"]: 
        return {"error": "Unauthorized"}, 401
        
    user_id = session.get("user_id")
    data = request.json
    db.session.execute(text("INSERT INTO messages (conversation_id, sender_id, message, created_at) VALUES (:cid, :uid, :msg, NOW())"), {"cid": data["conversation_id"], "uid": user_id, "msg": data["message"]})
    db.session.commit()
    return {"status": "success"}


# -------------------------------------------------
# 🟢 FOUNDER SETTINGS (UPDATED WITH LINKEDIN & VERIFICATION)
# -------------------------------------------------
@app.route("/founder/settings", methods=["GET", "POST"])
def founder_settings():
    if session.get("role") != "founder":
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # -------------------------------
    # POST → UPDATE PROFILE
    # -------------------------------
    if request.method == "POST":
        
        # --- 1. Handle Logo Upload ---
        logo_url = None
        if "logo" in request.files:
            file = request.files["logo"]
            if file and file.filename:
                # Secure filename and save
                filename = secure_filename(f"logo_{user_id}_{int(time.time())}_{file.filename}")
                file_path = os.path.join(UPLOAD_FOLDER, filename)
                file.save(file_path)
                logo_url = f"/static/uploads/{filename}"

        # --- 2. Build Update Query ---
        # Added 'linkedin_url' to the SET clause
        update_query = """
            UPDATE founder_profiles
            SET
                company_name = :company_name,
                tagline = :tagline,
                website_url = :website_url,
                linkedin_url = :linkedin_url, 
                location = :location,
                stage = :stage,
                sector = :sector,
                business_model = :business_model,
                product_stage = :product_stage,
                team_size = :team_size,
                raise_target = :raise_target,
                min_check_size = :min_check_size,
                actively_raising = :actively_raising
        """
        
        # Added 'linkedin_url' to the parameters
        params = {
            "company_name": request.form.get("company_name"),
            "tagline": request.form.get("tagline"),
            "website_url": request.form.get("website_url"),
            "linkedin_url": request.form.get("linkedin_url"),
            "location": request.form.get("location"),
            "stage": request.form.get("stage"),
            "sector": request.form.get("sector"),
            "business_model": request.form.get("business_model"),
            "product_stage": request.form.get("product_stage"),
            "team_size": request.form.get("team_size") or 0,
            "raise_target": request.form.get("raise_target") or 0,
            "min_check_size": request.form.get("min_check_size") or 0,
            "actively_raising": 1 if request.form.get("actively_raising") else 0,
            "uid": user_id
        }

        # Only update logo_url if a new file was uploaded
        if logo_url:
            update_query += ", logo_url = :logo_url"
            params["logo_url"] = logo_url

        update_query += " WHERE user_id = :uid"

        # Execute Update
        db.session.execute(text(update_query), params)
        db.session.commit()

        # --- 3. Recalculate Completion Score ---
        fresh_data = db.session.execute(text("SELECT * FROM founder_profiles WHERE user_id=:uid"), {"uid": user_id}).mappings().first()
        new_score = calculate_founder_profile_completion_db(fresh_data)

        if fresh_data.profile_completion != new_score:
            db.session.execute(text("UPDATE founder_profiles SET profile_completion=:s WHERE user_id=:uid"), {"s": new_score, "uid": user_id})
            db.session.commit()

        flash("Profile updated successfully!", "success")
        return redirect(url_for("founder_settings"))

    # -------------------------------
    # FETCH DATA
    # -------------------------------
    data = db.session.execute(text("""
        SELECT f.*, u.full_name, u.email, u.phone, u.country
        FROM founder_profiles f
        JOIN users u ON u.id = f.user_id
        WHERE f.user_id = :uid
    """), {"uid": user_id}).mappings().first()

    if not data:
        return redirect(url_for("register", role="founder"))

    return render_template("dashboard/founder_settings.html", data=data)



# -------------------------------------------------
# 🟢 FOUNDER REQUEST VERIFICATION
# -------------------------------------------------
@app.route("/founder/request-verification", methods=["POST"])
def request_founder_verification():
    if session.get("role") != "founder":
        return redirect(url_for("login"))

    user_id = session["user_id"]

    db.session.execute(text("""
        UPDATE founder_profiles
        SET verification_status = 'pending'
        WHERE user_id = :uid
    """), {"uid": user_id})

    db.session.commit()
    flash("Verification request sent to admin for review.", "success")
    return redirect(url_for("founder_settings"))

# -------------------------------------------------
# 🟢 ADMIN – PENDING FOUNDER VERIFICATIONS
# -------------------------------------------------
@app.route("/admin/founder-verifications")
def admin_founder_verifications():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    founders = db.session.execute(text("""
        SELECT f.id, f.company_name, f.stage, f.sector,
               f.profile_completion, f.verification_status,
               u.full_name, u.email
        FROM founder_profiles f
        JOIN users u ON u.id = f.user_id
        WHERE f.verification_status = 'pending'
        ORDER BY f.profile_completion DESC
    """)).mappings().all()

    return render_template(
        "admin/founder_verifications.html",
        founders=founders
    )

# Add to app.py imports
from sqlalchemy import text

# -------------------------------------------------
# 🟢 INVESTOR HOME (OPTIMIZED DEAL FEED)
# -------------------------------------------------
# -------------------------------------------------
# 🟢 INVESTOR HOME (WITH FILTERS & PASSED DEALS)
# -------------------------------------------------
@app.route("/investor/home")
def investor_home():
    # -------------------------------------------------
    # AUTH CHECK
    # -------------------------------------------------
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    user_id = session.get("user_id")

    # -------------------------------------------------
    # 1. FETCH INVESTOR PROFILE
    # -------------------------------------------------
    investor = db.session.execute(
        text("SELECT * FROM investor_profiles WHERE user_id = :uid"),
        {"uid": user_id}
    ).mappings().first()

    if not investor:
        return redirect(url_for("register", role="investor"))

    # -------------------------------------------------
    # 2. FILTERS (STAGE / SECTOR / GEO)
    # -------------------------------------------------
    filter_stage = request.args.get("stage")
    filter_sector = request.args.get("sector")
    filter_geo = request.args.get("geo")

    # -------------------------------------------------
    # 3. FETCH ACTIVE FOUNDERS + LATEST DECK
    # -------------------------------------------------
    query = """
        SELECT 
            f.*,
            u.country AS user_country,
            pd.deck_score
        FROM founder_profiles f
        JOIN users u ON f.user_id = u.id
        LEFT JOIN pitch_decks pd
            ON pd.founder_id = f.id
           AND pd.id = (
                SELECT MAX(id)
                FROM pitch_decks
                WHERE founder_id = f.id
           )
        WHERE f.actively_raising = 1
    """

    params = {}

    if filter_stage:
        query += " AND f.stage = :stage"
        params["stage"] = filter_stage

    if filter_sector:
        query += " AND f.sector LIKE :sector"
        params["sector"] = f"%{filter_sector}%"

    if filter_geo:
        query += " AND (f.location LIKE :geo OR u.country LIKE :geo)"
        params["geo"] = f"%{filter_geo}%"

    founders = db.session.execute(text(query), params).mappings().all()

    # -------------------------------------------------
    # 4. FETCH TRACTION (LATEST 2 RECORDS PER FOUNDER)
    # -------------------------------------------------
    metrics_raw = db.session.execute(text("""
        SELECT founder_id, revenue
        FROM traction_metrics
        ORDER BY founder_id, id DESC
    """)).fetchall()

    metrics_map = {}
    for m in metrics_raw:
        if m.founder_id not in metrics_map:
            metrics_map[m.founder_id] = []
        if len(metrics_map[m.founder_id]) < 2:
            metrics_map[m.founder_id].append(m)

    # -------------------------------------------------
    # 5. EXISTING MATCH STATUS
    # -------------------------------------------------
    existing_matches = db.session.execute(text("""
        SELECT founder_id, status
        FROM matches
        WHERE investor_id = :iid
    """), {"iid": investor.id}).fetchall()

    match_status_map = {m.founder_id: m.status for m in existing_matches}

    # -------------------------------------------------
    # 6. BUILD DEAL FEED (UPDATED LOGIC)
    # -------------------------------------------------
    deal_feed = []      # List for Active/New deals
    passed_deals = []   # List for Declined/Passed deals

    for f in founders:
        status = match_status_map.get(f.id, "new")

        # --- MOVED CALCULATIONS UP ---
        # We calculate this for everyone so Passed deals also have data to show in the UI
        pitch_score = f.deck_score or 0
        match_score, match_reasons = calculate_match_score(f, investor, pitch_score)

        # Traction
        m_data = metrics_map.get(f.id, [])
        mrr = float(m_data[0].revenue) if m_data else 0
        growth = 0
        if len(m_data) > 1 and float(m_data[1].revenue) > 0:
            growth = int(((mrr - float(m_data[1].revenue)) / float(m_data[1].revenue)) * 100)

        # Create Deal Object
        deal_obj = {
            "founder_id": f.id,
            "company_name": f.company_name,
            "tagline": f.tagline,
            "logo_url": f.logo_url,
            "sector": f.sector,
            "stage": f.stage,
            "location": f.location or f.user_country,
            "raise_target": f.raise_target,
            "match_score": match_score,
            "match_reasons": match_reasons,
            "mrr": mrr,
            "growth": growth,
            "pitch_score": pitch_score,
            "status": status
        }

        # --- SPLIT INTO LISTS ---
        if status == "declined":
            passed_deals.append(deal_obj)
        
        # Threshold (keep signal clean)
        # Only add to main feed if score is good OR it's already saved/new
        elif match_score >= 30 or status == "saved":
            deal_feed.append(deal_obj)

    # Sort Active Deals: Saved first → High match score
    deal_feed.sort(
        key=lambda x: (x["status"] == "saved", x["match_score"]),
        reverse=True
    )
    
    # Optional: Sort Passed deals by most recently passed (if you had a timestamp, otherwise just by score)
    passed_deals.sort(key=lambda x: x["match_score"], reverse=True)

    # -------------------------------------------------
    # 7. KPI DEFINITIONS (INVESTOR SIGNALS)
    # -------------------------------------------------
    kpis = {
        # High conviction = strong thesis + strong pitch
        "high_fit": sum(
            1 for d in deal_feed
            if d["match_score"] >= 75 and d["pitch_score"] >= 70
        ),

        # Fresh opportunities not yet actioned
        "new_deals": sum(
            1 for d in deal_feed
            if d["status"] == "new" and d["match_score"] >= 60
        ),

        # Founder momentum (recent deck or traction update)
        "updated_deals": db.session.execute(text("""
            SELECT COUNT(DISTINCT f.id)
            FROM founder_profiles f
            JOIN matches m ON m.founder_id = f.id
            LEFT JOIN pitch_decks p ON p.founder_id = f.id
            LEFT JOIN traction_metrics t ON t.founder_id = f.id
            WHERE m.investor_id = :iid
              AND (
                    p.created_at >= NOW() - INTERVAL 3 DAY
                 OR t.created_at >= NOW() - INTERVAL 3 DAY
              )
        """), {"iid": investor.id}).scalar() or 0,

        # Action required
        "open_conversations": db.session.execute(text("""
            SELECT COUNT(*)
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE c.investor_id = :iid
              AND m.is_read = 0
              AND m.sender_id != :uid
        """), {
            "iid": investor.id,
            "uid": user_id
        }).scalar() or 0
    }

    # -------------------------------------------------
    # 8. RENDER
    # -------------------------------------------------
    return render_template(
        "dashboard/investor_home.html",
        investor=investor,
        deals=deal_feed,
        passed_deals=passed_deals, # <--- Added this variable
        kpis=kpis
    )

# -------------------------------------------------
# 🟢 DEAL ACTIONS: PASS & UNDO
# -------------------------------------------------

@app.route("/investor/deal/pass/<int:founder_id>")
def pass_deal(founder_id):
    if session.get("role") != "investor": return redirect(url_for("login"))
    user_id = session.get("user_id")
    
    investor = db.session.execute(text("SELECT id FROM investor_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    if not investor: return redirect(url_for("investor_home"))

    # Upsert: Set status to 'declined'
    # We use ON DUPLICATE KEY UPDATE to handle both cases (new record or updating existing)
    db.session.execute(text("""
        INSERT INTO matches (founder_id, investor_id, match_score, status, ai_reason)
        VALUES (:fid, :iid, 0, 'declined', 'Manual Pass')
        ON DUPLICATE KEY UPDATE status = 'declined', updated_at = NOW()
    """), {"fid": founder_id, "iid": investor.id})

    db.session.commit()
    flash("Deal moved to Passed list.", "info")
    return redirect(url_for("investor_home"))


@app.route("/investor/deal/undo/<int:founder_id>")
def undo_pass_deal(founder_id):
    if session.get("role") != "investor": return redirect(url_for("login"))
    user_id = session.get("user_id")
    
    investor = db.session.execute(text("SELECT id FROM investor_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    
    # Logic: To "Undo", we simply delete the match record.
    # This resets the deal to "New" because your system treats no record as a "New Deal".
    db.session.execute(text("""
        DELETE FROM matches 
        WHERE founder_id = :fid AND investor_id = :iid AND status = 'declined'
    """), {"fid": founder_id, "iid": investor.id})

    db.session.commit()
    flash("Deal restored to main feed.", "success")
    return redirect(url_for("investor_home"))


# -------------------------------------------------
# 🟢 INVESTOR DEAL VIEW (UPDATED WITH DD)
# -------------------------------------------------
@app.route("/investor/deal/<int:founder_id>")
def investor_deal_view(founder_id):
    # -------------------------------------------------
    # AUTH
    # -------------------------------------------------
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    user_id = session.get("user_id")

    investor = db.session.execute(
        text("SELECT * FROM investor_profiles WHERE user_id = :uid"),
        {"uid": user_id}
    ).mappings().first()

    if not investor:
        return redirect(url_for("register", role="investor"))

    # -------------------------------------------------
    # 1. FOUNDER + USER INFO
    # -------------------------------------------------
    founder = db.session.execute(text("""
        SELECT 
            f.*,
            u.full_name,
            u.country AS user_country
        FROM founder_profiles f
        JOIN users u ON f.user_id = u.id
        WHERE f.id = :fid
    """), {"fid": founder_id}).mappings().first()

    if not founder:
        flash("Startup not found", "error")
        return redirect(url_for("investor_home"))

    # -------------------------------------------------
    # 2. LATEST PITCH DECK
    # -------------------------------------------------
    deck = db.session.execute(text("""
        SELECT *
        FROM pitch_decks
        WHERE founder_id = :fid
        ORDER BY created_at DESC
        LIMIT 1
    """), {"fid": founder_id}).mappings().first()

    deck_score = deck["deck_score"] if deck else 0
    deck_url = deck["file_url"] if deck else None
    analysis_json = deck["analysis_json"] if deck else None

    # -------------------------------------------------
    # 3. MATCH STATUS
    # -------------------------------------------------
    match = db.session.execute(text("""
        SELECT status, match_score
        FROM matches
        WHERE founder_id = :fid
          AND investor_id = :iid
    """), {
        "fid": founder_id,
        "iid": investor["id"]
    }).mappings().first()

    match_status = match["status"] if match else "new"
    match_score = match["match_score"] if match else None

    # -------------------------------------------------
    # 4. TRACTION METRICS (LAST 6 MONTHS)
    # -------------------------------------------------
    traction = db.session.execute(text("""
        SELECT 
            month_label,
            revenue,
            expenses
        FROM traction_metrics
        WHERE founder_id = :fid
        ORDER BY id ASC
        LIMIT 6
    """), {"fid": founder_id}).mappings().all()

    chart_labels = [t["month_label"] for t in traction]
    chart_rev = [float(t["revenue"]) for t in traction]
    chart_exp = [float(t["expenses"]) for t in traction]

    # -------------------------------------------------
    # 5. DUE DILIGENCE DATA (PRIVATE TO INVESTOR)
    # -------------------------------------------------
    dd_data = db.session.execute(text("""
        SELECT *
        FROM investment_reports
        WHERE founder_id = :fid
          AND deck_id = :did
    """), {
        "fid": founder_id,
        "did": deck["id"] if deck else None
    }).mappings().first()

    checklist = {}
    private_notes = ""

    if dd_data and dd_data.get("report_content"):
        try:
            parsed = json.loads(dd_data["report_content"])
            checklist = parsed.get("checklist", {})
            private_notes = parsed.get("notes", "")
        except Exception:
            checklist = {}
            private_notes = ""

# -------------------------------------------------
    # 6. RENDER
    # -------------------------------------------------
    return render_template(
        "dashboard/investor_deal_view.html",
        founder={
            **founder,
            "location": founder["location"] or founder["user_country"],
            "deck_score": deck_score,
            "deck_url": deck_url,
            "analysis_json": analysis_json
        },
        match_status=match_status,
        match_score=match_score,
        chart_labels=chart_labels,
        chart_rev=chart_rev,
        chart_exp=chart_exp,
        
        # FIX: Pass checklist explicitly so the template can find it
        checklist=checklist, 
        
        dd_data={
            "checklist": checklist,
            "private_notes": private_notes
        }
    )

# -------------------------------------------------
# 🟢 INVESTOR DEALS (WITH AUTO-SCORE REPAIR)
# -------------------------------------------------
@app.route("/investor/deals")
def investor_deals():
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    user_id = session.get("user_id")
    tab = request.args.get("tab", "interested")

    # 1. FETCH FULL INVESTOR PROFILE (Required for calculation)
    # We use mappings() to get a dictionary-like object
    investor_data = db.session.execute(
        text("SELECT * FROM investor_profiles WHERE user_id=:uid"),
        {"uid": user_id}
    ).mappings().first()

    if not investor_data:
        return redirect(url_for("register", role="investor"))

    # Helper class to allow dot notation (investor.sector_focus) for the calculation function
    class EntityObj:
        def __init__(self, d):
            for k, v in d.items():
                setattr(self, k, v)

    investor_obj = EntityObj(investor_data)

    # 2. FETCH DEALS (Updated with logo_url)
    deals = db.session.execute(text("""
        SELECT 
            f.id AS founder_id,
            f.company_name,
            f.logo_url,        /* <--- Added this field for the logo */
            f.sector,
            f.stage,
            f.location,
            f.min_check_size,

            m.status,
            m.match_score,
            m.updated_at,

            (SELECT deck_score 
             FROM pitch_decks 
             WHERE founder_id=f.id 
             ORDER BY created_at DESC LIMIT 1) AS pitch_score,

            (SELECT checklist_json 
             FROM due_diligence 
             WHERE founder_id=f.id AND investor_id=:iid) AS dd_checklist,

            GREATEST(
                COALESCE(m.updated_at, '1970-01-01'),
                COALESCE((SELECT MAX(created_at) FROM pitch_decks WHERE founder_id=f.id), '1970-01-01'),
                COALESCE((SELECT MAX(created_at) FROM traction_metrics WHERE founder_id=f.id), '1970-01-01')
            ) AS last_activity

        FROM matches m
        JOIN founder_profiles f ON f.id = m.founder_id
        WHERE m.investor_id = :iid
          AND m.status = :tab
        ORDER BY last_activity DESC
    """), {
        "iid": investor_data['id'],
        "tab": tab
    }).mappings().all()

    # 3. HELPER FUNCTIONS
    def dd_progress(checklist_json):
        if not checklist_json: return 0
        try:
            data = json.loads(checklist_json)
            total = len(data)
            done = sum(1 for v in data.values() if v)
            return int((done / total) * 100) if total else 0
        except: return 0

    def time_ago(dt):
        if not dt or (isinstance(dt, str) and dt.startswith('1970')): return "N/A"
        if isinstance(dt, str):
            try: dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
            except: return "N/A"
        diff = datetime.utcnow() - dt
        if diff.days > 0: return f"{diff.days}d ago"
        hours = diff.seconds // 3600
        if hours > 0: return f"{hours}h ago"
        return "Just now"

    # 4. ENRICH & AUTO-REPAIR SCORES
    enriched_deals = []
    updates_needed = False

    for d in deals:
        deal_dict = dict(d) # Create mutable copy
        
        # --- AUTO-FIX LOGIC: If score is 0, recalculate it now ---
        if deal_dict.get('match_score') == 0:
            # Create a temporary founder object for the calculator
            founder_mock = EntityObj({
                'stage': deal_dict.get('stage'),
                'sector': deal_dict.get('sector'),
                'location': deal_dict.get('location'),
                'min_check_size': deal_dict.get('min_check_size')
            })
            
            # Run calculation
            new_score, new_reason = calculate_match_score(
                founder_mock, 
                investor_obj, 
                deal_dict.get('pitch_score') or 0
            )
            
            # Update local display data
            deal_dict['match_score'] = new_score
            
            # Update Database (Silent Repair)
            db.session.execute(text("""
                UPDATE matches 
                SET match_score = :s, ai_reason = :r 
                WHERE founder_id = :fid AND investor_id = :iid
            """), {
                "s": new_score, 
                "r": new_reason, 
                "fid": deal_dict['founder_id'], 
                "iid": investor_data['id']
            })
            updates_needed = True

        enriched_deals.append({
            **deal_dict,
            "dd_progress": dd_progress(d.dd_checklist),
            "last_seen": time_ago(d.last_activity)
        })

    # Commit any repairs we made
    if updates_needed:
        db.session.commit()

    return render_template(
        "dashboard/investor_deals.html",
        deals=enriched_deals,
        active_tab=tab
    )

# BULK ACTIONS (PASS / ARCHIVE)
@app.route("/investor/deals/bulk", methods=["POST"])
def bulk_update_deals():
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    action = request.form.get("action")
    founder_ids = request.form.getlist("deal_ids")

    if not founder_ids:
        flash("No deals selected", "warning")
        return redirect(url_for("investor_deals"))

    investor = db.session.execute(
        text("SELECT id FROM investor_profiles WHERE user_id=:uid"),
        {"uid": session.get("user_id")}
    ).fetchone()

    db.session.execute(text("""
        UPDATE matches
        SET status=:st, updated_at=NOW()
        WHERE investor_id=:iid
          AND founder_id IN :ids
    """), {
        "st": action,
        "iid": investor.id,
        "ids": tuple(map(int, founder_ids))
    })

    db.session.commit()
    flash(f"{len(founder_ids)} deals updated", "success")

    return redirect(url_for("investor_deals"))

# SAVE DUE DILIGENCE (CHECKLIST + NOTES)

@app.route("/api/investor/save_dd", methods=["POST"])
def save_due_diligence():
    if session.get("role") != "investor":
        return {"error": "unauthorized"}, 401

    data = request.get_json()
    founder_id = data.get("founder_id")
    checklist = json.dumps(data.get("checklist", {}))
    notes = data.get("notes", "")

    investor = db.session.execute(
        text("SELECT id FROM investor_profiles WHERE user_id=:uid"),
        {"uid": session.get("user_id")}
    ).fetchone()

    db.session.execute(text("""
        INSERT INTO due_diligence (investor_id, founder_id, checklist_json, private_notes)
        VALUES (:iid, :fid, :chk, :notes)
        ON DUPLICATE KEY UPDATE
            checklist_json=:chk,
            private_notes=:notes,
            updated_at=NOW()
    """), {
        "iid": investor.id,
        "fid": founder_id,
        "chk": checklist,
        "notes": notes
    })

    db.session.commit()
    return {"status": "ok"}
# AUTO-GENERATE INVESTMENT MEMO (PDF)

@app.route("/investor/deal/<int:fid>/memo")
def generate_investment_memo(fid):
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    investor_id = db.session.execute(
        text("SELECT id FROM investor_profiles WHERE user_id=:uid"),
        {"uid": session.get("user_id")}
    ).scalar()

    founder = db.session.execute(
        text("SELECT * FROM founder_profiles WHERE id=:fid"),
        {"fid": fid}
    ).mappings().first()

    if not founder:
        flash("Startup not found", "error")
        return redirect(url_for("investor_deals"))

    memo_text = f"""
Investment Memo – {founder.company_name}

Sector: {founder.sector}
Stage: {founder.stage}
Location: {founder.location}

Summary:
This startup aligns with the investor's thesis based on market, traction, and execution readiness.

Recommendation:
Proceed to deeper diligence.
"""

    from reportlab.platypus import SimpleDocTemplate, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet

    file_path = f"/tmp/investment_memo_{fid}.pdf"
    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()
    story = [Paragraph(line, styles["Normal"]) for line in memo_text.split("\n\n")]

    doc.build(story)

    return send_file(file_path, as_attachment=True)

# -------------------------------------------------
# 🟢 API: SAVE DD NOTES & CHECKLIST
# -------------------------------------------------
@app.route("/api/investor/save_dd", methods=["POST"])
def save_dd_data():
    if session.get("role") != "investor": return {"error": "Unauthorized"}, 401
    user_id = session.get("user_id")
    data = request.json
    
    investor = db.session.execute(text("SELECT id FROM investor_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    
    # Upsert Logic (Insert if new, Update if exists)
    db.session.execute(text("""
        INSERT INTO due_diligence (investor_id, founder_id, private_notes, checklist_json)
        VALUES (:iid, :fid, :notes, :json)
        ON DUPLICATE KEY UPDATE private_notes = :notes, checklist_json = :json, updated_at = NOW()
    """), {
        "iid": investor.id,
        "fid": data["founder_id"],
        "notes": data.get("notes", ""),
        "json": json.dumps(data.get("checklist", {}))
    })
    
    db.session.commit()
    return {"status": "saved"}
# -------------------------------------------------
# 🟢 MATCH ACTIONS (SAVE / PASS / CONNECT)
# -------------------------------------------------
@app.route("/investor/match/<int:founder_id>/<action>")
def update_investor_match(founder_id, action):
    if session.get("role") != "investor": return redirect(url_for("login"))
    user_id = session.get("user_id")
    
    investor = db.session.execute(text("SELECT id FROM investor_profiles WHERE user_id=:uid"), {"uid": user_id}).fetchone()
    if not investor: return redirect(url_for("investor_home"))

    # Validate Action
    if action not in ['saved', 'interested', 'declined']:
        return redirect(url_for("investor_home"))

    # Upsert Match Record
    # We use a dummy score of 0 if creating new, expecting the cron/algorithm to update it later, 
    # OR we just rely on the fact that if they are clicking, they saw it in the feed (so score exists theoretically).
    # For robustness, we update the status.
    
    # Check if match exists
    existing = db.session.execute(text("""
        SELECT id FROM matches WHERE founder_id=:fid AND investor_id=:iid
    """), {"fid": founder_id, "iid": investor.id}).fetchone()

    if existing:
        db.session.execute(text("""
            UPDATE matches SET status=:st, updated_at=NOW() WHERE id=:mid
        """), {"st": action, "mid": existing.id})
    else:
        # Create new entry if they interacted before the batch job ran
        db.session.execute(text("""
            INSERT INTO matches (founder_id, investor_id, match_score, status, ai_reason)
            VALUES (:fid, :iid, 0, :st, 'Manual Interaction')
        """), {"fid": founder_id, "iid": investor.id, "st": action})

    # If Connected (Interested), Create Conversation Immediately
    if action == 'interested':
        db.session.execute(text("""
            INSERT IGNORE INTO conversations (founder_id, investor_id, created_at)
            VALUES (:fid, :iid, NOW())
        """), {"fid": founder_id, "iid": investor.id})
        flash(f"Connection request sent!", "success")

    db.session.commit()
    return redirect(url_for("investor_home"))
# -------------------------------------------------
# 🟢 INVESTOR MESSAGES
# -------------------------------------------------
@app.route("/investor/messages")
@app.route("/investor/messages/<int:conversation_id>", methods=["GET", "POST"])
def investor_messages(conversation_id=None):
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    user_id = session.get("user_id")

    if request.method == "POST" and conversation_id:
        msg = request.form.get("message")
        if msg:
            db.session.execute(text("""
                INSERT INTO messages (conversation_id, sender_id, message, created_at)
                VALUES (:cid, :uid, :msg, NOW())
            """), {"cid": conversation_id, "uid": user_id, "msg": msg})
            db.session.commit()
            return redirect(url_for("investor_messages", conversation_id=conversation_id))

    investor = db.session.execute(
        text("SELECT id FROM investor_profiles WHERE user_id=:uid"),
        {"uid": user_id}
    ).fetchone()

    conversations = db.session.execute(text("""
        SELECT c.id, u.full_name, fp.company_name,
        (SELECT message FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) AS last_msg,
        (SELECT created_at FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) AS last_time,
        (SELECT COUNT(*) FROM messages WHERE conversation_id=c.id AND is_read=0 AND sender_id!=:uid) AS unread_count
        FROM conversations c
        JOIN founder_profiles fp ON c.founder_id = fp.id
        JOIN users u ON fp.user_id = u.id
        WHERE c.investor_id=:iid
        ORDER BY last_time DESC
    """), {"iid": investor.id, "uid": user_id}).fetchall()

    active_chat = []
    active_partner = None

    if conversation_id:
        db.session.execute(text("""
            UPDATE messages SET is_read=1
            WHERE conversation_id=:cid AND sender_id!=:uid
        """), {"cid": conversation_id, "uid": user_id})
        db.session.commit()

        active_partner = db.session.execute(text("""
            SELECT u.full_name, fp.company_name
            FROM conversations c
            JOIN founder_profiles fp ON c.founder_id=fp.id
            JOIN users u ON fp.user_id=u.id
            WHERE c.id=:cid
        """), {"cid": conversation_id}).fetchone()

        active_chat = db.session.execute(text("""
            SELECT * FROM messages
            WHERE conversation_id=:cid
            ORDER BY created_at ASC
        """), {"cid": conversation_id}).fetchall()

    return render_template(
        "dashboard/investor_messages.html",
        conversations=conversations,
        current_convo=conversation_id,
        active_partner=active_partner,
        active_chat=active_chat,
        user_id=user_id
    )
# -------------------------------------------------
# 🟢 INVESTOR PORTFOLIO (Fund Intelligence)
# -------------------------------------------------
@app.route("/investor/portfolio")
def investor_portfolio():
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    user_id = session.get("user_id")

    investor = db.session.execute(
        text("SELECT * FROM investor_profiles WHERE user_id=:uid"),
        {"uid": user_id}
    ).mappings().first()

    if not investor:
        return redirect(url_for("investor_settings"))

    # -------------------------------
    # PORTFOLIO COMPANIES
    # -------------------------------
    portfolio_raw = db.session.execute(text("""
        SELECT
            m.invested_amount,
            m.invested_at,

            f.id AS founder_id,
            f.company_name,
            f.logo_url,
            f.sector,
            f.stage,
            f.location,

            (
                SELECT revenue
                FROM traction_metrics
                WHERE founder_id=f.id
                ORDER BY id DESC LIMIT 1
            ) AS current_mrr

        FROM matches m
        JOIN founder_profiles f ON f.id = m.founder_id
        WHERE m.investor_id=:iid
          AND m.status='invested'
        ORDER BY m.invested_at DESC
    """), {"iid": investor.id}).mappings().all()

    portfolio = []
    total_invested = 0
    total_mrr = 0

    for p in portfolio_raw:
        invested = float(p.invested_amount or 0)
        mrr = float(p.current_mrr or 0)
        annual_value = mrr * 12

        portfolio.append({
            **p,
            "moic": calculate_moic(invested, annual_value),
            "irr": calculate_irr_proxy(invested, annual_value, p.invested_at)
        })

        total_invested += invested
        total_mrr += mrr

    fund_size = float(investor.fund_size or 0)
    dry_powder = max(fund_size - total_invested, 0)

    # -------------------------------
    # SECTOR ALLOCATION
    # -------------------------------
    sector_map = {}
    for p in portfolio:
        sector = p["sector"] or "Other"
        sector_map[sector] = sector_map.get(sector, 0) + float(p["invested_amount"] or 0)

    # -------------------------------
    # PORTFOLIO TREND (MRR)
    # -------------------------------
    trends = db.session.execute(text("""
        SELECT month_label, SUM(revenue) AS total_mrr
        FROM traction_metrics
        WHERE founder_id IN (
            SELECT founder_id
            FROM matches
            WHERE investor_id=:iid AND status='invested'
        )
        GROUP BY month_label
        ORDER BY MIN(created_at)
    """), {"iid": investor.id}).mappings().all()

    trend_labels = [t.month_label for t in trends]
    trend_values = [float(t.total_mrr) for t in trends]

    # -------------------------------
    # FOUNDER UPDATES FEED
    # -------------------------------
    updates = db.session.execute(text("""
        SELECT f.company_name, u.month_label, u.update_text, u.created_at
        FROM founder_updates u
        JOIN founder_profiles f ON f.id = u.founder_id
        WHERE u.founder_id IN (
            SELECT founder_id
            FROM matches
            WHERE investor_id=:iid AND status='invested'
        )
        ORDER BY u.created_at DESC
        LIMIT 10
    """), {"iid": investor.id}).mappings().all()

    return render_template(
        "dashboard/investor_portfolio.html",
        investor=investor,
        portfolio=portfolio,
        updates=updates,
        metrics={
            "fund_size": fund_size,
            "deployed": total_invested,
            "dry_powder": dry_powder,
            "count": len(portfolio),
            "total_mrr": total_mrr
        },
        chart_labels=json.dumps(list(sector_map.keys())),
        chart_data=json.dumps(list(sector_map.values())),
        trend_labels=json.dumps(trend_labels),
        trend_values=json.dumps(trend_values)
    )

@app.route("/investor/portfolio/export/csv")
def export_portfolio_csv():
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    investor_id = db.session.execute(
        text("SELECT id FROM investor_profiles WHERE user_id=:uid"),
        {"uid": session.get("user_id")}
    ).scalar()

    rows = db.session.execute(text("""
        SELECT f.company_name, m.invested_amount, m.invested_at
        FROM matches m
        JOIN founder_profiles f ON f.id=m.founder_id
        WHERE m.investor_id=:iid AND m.status='invested'
    """), {"iid": investor_id}).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Company", "Invested Amount", "Invested At"])

    for r in rows:
        writer.writerow(r)

    output.seek(0)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"}
    )

# -------------------------------------------------
# 🟢 HELPER: MARK DEAL AS INVESTED (Testing / Admin)
# -------------------------------------------------
@app.route("/investor/mark_invested/<int:founder_id>", methods=["POST"])
def mark_invested(founder_id):
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    user_id = session.get("user_id")
    amount = float(request.form.get("amount", 0))

    investor = db.session.execute(
        text("SELECT id FROM investor_profiles WHERE user_id=:uid"),
        {"uid": user_id}
    ).fetchone()

    if not investor:
        flash("Investor profile not found.", "error")
        return redirect(url_for("investor_home"))

    db.session.execute(text("""
        UPDATE matches
        SET status = 'invested',
            invested_amount = :amt,
            invested_at = NOW(),
            updated_at = NOW()
        WHERE founder_id = :fid
          AND investor_id = :iid
    """), {
        "amt": amount,
        "fid": founder_id,
        "iid": investor.id
    })

    db.session.commit()
    flash("Investment recorded and added to Portfolio.", "success")
    return redirect(url_for("investor_portfolio"))


@app.route("/messages")
def messages_inbox():
    if "user_id" not in session:
        return redirect(url_for("login"))

    uid = session["user_id"]
    role = session["role"]

    if role == "investor":
        conversations = db.session.execute(text("""
            SELECT
                c.id AS convo_id,
                f.company_name,
                (
                    SELECT message
                    FROM messages
                    WHERE conversation_id = c.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) AS last_message,
                (
                    SELECT COUNT(*)
                    FROM messages
                    WHERE conversation_id = c.id
                      AND is_read = 0
                      AND sender_id != :uid
                ) AS unread_count
            FROM conversations c
            JOIN founder_profiles f ON f.id = c.founder_id
            WHERE c.investor_id = (
                SELECT id FROM investor_profiles WHERE user_id = :uid
            )
            ORDER BY c.created_at DESC
        """), {"uid": uid}).mappings().all()
    else:
        conversations = db.session.execute(text("""
            SELECT
                c.id AS convo_id,
                i.fund_name,
                (
                    SELECT message
                    FROM messages
                    WHERE conversation_id = c.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) AS last_message,
                (
                    SELECT COUNT(*)
                    FROM messages
                    WHERE conversation_id = c.id
                      AND is_read = 0
                      AND sender_id != :uid
                ) AS unread_count
            FROM conversations c
            JOIN investor_profiles i ON i.id = c.investor_id
            WHERE c.founder_id = (
                SELECT id FROM founder_profiles WHERE user_id = :uid
            )
            ORDER BY c.created_at DESC
        """), {"uid": uid}).mappings().all()

    return render_template(
        "dashboard/investment_messages.html",
        conversations=conversations
    )
@app.route("/api/messages/<int:conversation_id>")
def api_get_messages(conversation_id):
    if "user_id" not in session:
        return jsonify({"error": "unauthorized"}), 401

    msgs = db.session.execute(text("""
        SELECT
            m.id,
            m.message,
            m.attachment_url,
            m.sender_id,
            m.created_at,
            u.full_name
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE m.conversation_id = :cid
        ORDER BY m.created_at ASC
    """), {"cid": conversation_id}).mappings().all()

    return jsonify({"messages": msgs})
@app.route("/messages/<int:conversation_id>")
def message_thread(conversation_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    convo = db.session.execute(text("""
        SELECT * FROM conversations WHERE id = :cid
    """), {"cid": conversation_id}).mappings().first()

    if not convo:
        flash("Conversation not found", "error")
        return redirect(url_for("messages_inbox"))

    messages = db.session.execute(text("""
        SELECT m.*, u.full_name
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.conversation_id = :cid
        ORDER BY m.created_at ASC
    """), {"cid": conversation_id}).mappings().all()

    db.session.execute(text("""
        UPDATE messages
        SET is_read = 1
        WHERE conversation_id = :cid
          AND sender_id != :uid
    """), {"cid": conversation_id, "uid": user_id})
    db.session.commit()

    return render_template(
        "dashboard/message_thread.html",
        conversation_id=conversation_id,
        messages=messages,
        user_id=user_id
    )
@app.route("/messages/send", methods=["POST"])
def send_message():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conversation_id = request.form.get("conversation_id")
    text_msg = request.form.get("message")
    file = request.files.get("attachment")

    if not text_msg and not file:
        flash("Message cannot be empty", "warning")
        return redirect(url_for("message_thread", conversation_id=conversation_id))

    attachment_url = None
    if file:
        os.makedirs("static/uploads", exist_ok=True)
        path = f"static/uploads/{file.filename}"
        file.save(path)
        attachment_url = path

    db.session.execute(text("""
        INSERT INTO messages (conversation_id, sender_id, message, attachment_url)
        VALUES (:cid, :uid, :msg, :file)
    """), {
        "cid": conversation_id,
        "uid": session["user_id"],
        "msg": text_msg,
        "file": attachment_url
    })

    db.session.commit()
    return redirect(url_for("message_thread", conversation_id=conversation_id))
@app.route("/messages/search")
def search_messages():
    if "user_id" not in session:
        return jsonify({"error": "unauthorized"}), 401

    q = f"%{request.args.get('q','')}%"

    results = db.session.execute(text("""
        SELECT DISTINCT
            c.id AS convo_id,
            f.company_name
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        JOIN founder_profiles f ON f.id = c.founder_id
        WHERE m.message LIKE :q
    """), {"q": q}).mappings().all()

    return jsonify({"results": results})
@app.route("/messages/summary/<int:conversation_id>")
def message_ai_summary(conversation_id):
    if "user_id" not in session:
        return jsonify({"error": "unauthorized"}), 401

    rows = db.session.execute(text("""
        SELECT message
        FROM messages
        WHERE conversation_id = :cid
          AND message IS NOT NULL
          AND message != ''
        ORDER BY created_at ASC
    """), {"cid": conversation_id}).fetchall()

    # ✅ SAFETY: ensure strings only
    messages = [str(r[0]) for r in rows if r[0]]

    if not messages:
        return jsonify({
            "summary": "No meaningful messages to summarize yet."
        })

    prompt = f"""
You are an investment analyst AI.

Summarize the following investor–founder conversation.

Output sections:
- Key Asks
- Risks / Concerns
- Traction Signals
- Next Steps

Conversation:
{"\n".join(messages)}
"""

    summary = generate_ai(prompt)  # Gemini / OpenAI wrapper

    return jsonify({"summary": summary})

# -------------------------------------------------
# 🟢 INVESTOR SETTINGS
# -------------------------------------------------
@app.route("/investor/settings", methods=["GET", "POST"])
def investor_settings():
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    user_id = session.get("user_id")

    investor = db.session.execute(text("""
        SELECT i.*, u.full_name, u.email
        FROM investor_profiles i
        JOIN users u ON u.id = i.user_id
        WHERE i.user_id = :uid
    """), {"uid": user_id}).mappings().first()

    if not investor:
        return redirect(url_for("register", role="investor"))

    if request.method == "POST":

        privacy = {
            "show_fund_size": bool(request.form.get("show_fund_size")),
            "show_check_size": bool(request.form.get("show_check_size")),
            "show_thesis": bool(request.form.get("show_thesis")),
            "show_portfolio": bool(request.form.get("show_portfolio"))
        }

        updated = {
            "title": request.form.get("title"),
            "fund_name": request.form.get("fund_name"),
            "fund_size": request.form.get("fund_size"),
            "typical_check_min": request.form.get("check_min"),
            "typical_check_max": request.form.get("check_max"),
            "investment_stage": request.form.get("investment_stage"),
            "sector_focus": request.form.get("sector_focus"),
            "geography_focus": request.form.get("geography_focus"),
            "investment_thesis": request.form.get("investment_thesis"),
            "notable_investments": request.form.get("notable_investments"),
            "portfolio_url": request.form.get("portfolio_url"),
            "activity_status": request.form.get("activity_status"),
            "privacy_settings": json.dumps(privacy)
        }

        completion = calculate_investor_profile_completion(updated)

        db.session.execute(text("""
            UPDATE investor_profiles
            SET
                title = :title,
                fund_name = :fund_name,
                fund_size = :fund_size,
                typical_check_min = :typical_check_min,
                typical_check_max = :typical_check_max,
                investment_stage = :investment_stage,
                sector_focus = :sector_focus,
                geography_focus = :geography_focus,
                investment_thesis = :investment_thesis,
                notable_investments = :notable_investments,
                portfolio_url = :portfolio_url,
                activity_status = :activity_status,
                privacy_settings = :privacy_settings,
                profile_completion = :profile_completion
            WHERE user_id = :uid
        """), {
            **updated,
            "profile_completion": completion,
            "uid": user_id
        })

        db.session.commit()
        flash("Investor profile updated successfully", "success")
        return redirect(url_for("investor_settings"))

    return render_template(
        "dashboard/investor_settings.html",
        investor=investor
    )
@app.route("/investor/request-verification", methods=["POST"])
def request_investor_verification():
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    db.session.execute(text("""
        UPDATE investor_profiles
        SET verification_status = 'pending'
        WHERE user_id = :uid
    """), {"uid": session.get("user_id")})

    db.session.commit()
    flash("Verification request submitted for admin review.", "success")
    return redirect(url_for("investor_settings"))
# -------------------------------------------------
# 🟢 RECORD INVESTMENT (Finalize Deal)
# -------------------------------------------------
@app.route("/investor/record_investment/<int:founder_id>", methods=["POST"])
def record_investment(founder_id):
    # 1. Auth Check
    if session.get("role") != "investor":
        return redirect(url_for("login"))

    user_id = session.get("user_id")
    
    # 2. Get Input
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        flash("Invalid amount entered.", "error")
        return redirect(url_for("investor_deal_view", founder_id=founder_id))

    if amount <= 0:
        flash("Investment amount must be positive.", "warning")
        return redirect(url_for("investor_deal_view", founder_id=founder_id))

    # 3. Get Investor Profile ID
    investor = db.session.execute(
        text("SELECT id FROM investor_profiles WHERE user_id=:uid"),
        {"uid": user_id}
    ).fetchone()

    if not investor:
        flash("Investor profile not found.", "error")
        return redirect(url_for("investor_home"))

    # 4. Update the Match Record (The Deal)
    # This logic handles both existing matches (updating them) 
    # and creating a new one if for some reason it didn't exist yet.
    
    # Check if match exists
    existing_match = db.session.execute(
        text("SELECT id FROM matches WHERE founder_id=:fid AND investor_id=:iid"),
        {"fid": founder_id, "iid": investor.id}
    ).fetchone()

    if existing_match:
        db.session.execute(text("""
            UPDATE matches
            SET status = 'invested',
                invested_amount = :amt,
                invested_at = NOW(),
                updated_at = NOW()
            WHERE id = :mid
        """), {
            "amt": amount,
            "mid": existing_match.id
        })
    else:
        # Create new entry directly as invested (edge case)
        db.session.execute(text("""
            INSERT INTO matches (founder_id, investor_id, match_score, status, invested_amount, invested_at)
            VALUES (:fid, :iid, 0, 'invested', :amt, NOW())
        """), {
            "fid": founder_id, 
            "iid": investor.id, 
            "amt": amount
        })

    db.session.commit()

    # 5. Success Feedback
    founder_name = db.session.execute(text("SELECT company_name FROM founder_profiles WHERE id=:fid"), {"fid": founder_id}).scalar()
    flash(f"Successfully invested ${amount:,.0f} in {founder_name}! Added to your Portfolio.", "success")
    
    return redirect(url_for("investor_portfolio"))
# -------------------------------------------------
# 🛡️ ADMIN – VERIFICATION HUB
# -------------------------------------------------
@app.route("/admin/verifications")
def admin_verifications():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    investors = db.session.execute(text("""
        SELECT i.id, i.fund_name, i.profile_completion,
               i.verification_status, u.full_name, u.email
        FROM investor_profiles i
        JOIN users u ON u.id = i.user_id
        WHERE i.verification_status = 'pending'
        ORDER BY i.profile_completion DESC
    """)).mappings().all()

    founders = db.session.execute(text("""
        SELECT f.id, f.company_name, f.profile_completion,
               f.verification_status, u.full_name, u.email
        FROM founder_profiles f
        JOIN users u ON u.id = f.user_id
        WHERE f.verification_status = 'pending'
        ORDER BY f.profile_completion DESC
    """)).mappings().all()

    return render_template(
        "admin/verifications.html",
        investors=investors,
        founders=founders
    )
# Investor 
@app.route("/admin/investor/verify/<int:investor_id>", methods=["POST"])
def admin_verify_investor(investor_id):
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    db.session.execute(text("""
        UPDATE investor_profiles
        SET verification_status = 'verified'
        WHERE id = :iid
    """), {"iid": investor_id})

    db.session.commit()
    flash("Investor verified successfully.", "success")
    return redirect(url_for("admin_verifications"))


@app.route("/admin/investor/reject/<int:investor_id>", methods=["POST"])
def admin_reject_investor(investor_id):
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    db.session.execute(text("""
        UPDATE investor_profiles
        SET verification_status = 'rejected'
        WHERE id = :iid
    """), {"iid": investor_id})

    db.session.commit()
    flash("Investor verification rejected.", "warning")
    return redirect(url_for("admin_verifications"))
# Founder 

@app.route("/admin/founder/verify/<int:founder_id>", methods=["POST"])
def admin_verify_founder(founder_id):
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    db.session.execute(text("""
        UPDATE founder_profiles
        SET verification_status = 'verified'
        WHERE id = :fid
    """), {"fid": founder_id})

    db.session.commit()
    flash("Founder verified successfully.", "success")
    return redirect(url_for("admin_verifications"))


@app.route("/admin/founder/reject/<int:founder_id>", methods=["POST"])
def admin_reject_founder(founder_id):
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    db.session.execute(text("""
        UPDATE founder_profiles
        SET verification_status = 'rejected'
        WHERE id = :fid
    """), {"fid": founder_id})

    db.session.commit()
    flash("Founder verification rejected.", "warning")
    return redirect(url_for("admin_verifications"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("entry"))

if __name__ == "__main__":
    app.run(host='0.0.0.0',port=8000, debug=True)