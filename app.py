"""Website version of the meal tracker (Flask).
Uses the SAME tracker.db as meal.py, so users, foods and logs are shared.
Run:  python app.py   then open http://127.0.0.1:5000"""
import sqlite3
import json
import hashlib
import urllib.request
from datetime import date, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, g, jsonify)


# ======================= SETTINGS: change things here =======================
APP_NAME = "My Meal Tracker"
DB_FILE = "tracker.db"
MEALS = ["Breakfast", "Lunch", "Dinner", "Snack"]
DEFAULT_GOALS = {"kcal": 2000, "carbs_g": 250, "protein_g": 100,
                 "fat_g": 70, "water_ml": 2500}
UNITS = {"ml": 1, "cup": 240, "glass": 250, "oz": 29.57, "litre": 1000}
NAMES = {"kcal": "Calories", "carbs_g": "Carbs", "protein_g": "Protein",
         "fat_g": "Fat", "water_ml": "Water"}
SUFFIX = {"kcal": "kcal", "carbs_g": "g", "protein_g": "g", "fat_g": "g", "water_ml": "ml"}
FIELDS = ["barcode", "name", "stock_g", "kcal", "carbs_g", "protein_g", "fat_g"]

# Everyday foods added for everyone. Values per 100 g (approximate).
# (code, name, kcal, carbs, protein, fat, emoji, serving name, serving grams)
STARTER_FOODS = [
    ("F-BREAD",   "Bread (white)",        265, 49,  9,   3.2, "🍞", "slice", 30),
    ("F-BBREAD",  "Bread (brown)",        247, 41,  13,  3.4, "🍞", "slice", 30),
    ("F-EGG",     "Egg (boiled)",         155, 1.1, 13,  11,  "🥚", "egg", 50),
    ("F-OMELET",  "Omelette",             154, 0.6, 11,  12,  "🍳", "omelette", 60),
    ("F-MILK",    "Milk (toned)",         60,  4.8, 3.2, 3.3, "🥛", "glass", 250),
    ("F-ROTI",    "Roti / Chapati",       264, 46,  8.7, 3.7, "🫓", "roti", 40),
    ("F-PARATHA", "Paratha",              326, 45,  6.4, 13,  "🫓", "paratha", 80),
    ("F-SABJI",   "Sabji (mixed veg)",    85,  9,   2.5, 4.5, "🥘", "bowl", 150),
    ("F-DAL",     "Dal (cooked)",         116, 20,  9,   0.4, "🍲", "bowl", 150),
    ("F-RICE",    "Rice (cooked)",        130, 28,  2.7, 0.3, "🍚", "bowl", 150),
    ("F-PB",      "Peanut butter",        588, 20,  25,  50,  "🥜", "tbsp", 16),
    ("F-BANANA",  "Banana",               89,  23,  1.1, 0.3, "🍌", "banana", 120),
    ("F-APPLE",   "Apple",                52,  14,  0.3, 0.2, "🍎", "apple", 180),
    ("F-OATS",    "Oats (dry)",           389, 66,  17,  7,   "🥣", "bowl", 40),
    ("F-PANEER",  "Paneer",               265, 1.2, 18,  21,  "🧀", "piece", 30),
    ("F-CHICKEN", "Chicken breast",       165, 0,   31,  3.6, "🍗", "serving", 100),
    ("F-POHA",    "Poha",                 130, 25,  2.5, 2.5, "🍛", "plate", 150),
    ("F-CURD",    "Curd",                 61,  4.7, 3.5, 3.3, "🥣", "bowl", 100),
]
FOOD_INFO = {c: (e, s, sg) for c, *_, e, s, sg in STARTER_FOODS}
# ============================================================================

app = Flask(__name__)
app.secret_key = "change-this-secret-key"


