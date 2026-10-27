import hmac
import os
import re
import secrets
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


PLACES = (
    ("quad-cafe", "The Quad Cafe", "Cafe", "Coffee, sandwiches, and a sunny study patio.", "$$", "North Quad"),
    ("wok-and-roll", "Wok & Roll", "Asian", "Build-your-own noodle bowls with quick, generous portions.", "$$", "Student Union"),
    ("green-bowl", "Green Bowl Kitchen", "Healthy", "Fresh grain bowls, crisp vegetables, and house-made dressings.", "$$", "Maple Avenue"),
    ("brick-oven", "Brick Oven Pizza", "Pizza", "Thin-crust slices and classic pies baked to order.", "$", "College Street"),
    ("sunrise-diner", "Sunrise Diner", "Breakfast", "All-day breakfast plates, pancakes, and bottomless coffee.", "$", "Oak Hall"),
    ("taco-garden", "Taco Garden", "Mexican", "Street-style tacos with vegetarian and spicy options.", "$$", "Market Walk"),
)

SAMPLE_REVIEWS = (
    ("maya", "Maya", "quad-cafe", 5, "The patio is lovely and the tomato toast is my go-to between classes."),
    ("leo", "Leo", "quad-cafe", 4, "Great coffee and friendly staff. It gets busy at lunchtime."),
    ("maya", "Maya", "wok-and-roll", 4, "Fast, filling, and easy to customize. The chili oil is excellent."),
    ("noah", "Noah", "wok-and-roll", 5, "Big portions for the price. I keep coming back for the sesame noodles."),
    ("leo", "Leo", "green-bowl", 5, "Fresh ingredients and plenty of options. The lemon dressing is a favorite."),
    ("ava", "Ava", "green-bowl", 4, "A nice lighter lunch, and the portions are still satisfying."),
    ("noah", "Noah", "brick-oven", 4, "Good crispy crust and quick slices when I'm in a hurry."),
    ("ava", "Ava", "brick-oven", 5, "The roasted mushroom pizza is fantastic. Great value, too."),
    ("maya", "Maya", "sunrise-diner", 4, "Comforting breakfast and very generous pancakes."),
    ("leo", "Leo", "sunrise-diner", 3, "Solid diner food. The weekend wait can be a little long."),
    ("noah", "Noah", "taco-garden", 5, "The veggie tacos are packed with flavor and the salsa is fresh."),
    ("ava", "Ava", "taco-garden", 4, "Lots of tasty choices and a good quick dinner near campus."),
)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE_PATH=os.environ.get(
            "DATABASE_PATH", str(Path(app.instance_path) / "campus_bites.db")
        ),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    @app.before_request
    def ensure_csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)

    @app.before_request
    def validate_csrf_token():
        if request.method == "POST":
            submitted = request.form.get("csrf_token", "")
            expected = session.get("_csrf_token", "")
            if not expected or not hmac.compare_digest(submitted, expected):
                abort(400, description="Your form expired. Please try again.")

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with app.app_context():
        init_db()

    @app.context_processor
    def inject_user():
        return {"current_user": get_current_user()}

    @app.get("/")
    def index():
        db = get_db()
        search = request.args.get("q", "").strip()[:80]
        category = request.args.get("category", "").strip()
        query = """
            SELECT p.*,
                   COALESCE(AVG(r.rating), 0) AS average_rating,
                   COUNT(r.id) AS review_count
            FROM places p
            LEFT JOIN reviews r ON r.place_id = p.id
            WHERE 1 = 1
        """
        parameters = []
        if search:
            query += " AND (p.name LIKE ? OR p.description LIKE ? OR p.location LIKE ?)"
            search_term = f"%{search}%"
            parameters.extend((search_term, search_term, search_term))
        if category:
            query += " AND p.category = ?"
            parameters.append(category)
        query += " GROUP BY p.id ORDER BY average_rating DESC, review_count DESC, p.name"
        places = db.execute(query, parameters).fetchall()
        categories = db.execute(
            "SELECT DISTINCT category FROM places ORDER BY category"
        ).fetchall()
        return render_template(
            "index.html",
            places=places,
            categories=categories,
            search=search,
            selected_category=category,
        )

    @app.route("/register", methods=("GET", "POST"))
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            display_name = request.form.get("display_name", "").strip()
            password = request.form.get("password", "")
            error = validate_registration(username, display_name, password)
            if error:
                flash(error, "error")
            else:
                try:
                    get_db().execute(
                        "INSERT INTO users (username, display_name, password_hash) VALUES (?, ?, ?)",
                        (username.lower(), display_name, generate_password_hash(password)),
                    )
                    get_db().commit()
                except sqlite3.IntegrityError:
                    flash("That username is already taken.", "error")
                else:
                    session.clear()
                    session["user_id"] = get_db().execute(
                        "SELECT id FROM users WHERE username = ?", (username.lower(),)
                    ).fetchone()["id"]
                    flash("Your account is ready. Welcome to Campus Bites!", "success")
                    return redirect(url_for("index"))
        return render_template("register.html")

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password):
                flash("Username or password is incorrect.", "error")
            else:
                session.clear()
                session["user_id"] = user["id"]
                flash(f"Welcome back, {user['display_name']}!", "success")
                return redirect(url_for("index"))
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("index"))

    @app.route("/places/<slug>", methods=("GET", "POST"))
    def place_detail(slug):
        db = get_db()
        place = db.execute(
            "SELECT * FROM places WHERE slug = ?", (slug,)
        ).fetchone()
        if place is None:
            abort(404)

        user = get_current_user()
        if request.method == "POST":
            if user is None:
                flash("Log in to leave a review.", "error")
                return redirect(url_for("login"))
            rating_value = request.form.get("rating", "")
            review_text = request.form.get("review", "").strip()
            if rating_value not in {"1", "2", "3", "4", "5"}:
                flash("Choose a rating from 1 to 5 stars.", "error")
            elif len(review_text) < 5 or len(review_text) > 500:
                flash("Your review must be between 5 and 500 characters.", "error")
            else:
                db.execute(
                    """
                    INSERT INTO reviews (user_id, place_id, rating, body)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (user_id, place_id) DO UPDATE SET
                        rating = excluded.rating,
                        body = excluded.body,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user["id"], place["id"], int(rating_value), review_text),
                )
                db.commit()
                flash("Your review has been saved.", "success")
                return redirect(url_for("place_detail", slug=slug))

        my_review = None
        if user is not None:
            my_review = db.execute(
                "SELECT * FROM reviews WHERE user_id = ? AND place_id = ?",
                (user["id"], place["id"]),
            ).fetchone()
        summary = db.execute(
            """
            SELECT COALESCE(AVG(rating), 0) AS average_rating, COUNT(*) AS review_count
            FROM reviews WHERE place_id = ?
            """,
            (place["id"],),
        ).fetchone()
        distribution_rows = db.execute(
            "SELECT rating, COUNT(*) AS count FROM reviews WHERE place_id = ? GROUP BY rating",
            (place["id"],),
        ).fetchall()
        distribution = {row["rating"]: row["count"] for row in distribution_rows}
        reviews = db.execute(
            """
            SELECT r.*, u.username, u.display_name
            FROM reviews r JOIN users u ON u.id = r.user_id
            WHERE r.place_id = ?
            ORDER BY r.updated_at DESC, r.id DESC
            """,
            (place["id"],),
        ).fetchall()
        return render_template(
            "place.html",
            place=place,
            summary=summary,
            distribution=distribution,
            reviews=reviews,
            my_review=my_review,
        )

    @app.get("/people/<username>")
    def profile(username):
        user = get_db().execute(
            "SELECT id, username, display_name FROM users WHERE username = ?",
            (username.lower(),),
        ).fetchone()
        if user is None:
            abort(404)
        reviews = get_db().execute(
            """
            SELECT r.rating, r.body, r.updated_at, p.slug, p.name, p.category
            FROM reviews r JOIN places p ON p.id = r.place_id
            WHERE r.user_id = ?
            ORDER BY r.updated_at DESC, r.id DESC
            """,
            (user["id"],),
        ).fetchall()
        return render_template("profile.html", profile_user=user, reviews=reviews)

    @app.errorhandler(400)
    def bad_request(error):
        return render_template(
            "error.html", code=400, message=error.description or "That request was invalid."
        ), 400

    @app.errorhandler(404)
    def not_found(_error):
        return render_template(
            "error.html", code=404, message="We couldn't find that page or place."
        ), 404

    return app


def validate_registration(username, display_name, password):
    if not re.fullmatch(r"[a-zA-Z0-9_]{3,24}", username):
        return "Username must be 3–24 characters: letters, numbers, or underscores."
    if not display_name or len(display_name) > 40:
        return "Display name must be between 1 and 40 characters."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password) > 128:
        return "Password must be 128 characters or fewer."
    return None


def get_db():
    if "db" not in g:
        database_path = Path(current_app.config["DATABASE_PATH"])
        database_path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(database_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def get_current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_db().execute(
        "SELECT id, username, display_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            price TEXT NOT NULL,
            location TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            body TEXT NOT NULL CHECK (length(body) BETWEEN 5 AND 500),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, place_id)
        );
        """
    )
    db.execute("BEGIN IMMEDIATE")
    if db.execute("SELECT COUNT(*) FROM places").fetchone()[0] == 0:
        db.executemany(
            """
            INSERT OR IGNORE INTO places (slug, name, category, description, price, location)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            PLACES,
        )
        sample_users = (
            ("maya", "Maya Chen"),
            ("leo", "Leo Park"),
            ("noah", "Noah Rivera"),
            ("ava", "Ava Brooks"),
        )
        db.executemany(
            "INSERT OR IGNORE INTO users (username, display_name, password_hash) VALUES (?, ?, ?)",
            [
                (username, display_name, generate_password_hash(secrets.token_urlsafe(24)))
                for username, display_name in sample_users
            ],
        )
        place_ids = {
            row["slug"]: row["id"]
            for row in db.execute("SELECT id, slug FROM places").fetchall()
        }
        user_ids = {
            row["username"]: row["id"]
            for row in db.execute("SELECT id, username FROM users").fetchall()
        }
        db.executemany(
            """
            INSERT OR IGNORE INTO reviews (user_id, place_id, rating, body)
            VALUES (?, ?, ?, ?)
            """,
            [
                (user_ids[username], place_ids[slug], rating, body)
                for username, _display_name, slug, rating, body in SAMPLE_REVIEWS
            ],
        )
    db.commit()


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
