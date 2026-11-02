"""Multi-user meal tracker. Shared food DB, personal logs.
Uses own/simulated data only."""
import sqlite3
import json
import hashlib
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# ======================= SETTINGS: change things here =======================
APP_NAME = "My Meal Tracker"        # title of the window and login screen
DB_FILE = "tracker.db"              # name of the database file
WINDOW_SIZE = "440x600"             # width x height
MEALS = ["Breakfast", "Lunch", "Dinner", "Snack"]   # meal dropdown
DEFAULT_GOALS = {"kcal": 2000, "carbs_g": 250, "protein_g": 100,
                 "fat_g": 70, "water_ml": 2500}     # goals for new users
UNITS = {"ml": 1, "cup": 240, "glass": 250, "oz": 29.57, "litre": 1000}  # water: ml in 1 unit
CHART_COLOR = "#4c9be8"             # bar chart colour
# ============================================================================

# ---------- 1. DATABASE ----------
# foods = SHARED by everyone. meal_log / water_log / goals = PER USER.
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

FIELDS = ["barcode", "name", "stock_g", "kcal", "carbs_g", "protein_g", "fat_g"]
NAMES = {"kcal": "Calories", "carbs_g": "Carbs g", "protein_g": "Protein g",
         "fat_g": "Fat g", "water_ml": "Water ml"}


def today():
    return date.today().isoformat()


def num(text):
    """Empty box = 0."""
    text = str(text).strip()
    return float(text) if text else 0.0


def hash_pin(user, pin):
    return hashlib.sha256((user + pin).encode()).hexdigest()


# ---------- 2. CLASSES ----------
class FoodItem:
    """Packed food. Nutrition is per 100 g. Stock is tracked."""

    def __init__(self, barcode, name, stock_g=0, kcal=0,
                 carbs_g=0, protein_g=0, fat_g=0):
        self.barcode, self.name, self.stock_g = barcode, name, stock_g
        self.kcal, self.carbs_g = kcal, carbs_g
        self.protein_g, self.fat_g = protein_g, fat_g

    @staticmethod
    def find(barcode):
        row = db.execute("SELECT * FROM foods WHERE barcode=?", (barcode,)).fetchone()
        if row is None:
            return None
        return FoodItem(*row) if row[2] > 0 else LooseFood(*row)

    def save(self):
        db.execute("INSERT OR REPLACE INTO foods VALUES (?,?,?,?,?,?,?)",
                   (self.barcode, self.name, self.stock_g, self.kcal,
                    self.carbs_g, self.protein_g, self.fat_g))
        db.commit()

    def use_stock(self, grams):
        if grams > self.stock_g:
            raise ValueError("Not enough stock left!")
        self.stock_g -= grams
        db.execute("UPDATE foods SET stock_g=? WHERE barcode=?",
                   (self.stock_g, self.barcode))

    def eat(self, user, grams, meal):
        self.use_stock(grams)
        db.execute("INSERT INTO meal_log (username,day,meal,barcode,grams) "
                   "VALUES (?,?,?,?,?)", (user, today(), meal, self.barcode, grams))
        db.commit()


class LooseFood(FoodItem):
    """Inheritance: stock 0 = loose item, never runs out."""

    def use_stock(self, grams):
        pass


# ---------- 3. HELPERS: online lookup, totals ----------
def fetch_off(barcode):
    """Ask Open Food Facts (free, needs internet). Returns dict or None."""
    url = "https://world.openfoodfacts.org/api/v2/product/" + barcode + ".json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME.replace(" ", "") + "/1.0"})
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


def totals(user, day):
    q = """SELECT COALESCE(SUM(f.kcal*m.grams/100),0),
                  COALESCE(SUM(f.carbs_g*m.grams/100),0),
                  COALESCE(SUM(f.protein_g*m.grams/100),0),
                  COALESCE(SUM(f.fat_g*m.grams/100),0)
           FROM meal_log m JOIN foods f ON f.barcode=m.barcode
           WHERE m.username=? AND m.day=?"""
    kcal, carbs, protein, fat = db.execute(q, (user, day)).fetchone()
    water = db.execute("SELECT COALESCE(SUM(ml),0) FROM water_log "
                       "WHERE username=? AND day=?", (user, day)).fetchone()[0]
    return {"kcal": kcal, "carbs_g": carbs, "protein_g": protein,
            "fat_g": fat, "water_ml": water}


