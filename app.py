# Options Scanner Web Dashboard
# Public Web Dashboard with Database Users

from flask import Flask, request, redirect, session, jsonify
import pandas as pd
import numpy as np
import requests
import time
import sqlite3
import hashlib
import os

# ============================
# Database
# ============================

DB_PATH = "users.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def create_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username,password) VALUES (?,?)",
            (username, hash_password(password)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def verify_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    return row[0] == hash_password(password)


# ============================
# App Factory
# ============================


def create_app():
    app = Flask(__name__)
    app.secret_key = "change_this_secret"

    init_db()

    TICKERS = [
        "NVDA",
        "AAPL",
        "MSFT",
        "TSLA",
        "AMD",
        "META",
        "AMZN",
        "GOOGL",
        "NFLX",
        "SMCI",
    ]

    CACHE = {"data": [], "last": 0}
    CACHE_SECONDS = 60

    def fetch_stock_data(ticker):
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=3mo&interval=1d"
            res = requests.get(url, timeout=10)
            data = res.json()

            result = data["chart"]["result"][0]
            quotes = result["indicators"]["quote"][0]

            df = pd.DataFrame(
                {"Close": quotes["close"], "Volume": quotes["volume"]}
            )

            df.dropna(inplace=True)
            return df
        except Exception:
            return None

    def calculate_rsi(data, period=14):
        delta = data["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calculate_ema(data, span=20):
        return data["Close"].ewm(span=span).mean()

    def scan_market():
        results = []

        for ticker in TICKERS:
            df = fetch_stock_data(ticker)

            if df is None or len(df) < 20:
                continue

            price = df["Close"].iloc[-1]
            volume = df["Volume"].iloc[-1]
            rsi = calculate_rsi(df).iloc[-1]
            ema = calculate_ema(df).iloc[-1]

            results.append(
                {
                    "ticker": ticker,
                    "price": round(float(price), 2),
                    "rsi": round(float(rsi), 1),
                    "trend": "BULL" if price > ema else "BEAR",
                    "volume": int(volume),
                }
            )

        return results

    def get_cached_scan():
        now = time.time()

        if now - CACHE["last"] > CACHE_SECONDS:
            CACHE["data"] = scan_market()
            CACHE["last"] = now

        return CACHE["data"]

    # ============================
    # Routes
    # ============================

    @app.route("/")
    def home():
        return """
        <h2>Options Scanner</h2>

        <h3>Register</h3>
        <form method='post' action='/register'>
        Username:<br>
        <input name='username'><br>
        Password:<br>
        <input name='password' type='password'><br><br>
        <button>Register</button>
        </form>

        <h3>Login</h3>
        <form method='post' action='/login'>
        Username:<br>
        <input name='username'><br>
        Password:<br>
        <input name='password' type='password'><br><br>
        <button>Login</button>
        </form>

        <br>
        <a href='/dashboard'>Dashboard</a>
        """

    @app.route("/register", methods=["POST"])
    def register():
        username = request.form.get("username")
        password = request.form.get("password")

        if create_user(username, password):
            session["logged_in"] = True
            return redirect("/dashboard")

        return "User exists", 400

    @app.route("/login", methods=["POST"])
    def login():
        username = request.form.get("username")
        password = request.form.get("password")

        if verify_user(username, password):
            session["logged_in"] = True
            return redirect("/dashboard")

        return "Unauthorized", 401

    @app.route("/dashboard")
    def dashboard():
        if not session.get("logged_in"):
            return "Unauthorized", 401

        return jsonify(get_cached_scan())

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
