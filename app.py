from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_dance.contrib.google import make_google_blueprint, google
from datetime import datetime
import sqlite3

app = Flask(__name__)
app.secret_key = "supersecretkey"  # Change this to a real secret key in production

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quiz.db'  # SQLite database for storing users and scores
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Google OAuth configuration
google_bp = make_google_blueprint(client_id="YOUR_GOOGLE_CLIENT_ID", client_secret="YOUR_GOOGLE_CLIENT_SECRET", redirect_to="google_login")
app.register_blueprint(google_bp, url_prefix="/login")

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(256), unique=True, nullable=False)
    email = db.Column(db.String(256), unique=True, nullable=False)
    scores = db.relationship('Score', backref='user', lazy=True)

class Score(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    score = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(1), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# Database helper function to fetch questions by category
def get_questions(category, limit=10):
    try:
        conn = sqlite3.connect('quiz.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM questions WHERE category = ? ORDER BY RANDOM() LIMIT ?", (category, limit))
        rows = cursor.fetchall()
        conn.close()

        # Format questions into a list of dictionaries
        questions = []
        for row in rows:
            questions.append({
                "id": row[0],
                "category": row[1],
                "question_text": row[2],
                "options": [row[3], row[4], row[5], row[6]],
                "correct_option": row[7]
            })
        return questions
    except Exception as e:
        return {"error": str(e)}

# Google OAuth route
@app.route("/google_login")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))
    
    # Fetch user info from Google
    resp = google.get("/plus/v1/people/me")
    if resp.ok:
        google_info = resp.json()
        google_id = google_info["id"]
        email = google_info["emails"][0]["value"]

        # Check if the user exists, if not, create a new user
        user = User.query.filter_by(google_id=google_id).first()
        if not user:
            user = User(google_id=google_id, email=email)
            db.session.add(user)
            db.session.commit()

        # Store user ID in session
        session["user_id"] = user.id
        return redirect(url_for('home'))
    return jsonify({"error": "Google login failed"}), 400

# Homepage route
@app.route('/')
def home():
    if "user_id" not in session:
        return redirect(url_for('google_login'))
    return render_template('index.html')  # Serve the HTML page

# Fetch questions based on category
@app.route('/get_questions', methods=['GET'])
def fetch_questions():
    category = request.args.get('category', 'C')  # Default to Category C
    questions = get_questions(category)
    
    if "error" in questions:
        return jsonify({"error": questions["error"]}), 500

    return jsonify(questions)

# Submit answers and calculate score
@app.route('/submit_answers', methods=['POST'])
def submit_answers():
    if "user_id" not in session:
        return jsonify({"error": "User not logged in"}), 403
    
    data = request.json
    user_answers = data.get('answers', [])
    category = data.get('category', 'C')

    if not user_answers:
        return jsonify({"error": "No answers submitted"}), 400

    score = 0
    for answer in user_answers:
        question_id = answer.get('question_id')
        selected_option = answer.get('selected_option')

        if not question_id or not selected_option:
            return jsonify({"error": "Invalid answer format"}), 400
        
        # Verify the answer from the database
        conn = sqlite3.connect('quiz.db')
        cursor = conn.cursor()
        cursor.execute("SELECT correct_option FROM questions WHERE id = ?", (question_id,))
        correct_option = cursor.fetchone()
        conn.close()

        if correct_option:
            correct_option = correct_option[0]
            if selected_option == correct_option:
                score += 1
        else:
            return jsonify({"error": f"Question {question_id} not found"}), 404

    # Get the user from the session
    user = User.query.get(session["user_id"])

    # Save score in the database
    new_score = Score(score=score, category=category, user_id=user.id)
    db.session.add(new_score)
    db.session.commit()

    # Adjust difficulty based on score
    if score >= 8:
        next_category = 'C'
    elif score >= 5:
        next_category = category  # Stay in the current category
    else:
        next_category = 'A'

    return jsonify({"score": score, "next_category": next_category})

# Endpoint to fetch score history
@app.route("/score_history")
def score_history():
    if "user_id" not in session:
        return jsonify({"error": "User not logged in"}), 403

    user = User.query.get(session["user_id"])
    scores = Score.query.filter_by(user_id=user.id).all()
    return jsonify([
        {"score": score.score, "category": score.category, "date": score.date} 
        for score in scores
    ])

if __name__ == '__main__':
    # Wrap the db.create_all() call inside an app context
    with app.app_context():
        db.create_all()  # Create tables based on the defined models
    
    app.run(debug=True)