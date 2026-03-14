import os
import json
import logging
from functools import wraps
from datetime import datetime, timedelta, time, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response, send_file
import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import subprocess
from google.cloud.firestore import SERVER_TIMESTAMP, DELETE_FIELD
import io
import csv
import sys
import traceback
import hashlib
import secrets
import base64

# Optional encryption - only if cryptography is available
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    print("Warning: Cryptography not installed. Encryption features disabled.")

# PDF generation imports
try:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("Warning: ReportLab not installed. PDF generation will be disabled.")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------
# SECURITY MANAGER
# ----------------------
class SecurityManager:
    """Enhanced security manager for data encryption and protection"""
    
    def __init__(self):
        self.secret_key = os.environ.get("SPORTSCOUT_SECRET", self._generate_secret_key())
        if ENCRYPTION_AVAILABLE:
            self.encryption_key = self._derive_encryption_key()
            self.cipher_suite = Fernet(self.encryption_key)
        else:
            self.cipher_suite = None
    
    def _generate_secret_key(self):
        """Generate a secure random secret key"""
        return secrets.token_urlsafe(32)
    
    def _derive_encryption_key(self):
        """Derive encryption key from secret"""
        if not ENCRYPTION_AVAILABLE:
            return None
        password = self.secret_key.encode()
        salt = b"sportscout_salt_2025"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        return key
    
    def encrypt_data(self, data):
        """Encrypt sensitive data"""
        if not self.cipher_suite:
            return data  # Return original if encryption not available
        try:
            if isinstance(data, str):
                data = data.encode()
            elif not isinstance(data, bytes):
                data = str(data).encode()
            
            encrypted_data = self.cipher_suite.encrypt(data)
            return base64.urlsafe_b64encode(encrypted_data).decode()
        except Exception as e:
            logger.error(f"Encryption error: {e}")
            return data  # Return original on error
    
    def decrypt_data(self, encrypted_data):
        """Decrypt sensitive data"""
        if not self.cipher_suite:
            return encrypted_data  # Return original if encryption not available
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted_data = self.cipher_suite.decrypt(encrypted_bytes)
            return decrypted_data.decode()
        except Exception as e:
            logger.error(f"Decryption error: {e}")
            return encrypted_data  # Return original on error
    
    def hash_session_id(self, session_id):
        """Hash session ID for security"""
        return hashlib.sha256(f"{session_id}{self.secret_key}".encode()).hexdigest()

# Initialize security manager
security_manager = SecurityManager()

# ----------------------
# Flask App Configuration
# ----------------------
app = Flask(__name__)
app.secret_key = security_manager.secret_key

# ----------------------
# Firebase Configuration
# ----------------------
def initialize_firebase():
    """Initialize Firebase only once — loads credentials from environment variable"""
    if not firebase_admin._apps:
        try:
            # FIX #2: Load Firebase credentials from environment variable instead of
            # hardcoded serviceAccountKey.json file, so the key is never committed to GitHub.
            # Set FIREBASE_CREDENTIALS env var to the full JSON contents of serviceAccountKey.json.
            firebase_creds_env = os.environ.get("FIREBASE_CREDENTIALS")
            if firebase_creds_env:
                cred_dict = json.loads(firebase_creds_env)
                cred = credentials.Certificate(cred_dict)
            else:
                # Fallback to local file for local development only (never commit this file)
                logger.warning("FIREBASE_CREDENTIALS env var not set. Falling back to serviceAccountKey.json.")
                cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
            logger.info("Firebase initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            sys.exit(1)
    return firestore.client()

# Initialize database
db = initialize_firebase()

# ----------------------
# Authentication Decorators
# ----------------------
def login_required(view):
    """Decorator to require login for certain routes"""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    """Decorator to require admin privileges"""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "info")
            return redirect(url_for("login"))
        if session.get("user_role") != "admin":
            flash("Access denied. Admin privileges required.", "danger")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped

# ----------------------
# Helper Functions
# ----------------------
def parse_timestamp(ts):
    """Safely parse timestamps from various formats - FIXED VERSION"""
    if ts is None:
        return None

    # Firestore timestamp type
    if hasattr(ts, 'to_datetime'):
        return ts.to_datetime()  # Already offset-aware

    # Python datetime object
    if isinstance(ts, datetime):
        # Always ensure timezone info
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    # Parse ISO datetime string, assuming UTC if no tzinfo
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    return None

def safe_get_user_doc(user_id):
    """Safely get user document from Firestore"""
    try:
        user_doc = db.collection("users").document(user_id).get()
        if user_doc.exists:
            return user_doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return None

def safe_subprocess_call(cmd, timeout=120):
    """Safely execute subprocess with timeout - FIXED TO 120 SECONDS"""
    try:
        result = subprocess.run(cmd, cwd=os.getcwd(), timeout=timeout,
                              capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Subprocess failed (code {result.returncode}): {result.stderr}")
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"Subprocess timeout: {cmd}")
        return False, "", "Process timed out"
    except Exception as e:
        logger.error(f"Subprocess error: {e}")
        return False, "", str(e)

