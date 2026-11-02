# My Meal Tracker

A multi-user meal and nutrition tracker written in Python, with a SQLite database.
Track calories, carbs, protein, fat and water against your own daily goals.

## Two ways to use it

| File | What it is |
|------|------------|
| `app.py` | **Website** (Flask) – dashboard, food cards, charts, goals |
| `meal.py` | **Desktop app** (Tkinter) – the original version |

Both share the same `tracker.db`, so users, foods and logs are the same in each.

## Features
- Login / sign up with a username + PIN (each user has their own logs and goals)
- Shared food database with everyday foods built in: bread, eggs, milk, roti, paratha,
  sabji, dal, rice, peanut butter, banana, apple, oats, paneer, chicken, poha, curd
- One-tap portions (1 roti, 2 eggs, 1 glass milk…) or exact grams
- Barcode lookup via Open Food Facts
- Water tracking in ml / glass / cup / oz / litre
- Progress bars, macro doughnut chart and a 7-day calorie chart

## Run it
```bash
pip install -r requirements.txt
python app.py      # website  -> open http://127.0.0.1:5000
python meal.py     # desktop app
```
Run the commands from inside this folder. The database is created automatically on first run.