# ---------- DATABASE ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DB_FILE)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, pin_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS foods (
      barcode TEXT PRIMARY KEY, name TEXT NOT NULL, stock_g REAL DEFAULT 0,
      kcal REAL DEFAULT 0, carbs_g REAL DEFAULT 0,
      protein_g REAL DEFAULT 0, fat_g REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS meal_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, day TEXT,
      meal TEXT, barcode TEXT, grams REAL);
    CREATE TABLE IF NOT EXISTS water_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, day TEXT, ml REAL);
    CREATE TABLE IF NOT EXISTS goals (
      username TEXT, name TEXT, value REAL, PRIMARY KEY (username, name));
    """)
    # stock 0 = loose item, never runs out
    db.executemany("INSERT OR IGNORE INTO foods VALUES (?,?,0,?,?,?,?)",
                   [f[:6] for f in STARTER_FOODS])
    db.commit()
    db.close()


def today():
    return date.today().isoformat()


def num(text):
    text = str(text or "").strip()
    return float(text) if text else 0.0


def hash_pin(user, pin):
    return hashlib.sha256((user + pin).encode()).hexdigest()


def totals(user, day):
    q = """SELECT COALESCE(SUM(f.kcal*m.grams/100),0),
                  COALESCE(SUM(f.carbs_g*m.grams/100),0),
                  COALESCE(SUM(f.protein_g*m.grams/100),0),
                  COALESCE(SUM(f.fat_g*m.grams/100),0)
           FROM meal_log m JOIN foods f ON f.barcode=m.barcode
           WHERE m.username=? AND m.day=?"""
    kcal, carbs, protein, fat = get_db().execute(q, (user, day)).fetchone()
    water = get_db().execute("SELECT COALESCE(SUM(ml),0) FROM water_log "
                             "WHERE username=? AND day=?", (user, day)).fetchone()[0]
    return {"kcal": kcal, "carbs_g": carbs, "protein_g": protein,
            "fat_g": fat, "water_ml": water}


def get_goals(user):
    goals = dict(DEFAULT_GOALS)
    goals.update(dict(get_db().execute(
        "SELECT name, value FROM goals WHERE username=?", (user,)).fetchall()))
    return goals


def food_dict(row):
    d = dict(row)
    d["emoji"], d["serving"], d["serving_g"] = FOOD_INFO.get(d["barcode"], ("🍽️", "", 0))
    return d


def fetch_off(barcode):
    """Ask Open Food Facts (free, needs internet). Returns dict or None."""
    url = "https://world.openfoodfacts.org/api/v2/product/" + barcode + ".json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MyMealTracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
    except Exception:
        return None
    if data.get("status") != 1:
        return None
    p, n = data["product"], data["product"].get("nutriments", {})
    return {"name": p.get("product_name") or "Unknown",
            "kcal": n.get("energy-kcal_100g", 0),
            "carbs_g": n.get("carbohydrates_100g", 0),
            "protein_g": n.get("proteins_100g", 0),
            "fat_g": n.get("fat_100g", 0)}


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapper


@app.context_processor
def inject():
    return {"APP_NAME": APP_NAME, "user": session.get("user")}


# ---------- LOGIN ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("username", "").strip().lower()
        pin = request.form.get("pin", "")
        db = get_db()
        if request.form.get("action") == "signup":
            if not name or len(pin) < 4:
                flash("Need a username and a 4+ character PIN.", "bad")
                return redirect(url_for("login"))
            try:
                db.execute("INSERT INTO users VALUES (?,?)", (name, hash_pin(name, pin)))
            except sqlite3.IntegrityError:
                flash("That username is taken.", "bad")
                return redirect(url_for("login"))
            for k, v in DEFAULT_GOALS.items():
                db.execute("INSERT OR IGNORE INTO goals VALUES (?,?,?)", (name, k, v))
            db.commit()
        else:
            row = db.execute("SELECT pin_hash FROM users WHERE username=?", (name,)).fetchone()
            if not row or row[0] != hash_pin(name, pin):
                flash("Wrong username or PIN.", "bad")
                return redirect(url_for("login"))
        session["user"] = name
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- DASHBOARD ----------
@app.route("/")
@login_required
def dashboard():
    user, db = session["user"], get_db()
    t, goals = totals(user, today()), get_goals(user)
    rows = db.execute(
        "SELECT m.id, m.meal, m.grams, f.* FROM meal_log m JOIN foods f "
        "ON f.barcode=m.barcode WHERE m.username=? AND m.day=? ORDER BY m.id",
        (user, today())).fetchall()
    by_meal = {m: [] for m in MEALS}
    for r in rows:
        d = food_dict(r)
        d["id"], d["grams"] = r["id"], r["grams"]
        d["eaten_kcal"] = r["kcal"] * r["grams"] / 100
        by_meal.setdefault(r["meal"], []).append(d)
    week = []
    for i in range(6, -1, -1):
        day = date.today() - timedelta(days=i)
        week.append({"label": day.strftime("%a"),
                     "kcal": round(totals(user, day.isoformat())["kcal"])})
    return render_template("dashboard.html", t=t, goals=goals, names=NAMES,
                           suffix=SUFFIX, by_meal=by_meal, units=UNITS,
                           week=week, today=date.today().strftime("%A, %d %B"))


@app.route("/water", methods=["POST"])
@login_required
def add_water():
    try:
        ml = num(request.form.get("amount")) * UNITS.get(request.form.get("unit"), 1)
    except ValueError:
        flash("Water must be a number.", "bad")
        return redirect(url_for("dashboard"))
    if ml > 0:
        get_db().execute("INSERT INTO water_log (username,day,ml) VALUES (?,?,?)",
                         (session["user"], today(), ml))
        get_db().commit()
        flash(f"Added {ml:.0f} ml water 💧", "good")
    return redirect(url_for("dashboard"))


@app.route("/delete/<int:entry_id>", methods=["POST"])
@login_required
def delete_entry(entry_id):
    db = get_db()
    row = db.execute("SELECT barcode, grams FROM meal_log WHERE id=? AND username=?",
                     (entry_id, session["user"])).fetchone()
    if row:
        # give stock back for packed items
        db.execute("UPDATE foods SET stock_g=stock_g+? WHERE barcode=? AND stock_g>0",
                   (row["grams"], row["barcode"]))
        db.execute("DELETE FROM meal_log WHERE id=?", (entry_id,))
        db.commit()
        flash("Entry removed.", "good")
    return redirect(url_for("dashboard"))


# ---------- LOG A MEAL ----------
@app.route("/log", methods=["GET", "POST"])
@login_required
def log_meal():
    db = get_db()
    if request.method == "POST":
        code = request.form.get("barcode")
        meal = request.form.get("meal", MEALS[1])
        f = db.execute("SELECT * FROM foods WHERE barcode=?", (code,)).fetchone()
        try:
            grams = num(request.form.get("grams"))
        except ValueError:
            grams = 0
        if not f or grams <= 0:
            flash("Pick a food and enter grams more than 0.", "bad")
            return redirect(url_for("log_meal"))
        if f["stock_g"] > 0:
            if grams > f["stock_g"]:
                flash(f"Not enough stock left! Only {f['stock_g']:g} g of {f['name']}.", "bad")
                return redirect(url_for("log_meal"))
            db.execute("UPDATE foods SET stock_g=stock_g-? WHERE barcode=?", (grams, code))
        db.execute("INSERT INTO meal_log (username,day,meal,barcode,grams) VALUES (?,?,?,?,?)",
                   (session["user"], today(), meal, code, grams))
        db.commit()
        flash(f"Logged {grams:g} g {f['name']} = {grams / 100 * f['kcal']:.0f} kcal", "good")
        return redirect(url_for("log_meal", meal=meal))
    foods = [food_dict(r) for r in db.execute("SELECT * FROM foods ORDER BY name")]
    return render_template("log.html", foods=foods, meals=MEALS,
                           meal=request.args.get("meal", MEALS[1]))


# ---------- FOOD DATABASE ----------
@app.route("/foods", methods=["GET", "POST"])
@login_required
def foods():
    db = get_db()
    if request.method == "POST":
        code = request.form.get("barcode", "").strip()
        name = request.form.get("name", "").strip()
        if not code or not name:
            flash("Barcode and name are needed.", "bad")
            return redirect(url_for("foods"))
        try:
            vals = [num(request.form.get(k)) for k in FIELDS[2:]]
        except ValueError:
            flash("Use numbers only in the number boxes.", "bad")
            return redirect(url_for("foods"))
        db.execute("INSERT OR REPLACE INTO foods VALUES (?,?,?,?,?,?,?)", (code, name, *vals))
        db.commit()
        flash(name + " saved for everyone!", "good")
        return redirect(url_for("foods"))
    all_foods = [food_dict(r) for r in db.execute("SELECT * FROM foods ORDER BY name")]
    return render_template("foods.html", foods=all_foods)


@app.route("/lookup/<code>")
@login_required
def lookup(code):
    row = get_db().execute("SELECT * FROM foods WHERE barcode=?", (code,)).fetchone()
    if row:
        return jsonify(found="local", food=dict(row))
    d = fetch_off(code)
    return jsonify(found="online", food=d) if d else jsonify(found=None)


# ---------- GOALS ----------
@app.route("/goals", methods=["GET", "POST"])
@login_required
def goals():
    user, db = session["user"], get_db()
    if request.method == "POST":
        try:
            vals = {k: num(request.form.get(k)) for k in NAMES}
        except ValueError:
            flash("Goals must be numbers.", "bad")
            return redirect(url_for("goals"))
        for k, v in vals.items():
            db.execute("INSERT OR REPLACE INTO goals VALUES (?,?,?)", (user, k, v))
        db.commit()
        flash("Goals saved.", "good")
        return redirect(url_for("dashboard"))
    return render_template("goals.html", goals=get_goals(user), names=NAMES, suffix=SUFFIX)


init_db()

if __name__ == "__main__":
    app.run(debug=True)