def get_goals(user):
    return dict(db.execute("SELECT name, value FROM goals WHERE username=?",
                           (user,)).fetchall())


# ---------- 4. WINDOWS ----------
root = tk.Tk()
root.title(APP_NAME)
root.geometry(WINDOW_SIZE)


def clear():
    for w in root.winfo_children():
        w.destroy()


def add_entries(frame, labels):
    boxes = {}
    for i, label in enumerate(labels):
        ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", pady=3)
        boxes[label] = ttk.Entry(frame, width=26)
        boxes[label].grid(row=i, column=1, pady=3, padx=6)
    return boxes


def login_screen():
    clear()
    f = ttk.Frame(root, padding=30)
    f.pack(expand=True)
    ttk.Label(f, text=APP_NAME, font=("Segoe UI", 16, "bold")).pack(pady=10)
    ttk.Label(f, text="Username").pack(anchor="w")
    u = ttk.Entry(f, width=26)
    u.pack()
    ttk.Label(f, text="PIN (4+ characters)").pack(anchor="w", pady=(8, 0))
    p = ttk.Entry(f, width=26, show="*")
    p.pack()

    def login():
        name = u.get().strip().lower()
        row = db.execute("SELECT pin_hash FROM users WHERE username=?", (name,)).fetchone()
        if row and row[0] == hash_pin(name, p.get()):
            start_app(name)
        else:
            messagebox.showerror("Oops", "Wrong username or PIN.")

    def signup():
        name = u.get().strip().lower()
        if not name or len(p.get()) < 4:
            messagebox.showerror("Oops", "Need a username and a 4+ character PIN.")
            return
        try:
            db.execute("INSERT INTO users VALUES (?,?)", (name, hash_pin(name, p.get())))
        except sqlite3.IntegrityError:
            messagebox.showerror("Oops", "That username is taken.")
            return
        for k, v in DEFAULT_GOALS.items():
            db.execute("INSERT INTO goals VALUES (?,?,?)", (name, k, v))
        db.commit()
        start_app(name)

    ttk.Button(f, text="Login", command=login).pack(pady=(14, 4), fill="x")
    ttk.Button(f, text="Create account", command=signup).pack(fill="x")