# ----------------------
# Gamification Functions
# ----------------------
def calculate_user_points(user_id):
    """Calculate total points for a user based on their exercises"""
    try:
        exercises_ref = db.collection("users").document(user_id).collection("exercises")
        exercises = exercises_ref.stream()
        total_points = 0

        for exercise in exercises:
            data = exercise.to_dict()
            exercise_type = data.get("type", "")

            if exercise_type == "vertical-jump":
                points = data.get("jump_height_cm", 0) * 2
            elif exercise_type == "broad-jump":
                points = data.get("score", 0)
            elif exercise_type in ["standing-start", "shuttle-run", "800m-run"]:
                points = data.get("score", 0) * 10
            elif exercise_type == "medicine-ball":
                points = data.get("score", 0) / 10 * 10
            else:
                points = data.get("count", 0) * 5

            total_points += points

        return int(total_points)
    except Exception as e:
        logger.error(f"Error calculating points for user {user_id}: {e}")
        return 0

def get_user_badges(user_id):
    """Get badges earned by a user"""
    try:
        badges = []
        exercises_ref = db.collection("users").document(user_id).collection("exercises")
        exercises = exercises_ref.stream()

        exercise_counts = {}
        max_scores = {}

        for exercise in exercises:
            data = exercise.to_dict()
            exercise_type = data.get("type", "")

            if exercise_type not in exercise_counts:
                exercise_counts[exercise_type] = 0
                max_scores[exercise_type] = 0

            exercise_counts[exercise_type] += 1

            if exercise_type == "vertical-jump":
                max_scores[exercise_type] = max(max_scores[exercise_type],
                                               data.get("jump_height_cm", 0))
            elif exercise_type == "broad-jump":
                max_scores[exercise_type] = max(max_scores[exercise_type],
                                               data.get("score", 0))
            elif exercise_type in ["standing-start", "shuttle-run", "800m-run"]:
                max_scores[exercise_type] = max(max_scores[exercise_type],
                                               data.get("score", 0))
            elif exercise_type == "medicine-ball":
                max_scores[exercise_type] = max(max_scores[exercise_type],
                                               data.get("score", 0))
            else:
                max_scores[exercise_type] = max(max_scores[exercise_type],
                                               data.get("count", 0))

        # Award badges based on exercise counts
        for exercise_type, count in exercise_counts.items():
            exercise_name = exercise_type.replace('-', ' ').title()
            if count >= 10:
                badges.append(f"{exercise_name} Champion")
            if count >= 50:
                badges.append(f"{exercise_name} Master")

        # Award badges based on performance
        for exercise_type, max_val in max_scores.items():
            exercise_name = exercise_type.replace('-', ' ').title()
            if exercise_type == "vertical-jump" and max_val > 50:
                badges.append("High Jumper")
            elif exercise_type == "broad-jump" and max_val > 70:
                badges.append("Long Jumper")
            elif exercise_type == "medicine-ball" and max_val > 80:
                badges.append("Power Thrower")
            elif exercise_type in ["standing-start", "shuttle-run", "800m-run"] and max_val > 8:
                badges.append(f"{exercise_name} Pro")
            elif exercise_type not in ["vertical-jump", "broad-jump", "standing-start",
                                     "shuttle-run", "800m-run", "medicine-ball"] and max_val > 50:
                badges.append(f"{exercise_name} Pro")

        return badges
    except Exception as e:
        logger.error(f"Error getting badges for user {user_id}: {e}")
        return []

def get_user_streak(user_id):
    """Calculate user's current streak of consecutive exercise days"""
    try:
        exercises_ref = db.collection("users").document(user_id).collection("exercises")
        exercises = exercises_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).stream()

        dates = set()
        for exercise in exercises:
            data = exercise.to_dict()
            timestamp = data.get("timestamp")
            if timestamp:
                parsed_ts = parse_timestamp(timestamp)
                if parsed_ts:
                    dates.add(parsed_ts.date())

        if not dates:
            return 0

        sorted_dates = sorted(dates, reverse=True)
        streak = 0
        expected_date = datetime.now().date()

        for date in sorted_dates:
            if date == expected_date:
                streak += 1
                expected_date -= timedelta(days=1)
            elif date < expected_date:
                break

        return streak
    except Exception as e:
        logger.error(f"Error calculating streak for user {user_id}: {e}")
        return 0

def get_user_exercises(user_id):
    """Get detailed exercise data for a user"""
    try:
        exercises_ref = db.collection("users").document(user_id).collection("exercises")
        exercises = exercises_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).stream()

        exercise_data = []
        for exercise in exercises:
            data = exercise.to_dict()
            exercise_type = data.get("type", "")

            exercise_info = {
                "type": exercise_type.replace("-", " ").title(),
                "timestamp": parse_timestamp(data.get("timestamp")),
                "count": data.get("count", 0)
            }

            if exercise_type in ["vertical-jump", "broad-jump"]:
                exercise_info["score"] = data.get("score", 0)
                if exercise_type == "vertical-jump":
                    exercise_info["jump_height"] = data.get("jump_height_cm", 0)
            elif exercise_type in ["standing-start", "shuttle-run", "800m-run"]:
                exercise_info["score"] = data.get("score", 0)
                exercise_info["time"] = data.get("time", 0)
            elif exercise_type == "medicine-ball":
                exercise_info["score"] = data.get("score", 0)
            else:
                exercise_info["score"] = data.get("count", 0) * 5

            exercise_data.append(exercise_info)

        return exercise_data
    except Exception as e:
        logger.error(f"Error getting exercises for user {user_id}: {e}")
        return []

