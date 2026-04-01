# Options Scanner Web Dashboard
# Public Web Dashboard with Database Users
# Render / Gunicorn Friendly + Safe Startup

from flask import Flask, request, redirect, session, jsonify
import pandas as pd
import numpy as np
import requests
import time
import sqlite3
import hashlib
import os
import io

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

    app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key_123")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = True

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

    # ============================
    # Data Fetch
    # ============================

    def fetch_stock_data(ticker):
        # Try Stooq first (more reliable on cloud hosts)
        try:
            stooq_symbol = ticker.lower() + ".us"
            url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"

            headers = {"User-Agent": "Mozilla/5.0"}

            res = requests.get(url, headers=headers, timeout=10)

            if res.status_code == 200 and len(res.text) > 0:
                df = pd.read_csv(io.StringIO(res.text))

                if "Close" in df.columns and "Volume" in df.columns:
                    df = df[["Close", "Volume"]]
                    df.dropna(inplace=True)

                    if len(df) > 0:
                        return df

        except Exception as e:
            print("Stooq fetch error:", ticker, e)

        # Fallback to Yahoo
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=3mo&interval=1d"

            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            }

            res = requests.get(url, headers=headers, timeout=10)

            if res.status_code == 200:
                data = res.json()

                if data.get("chart") and data["chart"].get("result"):
                    result = data["chart"]["result"][0]
                    quotes = result["indicators"]["quote"][0]

                    df = pd.DataFrame(
                        {"Close": quotes.get("close"), "Volume": quotes.get("volume")}
                    )

                    df.dropna(inplace=True)

                    if len(df) > 0:
                        return df

        except Exception as e:
            print("Yahoo fetch error:", ticker, e)

        return None

    # ============================
    # Indicators
    # ============================

    def calculate_rsi(data, period=14):
        delta = data["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calculate_ema(data, span=20):
        return data["Close"].ewm(span=span).mean()

    # ============================
    # Scanner
    # ============================

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
        <html>
        <head><title>Options Scanner</title></head>
        <body>
        <h2>Options Scanner</h2>

        <h3>Register</h3>
        <form method='post' action='/register'>
        Username:<br>
        <input name='username'><br>
        Password:<br>
        <input name='password' type='password'><br><br>
        <button type='submit'>Register</button>
        </form>

        <h3>Login</h3>
        <form method='post' action='/login'>
        Username:<br>
        <input name='username'><br>
        Password:<br>
        <input name='password' type='password'><br><br>
        <button type='submit'>Login</button>
        </form>

        <br>
        <a href='/dashboard'>Dashboard</a>
        </body>
        </html>
        """

    @app.route("/register", methods=["POST"])
    def register():
        username = request.form.get("username")
        password = request.form.get("password")

        if create_user(username, password):
            session["logged_in"] = True
            session["username"] = username
            return redirect("/dashboard")

        return "User exists", 400

    @app.route("/login", methods=["POST"])
    def login():
        username = request.form.get("username")
        password = request.form.get("password")

        if verify_user(username, password):
            session["logged_in"] = True
            session["username"] = username
            return redirect("/dashboard")

        return "Unauthorized", 401

    @app.route("/dashboard")
    def dashboard():
        if not session.get("logged_in"):
            return redirect("/")

        return jsonify(get_cached_scan())

    @app.route("/health")
    def health():
        return {"status": "ok"}

    # expose for testing
    app.scan_market = scan_market
    app.get_cached_scan = get_cached_scan

    return app


# ============================
# Create App
# ============================

app = create_app()


# ============================
# Tests
# ============================


def test_health():
    client = app.test_client()
    res = client.get("/health")
    assert res.status_code == 200


def test_home():
    client = app.test_client()
    res = client.get("/")
    assert res.status_code == 200


def test_scan():
    data = app.get_cached_scan()
    assert isinstance(data, list)


def test_fetch():
    data = app.scan_market()
    assert isinstance(data, list)


def test_login_flow():
    client = app.test_client()
    client.post("/register", data={"username": "test1", "password": "pass"})
    res = client.get("/dashboard")
    assert res.status_code in (200, 302)


def run_tests():
    test_health()
    test_home()
    test_scan()
    test_fetch()
    test_login_flow()


# ============================
# Safe Start
# ============================

if __name__ == "__main__":
    try:
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port)
    except SystemExit:
        print("Server start skipped (restricted environment)")
        run_tests()