def start_app(user):
    clear()
    top = ttk.Frame(root)
    top.pack(fill="x", padx=8, pady=(8, 0))
    ttk.Label(top, text="Hi, " + user, font=("Segoe UI", 11, "bold")).pack(side="left")
    ttk.Button(top, text="Logout", command=login_screen).pack(side="right")
    tabs = ttk.Notebook(root)
    tabs.pack(fill="both", expand=True, padx=8, pady=8)

    def tab(title):
        fr = ttk.Frame(tabs, padding=12)
        tabs.add(fr, text=title)
        return fr

    status = ttk.Label(root, text="")
    status.pack(pady=(0, 6))

    def msg(text, bad=False):
        status.config(text=text, foreground="red" if bad else "green")

    # ----- Tab 1: Add food (shared by all users) -----
    t1 = tab("Add food")
    fb = add_entries(t1, FIELDS)
    ttk.Label(t1, text="Values are per 100 g. Blank = 0. Stock 0 = loose item.",
              foreground="gray").grid(row=7, column=0, columnspan=2, pady=4)

    def fill(d):
        for k, v in d.items():
            fb[k].delete(0, "end")
            fb[k].insert(0, v)

    def lookup():
        code = fb["barcode"].get().strip()
        if not code:
            return msg("Type or scan a barcode first.", True)
        f = FoodItem.find(code)
        if f:
            fill({k: getattr(f, k) for k in FIELDS})
            return msg("Found in your database.")
        d = fetch_off(code)
        if d:
            fill(d)
            msg("Found online. Check values, add stock, then Save.")
        else:
            msg("Not found. Type the values once, then Save.", True)

    def scan_photo():
        try:
            from pyzbar.pyzbar import decode
            from PIL import Image
        except ImportError:
            return messagebox.showinfo(
                "Not installed", "Run:  pip install pyzbar pillow\nThen try again.")
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg")])
        if not path:
            return
        codes = decode(Image.open(path))
        if not codes:
            return msg("No barcode found. Try a sharper, closer photo.", True)
        fb["barcode"].delete(0, "end")
        fb["barcode"].insert(0, codes[0].data.decode())
        lookup()

    def save_food():
        code, name = fb["barcode"].get().strip(), fb["name"].get().strip()
        if not code or not name:
            return msg("Barcode and name are needed.", True)
        try:
            vals = [num(fb[k].get()) for k in FIELDS[2:]]
        except ValueError:
            return msg("Use numbers only in the number boxes.", True)
        FoodItem(code, name, *vals).save()
        msg(name + " saved for everyone!")

    bf = ttk.Frame(t1)
    bf.grid(row=8, column=0, columnspan=2, pady=8)
    ttk.Button(bf, text="Look up", command=lookup).pack(side="left", padx=3)
    ttk.Button(bf, text="Scan photo", command=scan_photo).pack(side="left", padx=3)
    ttk.Button(bf, text="Save", command=save_food).pack(side="left", padx=3)

    # ----- Tab 2: Log (search, quantity, water) -----
    t2 = tab("Log")
    ttk.Label(t2, text="Search food (name or barcode, Enter picks first)").pack(anchor="w")
    q = tk.StringVar()
    se = ttk.Entry(t2, textvariable=q, width=40)
    se.pack(anchor="w")
    box = tk.Listbox(t2, height=6, exportselection=False)
    box.pack(fill="x", pady=4)
    found = []

    def search(*_):
        found.clear()
        box.delete(0, "end")
        s = "%" + q.get().strip() + "%"
        rows = db.execute("SELECT barcode, name FROM foods WHERE name LIKE ? "
                          "OR barcode LIKE ? ORDER BY name LIMIT 20", (s, s))
        for code, name in rows:
            found.append(code)
            box.insert("end", name + "  (" + code + ")")

    q.trace_add("write", search)

    row = ttk.Frame(t2)
    row.pack(anchor="w", pady=4)
    ttk.Label(row, text="grams").pack(side="left")
    gram = ttk.Entry(row, width=8)
    gram.pack(side="left", padx=4)
    meal = ttk.Combobox(row, values=MEALS,
                        width=10, state="readonly")
    meal.set(MEALS[1])
    meal.pack(side="left", padx=4)

    def pick(_=None):
        if found:
            box.selection_clear(0, "end")
            box.selection_set(0)
            gram.focus()

    se.bind("<Return>", pick)

    def log_meal():
        sel = box.curselection()
        if not sel:
            return msg("Pick a food from the list first.", True)
        f = FoodItem.find(found[sel[0]])
        try:
            grams = num(gram.get())
        except ValueError:
            return msg("Grams must be a number.", True)
        if grams <= 0:
            return msg("Grams must be more than 0.", True)
        try:
            f.eat(user, grams, meal.get())
        except ValueError as err:
            return msg(str(err), True)
        msg(f"Logged {grams:g} g {f.name} = {grams / 100 * f.kcal:.0f} kcal")

    ttk.Button(row, text="Log it", command=log_meal).pack(side="left", padx=4)

    ttk.Separator(t2).pack(fill="x", pady=10)
    wr = ttk.Frame(t2)
    wr.pack(anchor="w")
    ttk.Label(wr, text="water").pack(side="left")
    wamt = ttk.Entry(wr, width=6)
    wamt.pack(side="left", padx=4)
    unit = ttk.Combobox(wr, values=list(UNITS), width=7, state="readonly")
    unit.set("glass")
    unit.pack(side="left", padx=4)

    def log_water():
        try:
            ml = num(wamt.get()) * UNITS[unit.get()]  # always store ml
        except ValueError:
            return msg("Water must be a number.", True)
        db.execute("INSERT INTO water_log (username,day,ml) VALUES (?,?,?)",
                   (user, today(), ml))
        db.commit()
        msg(f"Added {ml:.0f} ml water")

    ttk.Button(wr, text="Add water", command=log_water).pack(side="left", padx=4)

    # ----- Tab 3: Today (summary, chart, goals) -----
    t3 = tab("Today")
    summary = ttk.Label(t3, font=("Consolas", 10), justify="left")
    summary.pack(anchor="w")

    def refresh():
        t, g = totals(user, today()), get_goals(user)
        lines = [f"{NAMES[k]:<10}{t[k]:>7.0f} / {g[k]:<6.0f}"
                 f"({t[k] / g[k] * 100 if g[k] else 0:.0f}%)" for k in NAMES]
        meals = db.execute(
            "SELECT m.meal, f.name, m.grams FROM meal_log m JOIN foods f "
            "ON f.barcode=m.barcode WHERE m.username=? AND m.day=? ORDER BY m.id",
            (user, today())).fetchall()
        lines += ["", "Eaten today:"] + [f"  {a}: {b} {c:g} g" for a, b, c in meals]
        summary.config(text="\n".join(lines))

    def show_chart():
        t, g = totals(user, today()), get_goals(user)
        win = tk.Toplevel(root)
        win.title(user + ": today vs goals")
        fig = Figure(figsize=(8, 3.6))
        ax1, ax2 = fig.add_subplot(121), fig.add_subplot(122)
        pct = [t[k] / g[k] * 100 if g[k] else 0 for k in NAMES]
        ax1.barh(list(NAMES.values()), pct, color=CHART_COLOR)
        ax1.axvline(100, color="red", linestyle="--")
        ax1.set_title("% of goal")
        cal = [t["carbs_g"] * 4, t["protein_g"] * 4, t["fat_g"] * 9]
        if sum(cal) > 0:
            ax2.pie(cal, labels=["Carbs", "Protein", "Fat"], autopct="%1.0f%%")
        else:
            ax2.text(0.5, 0.5, "No meals logged yet", ha="center")
            ax2.axis("off")
        ax2.set_title("Calories by macro")
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    br = ttk.Frame(t3)
    br.pack(pady=6)
    ttk.Button(br, text="Refresh", command=refresh).pack(side="left", padx=3)
    ttk.Button(br, text="Show chart", command=show_chart).pack(side="left", padx=3)

    ttk.Separator(t3).pack(fill="x", pady=8)
    ttk.Label(t3, text="My daily goals").pack(anchor="w")
    gf = ttk.Frame(t3)
    gf.pack(anchor="w")
    goal_boxes = {}
    for i, k in enumerate(NAMES):
        ttk.Label(gf, text=NAMES[k]).grid(row=i, column=0, sticky="w", pady=2)
        goal_boxes[k] = ttk.Entry(gf, width=10)
        goal_boxes[k].grid(row=i, column=1, padx=6)
        goal_boxes[k].insert(0, get_goals(user).get(k, DEFAULT_GOALS[k]))

    def save_goals():
        try:
            vals = {k: num(b.get()) for k, b in goal_boxes.items()}
        except ValueError:
            return msg("Goals must be numbers.", True)
        for k, v in vals.items():
            db.execute("INSERT OR REPLACE INTO goals VALUES (?,?,?)", (user, k, v))
        db.commit()
        refresh()
        msg("Goals saved.")

    ttk.Button(t3, text="Save goals", command=save_goals).pack(pady=8)

    tabs.bind("<<NotebookTabChanged>>", lambda e: (search(), refresh()))
    search()
    refresh()


login_screen()
root.mainloop()