# ----------------------
# Exercise Processing Functions
# ----------------------
def save_exercise_score(user_id, exercise_type, **kwargs):
    """Save exercise score to Firebase with proper error handling"""
    try:
        exercise_ref = db.collection('users').document(user_id).collection('exercises').document()

        base_data = {
            'type': exercise_type,
            'timestamp': firestore.SERVER_TIMESTAMP
        }

        base_data.update(kwargs)
        exercise_ref.set(base_data)
        logger.info(f"Saved {exercise_type} score for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving {exercise_type} score for user {user_id}: {e}")
        return False

def process_exercise_video(exercise_type, video_path, user_id):
    """Process exercise video and save results"""
    try:
        ex_type_norm = exercise_type.replace(' ', '-')

        if ex_type_norm == 'vertical-jump':
            try:
                from vertical_jump import run
                jump_score, jump_count = run(video_path)
                success = save_exercise_score(user_id, 'vertical-jump',
                                            jump_height_cm=jump_score, count=jump_count, score=jump_score)
                return success, f"Vertical Jump: Score {int(jump_score)}, Jumps: {jump_count}"
            except ImportError:
                logger.error("vertical_jump module not found")
                return False, "Vertical jump processing not available"

        elif ex_type_norm == 'broad-jump':
            try:
                from broad_jump import run
                score, count = run(video_path)
                success = save_exercise_score(user_id, 'broad-jump',
                                            score=score, count=count)
                return success, f"Broad Jump: Score {score:.1f}, Jumps: {count}"
            except ImportError:
                logger.error("broad_jump module not found")
                return False, "Broad jump processing not available"

        elif ex_type_norm == 'standing-start':
            try:
                from standing_start import run
                score, attempts, run_time = run(video_path)
                success = save_exercise_score(user_id, 'standing-start',
                                            score=score, time=run_time, count=attempts)
                return success, f"Standing Start: Score {score}/10, Time: {run_time:.2f}s"
            except ImportError:
                logger.error("standing_start module not found")
                return False, "Standing start processing not available"

        elif ex_type_norm == 'shuttle-run':
            try:
                from shuttle_run import run
                score, attempts, run_time = run(video_path)
                success = save_exercise_score(user_id, 'shuttle-run',
                                            score=score, time=run_time, count=attempts)
                return success, f"Shuttle Run: Score {score}/10, Time: {run_time:.2f}s"
            except ImportError:
                logger.error("shuttle_run module not found")
                return False, "Shuttle run processing not available"

        elif ex_type_norm == '800m-run':
            try:
                from run_800m import run
                score, attempts, run_time = run(video_path)
                success = save_exercise_score(user_id, '800m-run',
                                            score=score, time=run_time, count=attempts)
                return success, f"800m Run: Score {score}/10, Time: {run_time:.2f}s"
            except ImportError:
                logger.error("run_800m module not found")
                return False, "800m run processing not available"

        elif ex_type_norm == 'medicine-ball':
            try:
                from medicine_throw import run
                score = run(video_path)
                success = save_exercise_score(user_id, 'medicine-ball',
                                            score=score, count=1)
                return success, f"Medicine Ball: Score {score:.1f}/100"
            except ImportError:
                logger.error("medicine_throw module not found")
                return False, "Medicine ball processing not available"

        else:
            # For other exercises, use the general process_video.py approach
            cmd = ["python", "process_video.py", "-t", ex_type_norm, "-u", user_id, "-vs", video_path]
            success, stdout, stderr = safe_subprocess_call(cmd)
            if success:
                return True, f"{ex_type_norm.replace('-', ' ').title()} video processed successfully"
            else:
                logger.error(f"Process video failed: {stderr}")
                return False, f"Failed to process {ex_type_norm} video"

    except Exception as e:
        logger.error(f"Error processing {exercise_type} video: {e}")
        return False, f"Error processing video: {str(e)}"

# ----------------------
# Analytics Functions for SAI Dashboard
# ----------------------
def get_regional_performance_data():
    """Get regional performance statistics"""
    try:
        users_ref = db.collection("users").where("role", "==", "user").stream()
        regional_data = {}
        
        for user_doc in users_ref:
            user_data = user_doc.to_dict()
            user_id = user_doc.id
            location = user_data.get("location", "Unknown")
            
            if location not in regional_data:
                regional_data[location] = {
                    "users": 0,
                    "total_points": 0,
                    "avg_points": 0,
                    "total_exercises": 0
                }
            
            regional_data[location]["users"] += 1
            points = calculate_user_points(user_id)
            regional_data[location]["total_points"] += points
            
            # Count exercises
            exercises_ref = db.collection("users").document(user_id).collection("exercises")
            exercise_count = len(list(exercises_ref.stream()))
            regional_data[location]["total_exercises"] += exercise_count
        
        # Calculate averages
        for region in regional_data:
            if regional_data[region]["users"] > 0:
                regional_data[region]["avg_points"] = regional_data[region]["total_points"] / regional_data[region]["users"]
        
        return regional_data
    except Exception as e:
        logger.error(f"Error getting regional data: {e}")
        return {}

def get_exercise_popularity_data():
    """Get exercise popularity statistics"""
    try:
        exercises_ref = db.collection_group('exercises')
        exercises = exercises_ref.stream()
        
        exercise_counts = {}
        for exercise in exercises:
            data = exercise.to_dict()
            exercise_type = data.get("type", "unknown")
            exercise_counts[exercise_type] = exercise_counts.get(exercise_type, 0) + 1
        
        return exercise_counts
    except Exception as e:
        logger.error(f"Error getting exercise popularity: {e}")
        return {}

# ----------------------
# Routes - FIXED ROUTES
# ----------------------
@app.route("/")
def home():
    """Home page - redirect based on user status"""
    if "user_id" in session:
        if session.get("user_role") == "admin":
            return redirect(url_for("sai_dashboard"))
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    """User registration"""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        age = request.form.get("age")
        gender = request.form.get("gender")
        location = request.form.get("location")
        role = request.form.get("role", "user")
        height = request.form.get("height")
        weight = request.form.get("weight")

        if not (name and email and password):
            flash("Please fill in all required fields", "danger")
            return render_template("register.html")

        try:
            users_ref = db.collection("users")
            existing_users = users_ref.where("email", "==", email).get()

            if existing_users:
                flash("Email already registered", "danger")
                return render_template("register.html")

            hashed_password = generate_password_hash(password)
            doc_ref = users_ref.document()

            user_data = {
                "name": name,
                "email": email,
                "password": hashed_password,
                "role": role,
                "created_at": firestore.SERVER_TIMESTAMP
            }

            if age:
                user_data["age"] = int(age)
            if gender:
                user_data["gender"] = gender
            if location:
                user_data["location"] = location
            if height:
                user_data["height"] = float(height)
            if weight:
                user_data["weight"] = float(weight)

            doc_ref.set(user_data)

            session["user_id"] = doc_ref.id
            session["user_name"] = name
            session["user_role"] = role
            session.permanent = True

            flash("Registration successful!", "success")

            if role == "admin":
                return redirect(url_for("sai_dashboard"))
            return redirect(url_for("dashboard"))

        except Exception as e:
            logger.error(f"Registration error: {e}")
            flash("Registration failed. Please try again.", "danger")

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    """User login"""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        try:
            users_ref = db.collection("users").where("email", "==", email).get()

            if not users_ref:
                flash("Invalid email or password", "danger")
                return render_template("login.html")

            user_doc = users_ref[0]
            user = user_doc.to_dict()

            if check_password_hash(user["password"], password):
                session["user_id"] = user_doc.id
                session["user_name"] = user["name"]
                session["user_role"] = user.get("role", "user")
                session.permanent = True

                flash(f"Welcome back, {user['name']}!", "success")

                if user.get("role") == "admin":
                    return redirect(url_for("sai_dashboard"))
                return redirect(url_for("dashboard"))
            else:
                flash("Invalid email or password", "danger")

        except Exception as e:
            logger.error(f"Login error: {e}")
            flash("Login failed. Please try again.", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    """User logout"""
    name = session.get("user_name", "")
    session.clear()
    if name:
        flash(f"Goodbye, {name}!", "info")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    """User dashboard"""
    if session.get("user_role") == "admin":
        return redirect(url_for("sai_dashboard"))

    username = session["user_name"]
    user_id = session["user_id"]

    points = calculate_user_points(user_id)
    badges = get_user_badges(user_id)
    streak = get_user_streak(user_id)

    try:
        exercises_ref = db.collection("users").document(user_id).collection("exercises")
        recent_exercises = exercises_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(5).stream()

        recent_activities = []
        for exercise in recent_exercises:
            data = exercise.to_dict()
            recent_activities.append({
                "type": data.get("type", "").replace("-", " ").title(),
                "count": data.get("count", data.get("jump_height_cm", data.get("score", 0))),
                "timestamp": parse_timestamp(data.get("timestamp"))
            })
    except Exception as e:
        logger.error(f"Error getting recent activities: {e}")
        recent_activities = []

    return render_template("dashboard.html",
                         username=username,
                         points=points,
                         badges=badges,
                         streak=streak,
                         recent_activities=recent_activities)

@app.route('/sai_dashboard')
@admin_required
def sai_dashboard():
    """SAI admin dashboard"""
    try:
        today = datetime.combine(datetime.now().date(), time.min).replace(tzinfo=timezone.utc)

        all_exercises = db.collection_group('exercises').stream()
        today_exercises = []

        for ex in all_exercises:
            data = ex.to_dict()
            ts = parse_timestamp(data.get('timestamp'))
            if ts and ts >= today:
                today_exercises.append(ex)

        exercise_counts = {}
        active_users = set()
        total_exercise_count = 0

        for ex in today_exercises:
            data = ex.to_dict()
            exercise_type = data.get('type', '')

            active_users.add(ex.reference.parent.parent.id)
            exercise_counts[exercise_type] = exercise_counts.get(exercise_type, 0) + 1

            if data.get('type') not in ['vertical-jump', 'broad-jump']:
                total_exercise_count += data.get('count', 0)

        daily_stats = {
            "total_sessions": len(today_exercises),
            "total_exercises": total_exercise_count,
            "active_users": len(active_users),
            "target": max(exercise_counts, key=exercise_counts.get).replace('-', ' ').title() if exercise_counts else "No Activity"
        }

        users_ref = db.collection("users").where("role", "==", "user").stream()
        user_points = []

        for user_doc in users_ref:
            user_data = user_doc.to_dict()
            user_id = user_doc.id

            points = calculate_user_points(user_id)
            badges = get_user_badges(user_id)
            streak = get_user_streak(user_id)

            user_points.append({
                "user_id": user_id,
                "name": user_data.get("name", "Anonymous"),
                "points": points,
                "badges": len(badges),
                "streak": streak,
                "location": user_data.get("location", "Unknown"),
                "age": user_data.get("age", "N/A"),
                "gender": user_data.get("gender", "N/A"),
                "email": user_data.get("email", "N/A")
            })

        top_users = sorted(user_points, key=lambda x: x["points"], reverse=True)[:10]

        regional_data = get_regional_performance_data()
        exercise_popularity = get_exercise_popularity_data()

        return render_template("sai_dashboard.html",
                             top_users=top_users,
                             daily_stats=daily_stats,
                             regional_data=regional_data,
                             exercise_popularity=exercise_popularity,
                             username=session["user_name"])

    except Exception as e:
        logger.error(f"Error in sai_dashboard: {e}")
        return render_template("sai_dashboard.html",
                             top_users=[],
                             daily_stats={"total_sessions": 0, "total_exercises": 0,
                                        "target": "Error", "active_users": 0},
                             regional_data={},
                             exercise_popularity={},
                             username=session["user_name"])

# FIXED ROUTE: Removed extra slash and parameter
@app.route("/api/user_details/<user_id>")
@admin_required
def get_user_details(user_id):
    """API endpoint to get user details and exercises for the modal"""
    try:
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400

        user_doc = db.collection("users").document(user_id).get()

        if not user_doc.exists:
            return jsonify({"error": "User not found"}), 404

        user_data = user_doc.to_dict()
        exercises = get_user_exercises(user_id)

        points = calculate_user_points(user_id)
        badges = get_user_badges(user_id)
        streak = get_user_streak(user_id)

        return jsonify({
            "name": user_data.get("name", "Anonymous"),
            "email": user_data.get("email", "N/A"),
            "age": user_data.get("age", "N/A"),
            "gender": user_data.get("gender", "N/A"),
            "location": user_data.get("location", "Unknown"),
            "points": points,
            "badges": badges,
            "streak": streak,
            "level": (points // 1000) + 1,
            "exercises": exercises
        })

    except Exception as e:
        logger.error(f"Error getting user details for {user_id}: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to get user details"}), 500

# FIXED ROUTE: Added missing chart data endpoint
@app.route("/api/chart_data/<chart_type>")
@admin_required
def get_chart_data(chart_type):
    """API endpoint for real-time chart data"""
    try:
        if chart_type == "exercise_popularity":
            data = get_exercise_popularity_data()
            return jsonify(data)
        elif chart_type == "regional_performance":
            data = get_regional_performance_data()
            return jsonify(data)
        else:
            return jsonify({"error": "Unknown chart type"}), 400
    except Exception as e:
        logger.error(f"Error getting chart data: {e}")
        return jsonify({"error": "Failed to get chart data"}), 500

@app.route("/leaderboard")
@login_required
def leaderboard():
    """Public leaderboard"""
    try:
        users_ref = db.collection("users").where("role", "==", "user").stream()
        board = []

        for user_doc in users_ref:
            user_data = user_doc.to_dict()
            user_id = user_doc.id

            points = calculate_user_points(user_id)
            badges = get_user_badges(user_id)
            streak = get_user_streak(user_id)

            board.append({
                "name": user_data.get("name", "Anonymous"),
                "points": points,
                "badges": len(badges),
                "streak": streak,
                "location": user_data.get("location", "Unknown"),
            })

        board.sort(key=lambda x: x["points"], reverse=True)

        stats = {
            "total_athletes": len(board),
            "highest_points": board[0]["points"] if board else 0,
            "longest_streak": max((user["streak"] for user in board), default=0),
            "most_badges": max((user["badges"] for user in board), default=0)
        }

        return render_template("leaderboard.html", board=board, stats=stats)

    except Exception as e:
        logger.error(f"Error in leaderboard: {e}")
        return render_template("leaderboard.html",
                             board=[],
                             stats={"total_athletes": 0, "highest_points": 0,
                                   "longest_streak": 0, "most_badges": 0})

# FIX #4: Whitelist of allowed exercise types to prevent command injection
ALLOWED_EXERCISE_TYPES = {
    "vertical-jump", "broad-jump", "standing-start",
    "shuttle-run", "800m-run", "medicine-ball",
    "sit-up", "pull-up", "push-up", "squat", "walk"
}

# FIXED ROUTE: Proper parameter handling for exercise types
@app.route("/start_exercise/<exercise_type>")
@login_required
def start_exercise(exercise_type):
    # FIX #4: Validate exercise type against whitelist before passing to subprocess
    ex_type_norm = exercise_type.replace(' ', '-')
    if ex_type_norm not in ALLOWED_EXERCISE_TYPES:
        flash("Invalid exercise type.", "danger")
        return redirect(url_for("dashboard"))

    user_id = session["user_id"]

    try:
        # Run cheat detection first
        cheat_result = subprocess.run(["python", "live_cheat.py"], cwd=os.getcwd())
        if cheat_result.returncode != 0:
            flash("Cheat detection failed! Please follow liveness prompts.", "danger")
            return redirect(url_for("dashboard"))

        # Start the appropriate exercise command
        if ex_type_norm == "medicine-ball":
            exercise_cmd = ["python", "medicine_throw.py", "-u", user_id]
        else:
            exercise_cmd = ["python", "main.py", "-t", ex_type_norm, "-u", user_id]

        # Start the exercise process asynchronously
        subprocess.Popen(exercise_cmd, cwd=os.getcwd())
        flash(f"{ex_type_norm.replace('-', ' ').title()} exercise started successfully!", "success")

    except Exception as e:
        print(f"Failed to start exercise {ex_type_norm}: {e}")
        flash("Failed to start exercise. Please try again.", "danger")

    return redirect(url_for("dashboard"))

# FIXED ROUTE: Proper parameter handling for video uploads
@app.route("/upload_exercise/<exercise_type>", methods=["POST"])
@login_required
def upload_exercise(exercise_type):
    """Upload and process exercise video - FIXED ROUTE"""
    # FIX #4: Validate exercise type against whitelist
    ex_type_norm = exercise_type.replace(' ', '-')
    if ex_type_norm not in ALLOWED_EXERCISE_TYPES:
        flash("Invalid exercise type.", "danger")
        return redirect(url_for("dashboard"))

    if "exercise_video" not in request.files:
        flash("No video file uploaded", "danger")
        return redirect(url_for("dashboard"))

    video_file = request.files["exercise_video"]

    if video_file.filename == "":
        flash("No file selected", "danger")
        return redirect(url_for("dashboard"))

    try:
        save_dir = os.path.join("uploads")
        os.makedirs(save_dir, exist_ok=True)

        # FIX #3: Use secure_filename to prevent path traversal attacks
        safe_name = secure_filename(video_file.filename)
        if not safe_name:
            flash("Invalid filename.", "danger")
            return redirect(url_for("dashboard"))

        save_path = os.path.join(save_dir, safe_name)
        video_file.save(save_path)

        user_id = session["user_id"]

        success, message = process_exercise_video(exercise_type, save_path, user_id)

        if success:
            flash(message, "success")
        else:
            flash(f"Error: {message}", "danger")

        try:
            if os.path.exists(save_path):
                os.remove(save_path)
        except Exception as e:
            logger.warning(f"Failed to remove uploaded file: {e}")

    except Exception as e:
        logger.error(f"Failed to process {exercise_type} video: {e}")
        flash("Failed to process video. Please try again.", "danger")

    return redirect(url_for("dashboard"))

@app.route('/api/export_report')
@admin_required
def export_report():
    """Export detailed CSV report"""
    try:
        output = io.StringIO()
        writer = csv.writer(output)

        # Enhanced header with all exercise details
        headers = ['Rank', 'Name', 'Location', 'Age', 'Gender', 'Email', 'Points', 'Level', 'Badges', 'Streak']

        # Add exercise-specific headers - ADDED MEDICINE BALL
        exercise_types = ['vertical-jump', 'broad-jump', 'standing-start', 'shuttle-run',
                         '800m-run', 'medicine-ball', 'sit-up', 'pull-up', 'push-up', 'squat', 'walk']

        for ex_type in exercise_types:
            headers.extend([f'{ex_type.replace("-", " ").title()} Count',
                           f'{ex_type.replace("-", " ").title()} Best Score'])

        writer.writerow(headers)

        # Get all users
        users_ref = db.collection("users").where("role", "==", "user").stream()
        users_list = []

        for user_doc in users_ref:
            user_data = user_doc.to_dict()
            user_id = user_doc.id

            points = calculate_user_points(user_id)
            badges = get_user_badges(user_id)
            streak = get_user_streak(user_id)

            # Get exercise details
            exercises = get_user_exercises(user_id)
            exercise_stats = {}

            for exercise in exercises:
                ex_type = exercise.get('type', '').lower().replace(' ', '-')
                if ex_type not in exercise_stats:
                    exercise_stats[ex_type] = {'count': 0, 'best_score': 0}

                exercise_stats[ex_type]['count'] += 1
                current_score = exercise.get('score', 0)

                if current_score > exercise_stats[ex_type]['best_score']:
                    exercise_stats[ex_type]['best_score'] = current_score

            user_row = {
                'name': user_data.get('name', 'Anonymous'),
                'location': user_data.get('location', 'Unknown'),
                'age': user_data.get('age', 'N/A'),
                'gender': user_data.get('gender', 'N/A'),
                'email': user_data.get('email', 'N/A'),
                'points': points,
                'level': (points // 1000) + 1,
                'badges': len(badges),
                'streak': streak,
                'exercise_stats': exercise_stats
            }

            users_list.append(user_row)

        # Sort by points
        users_list.sort(key=lambda x: x['points'], reverse=True)

        # Write user data
        for rank, user in enumerate(users_list, start=1):
            row = [
                rank, user['name'], user['location'], user['age'],
                user['gender'], user['email'], user['points'],
                user['level'], user['badges'], user['streak']
            ]

            # Add exercise data
            for ex_type in exercise_types:
                stats = user['exercise_stats'].get(ex_type, {'count': 0, 'best_score': 0})
                row.extend([stats['count'], stats['best_score']])

            writer.writerow(row)

        output.seek(0)

        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=detailed_leaderboard_report.csv'

        return response

    except Exception as e:
        logger.error(f"Error generating CSV report: {e}")
        flash('Failed to generate export report', 'danger')
        return redirect(url_for('sai_dashboard'))

@app.route('/export_report_pdf')
@admin_required
def export_report_pdf():
    """Export detailed PDF report"""
    if not PDF_AVAILABLE:
        flash('PDF generation not available. Please install ReportLab.', 'danger')
        return redirect(url_for('sai_dashboard'))

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                               leftMargin=10, rightMargin=10,
                               topMargin=15, bottomMargin=15)

        # Create table headers
        headers = ['Rank', 'Name', 'Email', 'Age', 'Gender', 'Location']
        codes = ['VJ', 'BJ', 'SS', 'SR', '800', 'MB', 'SU', 'PU', 'PS', 'SQ', 'WK']  # ADDED MB for Medicine Ball
        headers.extend(codes)

        data = [headers]

        # Map exercise types to codes - ADDED MEDICINE BALL
        normalized_code_map = {
            'verticaljump': 'VJ', 'broadjump': 'BJ', 'standingstart': 'SS',
            'shuttlerun': 'SR', '800mrun': '800', 'medicineball': 'MB',
            'situp': 'SU', 'pullup': 'PU', 'pushup': 'PS', 'squat': 'SQ', 'walk': 'WK'
        }

        # Get user data
        users = list(db.collection('users').where('role', '==', 'user').stream())
        rows = []

        for i, user_doc in enumerate(users, 1):
            user_id = user_doc.id
            user_info = user_doc.to_dict()

            # Initialize exercise stats
            exercise_stats = {code: {'count': 0, 'score': 0} for code in codes}

            # Get exercises for this user
            exercises = get_user_exercises(user_id)

            for ex in exercises:
                ex_type_norm = ex.get('type', '').lower().replace('-', '').replace(' ', '')
                code = normalized_code_map.get(ex_type_norm)

                if code:
                    count = ex.get('count', 0)
                    score = ex.get('score', 0) or ex.get('jump_height', 0)

                    if isinstance(score, float):
                        score = round(score, 1)

                    exercise_stats[code]['count'] += count
                    if score > exercise_stats[code]['score']:
                        exercise_stats[code]['score'] = score

            # Create row
            row = [
                i,
                user_info.get('name', ''),
                user_info.get('email', ''),
                user_info.get('age', ''),
                user_info.get('gender', ''),
                user_info.get('location', '')
            ]

            # Add exercise data
            for code in codes:
                count = exercise_stats[code]['count']
                score = exercise_stats[code]['score']
                val = f"{count} / {score}" if (count or score) else ''
                row.append(val)

            rows.append(row)

        data.extend(rows)

        # Create table
        styles = getSampleStyleSheet()
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.black)
        ])

        col_widths = [25, 75, 90, 30, 30, 50] + [40] * len(codes)
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(table_style)

        # Build document
        elements = [
            Paragraph("Detailed Athlete Performance Report", styles['Title']),
            Spacer(1, 12),
            table
        ]

        doc.build(elements)
        buffer.seek(0)

        return send_file(buffer, as_attachment=True,
                        download_name="detailed_athlete_report.pdf",
                        mimetype="application/pdf")

    except Exception as e:
        logger.error(f"Error generating PDF report: {e}")
        traceback.print_exc()
        flash('Failed to generate PDF report.', 'danger')
        return redirect(url_for('sai_dashboard'))

# ----------------------
# Error Handlers
# ----------------------
@app.errorhandler(404)
def not_found_error(error):
    return f"<h1>404 - Page Not Found</h1><p>The requested page was not found.</p>", 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return f"<h1>500 - Internal Server Error</h1><p>Something went wrong on our side.</p>", 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}")
    traceback.print_exc()
    if app.debug:
        raise e
    return f"<h1>Error</h1><p>An unexpected error occurred.</p>", 500

def calculate_exercise_points(exercise_type, data):
    try:
        if exercise_type == 'vertical-jump':
            return data.get('jumpHeightCm', 0) * 2
        elif exercise_type == 'broad-jump':
            return data.get('score', 0)
        elif exercise_type in ['standing-start', 'shuttle-run', '800m-run']:
            return data.get('score', 0) * 10
        elif exercise_type == 'medicine-ball':
            return (data.get('score', 0) * 10) + 10
        else:
            return data.get('count', 0) * 5
    except Exception:
        return 0

@app.route('/personal_dashboard')
@login_required
def personal_dashboard():
    userid = session.get('user_id')
    username = session.get('user_name', 'User')

    if not userid:
        flash("Please log in to access your personal dashboard.", "warning")
        return redirect(url_for('login'))

    points = calculate_user_points(userid)
    badges = get_user_badges(userid) or []
    streak = get_user_streak(userid)
    level = (points // 1000) + 1

    recentactivities = []
    exercises_ref = (
        db.collection('users')
          .document(userid)
          .collection('exercises')
          .order_by('timestamp', direction=firestore.Query.DESCENDING)
          .limit(50)
    )
    for doc in exercises_ref.stream():
        data = doc.to_dict()
        try:
            ts = parse_timestamp(data.get('timestamp'))
        except:
            ts = None
        ex_type = data.get('type', 'Unknown').replace('-', ' ').title()
        try:
            pts = calculate_exercise_points(data.get('type'), data)
        except:
            pts = 0
        recentactivities.append({'exercise': ex_type, 'points': pts, 'timestamp': ts})

    record_map = {}
    for doc in db.collection('users').document(userid).collection('exercises').stream():
        data = doc.to_dict()
        name = data.get('type', 'Unknown').replace('-', ' ').title()
        try:
            pts = calculate_exercise_points(data.get('type'), data)
        except:
            pts = 0
        record_map[name] = max(record_map.get(name, 0), pts)
    personalrecords = [{'name': k, 'record': v} for k, v in record_map.items()]

    userstats = {
        'points': points,
        'badgescount': len(badges),
        'streak': streak,
        'level': level
    }

    return render_template(
        'personal_dashboard.html',
        username=username,
        userstats=userstats,
        badges=badges,
        recentactivities=recentactivities,
        personal_records=personalrecords
    )

# CSV export route
@app.route('/export_personal_report')
@login_required
def export_personal_report():
    userid = session.get('user_id')
    username = session.get('user_name', 'User')

    exercises_ref = db.collection('users').document(userid).collection('exercises')
    exercises = exercises_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).stream()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Personal Summary'])
    writer.writerow(['Username', username])
    writer.writerow(['Total Points', calculate_user_points(userid)])
    writer.writerow(['Badges Earned', len(get_user_badges(userid))])
    writer.writerow(['Current Streak', f'{get_user_streak(userid)} days'])
    writer.writerow([])

    writer.writerow(['Exercise History'])
    writer.writerow(['Date', 'Exercise Type', 'Score', 'Count'])

    for exercise in exercises:
        data = exercise.to_dict()
        exercise_type = data.get('type', '').replace('-', ' ').title()
        timestamp = parse_timestamp(data.get('timestamp'))
        date_str = timestamp.strftime('%Y-%m-%d %H:%M') if timestamp else 'N/A'
        score = data.get('score', data.get('jumpHeightCm', data.get('count', 0)))
        count = data.get('count', 1)
        writer.writerow([date_str, exercise_type, score, count])

    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={username}_personal_report.csv'
    return response

# Register strftime filter for Jinja2 — single definition (FIX #1: removed duplicate)
@app.template_filter('strftime')
def _jinja2_filter_datetime(dt, fmt=None):
    if dt is None:
        return ''
    if isinstance(dt, (int, float)):
        dt = datetime.fromtimestamp(dt)
    elif isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    if not fmt:
        fmt = '%Y-%m-%d'
    return dt.strftime(fmt)

@app.route('/events')
@login_required
def events():
    """Display upcoming events from events.json file"""
    username = session.get('user_name', 'User')
    
    # Read events from JSON file
    events_file_path = os.path.join(os.path.dirname(__file__), 'events.json')
    events = []
    
    try:
        if os.path.exists(events_file_path):
            with open(events_file_path, 'r') as f:
                events_data = json.load(f)
                events = events_data.get('events', [])
    except Exception as e:
        flash(f'Error loading events: {str(e)}', 'error')
        events = []
    
    # Sort events by date (upcoming first)
    current_date = datetime.now().strftime('%Y-%m-%d')
    upcoming_events = [e for e in events if e.get('date', '') >= current_date]
    past_events = [e for e in events if e.get('date', '') < current_date]
    
    upcoming_events.sort(key=lambda x: x.get('date', ''))
    past_events.sort(key=lambda x: x.get('date', ''), reverse=True)
    
    return render_template('events.html', 
                         username=username,
                         upcoming_events=upcoming_events,
                         past_events=past_events)

# ----------------------
# Main Application
# ----------------------
if __name__ == "__main__":
    os.makedirs("uploads", exist_ok=True)

    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"

    app.run(host="0.0.0.0", port=port, debug=debug)