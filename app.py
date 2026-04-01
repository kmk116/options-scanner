# Options Scanner Web Dashboard
# Public Web Dashboard with Database Users

# ============================
# IMPORTANT
# ============================
# This version avoids:
# - multiprocessing
# - threading
# - background workers
# - sandbox server crashes
#
# To run server locally:
# python app.py runserver

# ============================
# Install Requirements
# ============================
# pip install flask pandas numpy requests

from flask import Flask, request, redirect, session, jsonify
import pandas as pd
import numpy as np
import requests
import time
import sys
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)
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
            (username, hash_password(password))
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
    cur.execute(
        "SELECT password FROM users WHERE username=?",
        (username,)
    )
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
    app.secret_key = "super_secret_key_change_this"

    init_db()

    # ============================
    # Scanner Config
    # ============================

    TICKERS = [
        "NVDA","AAPL","MSFT","TSLA","AMD",
        "META","AMZN","GOOGL","NFLX","SMCI",
        "XOM","CVX","COP","EOG","FANG"
    ]

    # ============================
    # Cache
    # ============================

    SCAN_CACHE = {"data": [], "last": 0}
    CACHE_SECONDS = 60

    # ============================
    # Data Fetch
    # ============================

    def fetch_stock_data(ticker):
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=3mo&interval=1d"
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return None

            data = response.json()

            if "chart" not in data or not data["chart"]["result"]:
                return None

            result = data['chart']['result'][0]
            quotes = result['indicators']['quote'][0]

            df = pd.DataFrame({
                'Close': quotes['close'],
                'Volume': quotes['volume']
            })

            df.dropna(inplace=True)
            return df

        except Exception:
            return None

    # ============================
    # Indicators
    # ============================

    def calculate_rsi(data, period=14):
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi


    def calculate_ema(data, span=20):
        return data['Close'].ewm(span=span, adjust=False).mean()

    # ============================
    # Scanner
    # ============================

    def scan_market():
        results = []

        for ticker in TICKERS:
            try:
                df = fetch_stock_data(ticker)

                if df is None or len(df) < 20:
                    continue

                price = df['Close'].iloc[-1]
                volume = df['Volume'].iloc[-1]
                rsi = calculate_rsi(df).iloc[-1]
                ema = calculate_ema(df).iloc[-1]

                trend = "BULL" if price > ema else "BEAR"
                momentum = "UP" if df['Close'].iloc[-1] > df['Close'].iloc[-5] else "DOWN"

                results.append({
                    "ticker": ticker,
                    "price": round(float(price), 2),
                    "rsi": round(float(rsi), 1),
                    "trend": trend,
                    "momentum": momentum,
                    "volume": int(volume)
                })

            except Exception:
                continue

        return results

    # ============================
    # Cache
    # ============================

    def get_cached_scan():
        now = time.time()

        if now - SCAN_CACHE["last"] > CACHE_SECONDS:
            SCAN_CACHE["data"] = scan_market()
            SCAN_CACHE["last"] = now

        return SCAN_CACHE["data"]

    # ============================
    # Routes
    # ============================

    @app.route('/')
    def home():
        return "Options Scanner API"


    @app.route('/register', methods=['POST'])
    def register():
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            return "Missing fields", 400

        if create_user(username, password):
            return "User created"
        else:
            return "User exists", 400


    @app.route('/login', methods=['POST'])
    def login():
        username = request.form.get('username')
        password = request.form.get('password')

        if verify_user(username, password):
            session['logged_in'] = True
            return "Logged in"

        return "Invalid login", 401


    @app.route('/dashboard')
    def dashboard():
        if 'logged_in' not in session:
            return "Unauthorized", 401
        return jsonify(get_cached_scan())


    @app.route('/scan')
    def scan():
        if 'logged_in' not in session:
            return jsonify([])
        return jsonify(get_cached_scan())


    @app.route('/logout')
    def logout():
        session.clear()
        return "Logged out"


    @app.route('/health')
    def health():
        return jsonify({"status": "ok"})

    # expose for tests
    app.scan_market = scan_market
    app.calculate_rsi = calculate_rsi
    app.calculate_ema = calculate_ema
    app.get_cached_scan = get_cached_scan

    return app


app = create_app()

# ============================
# Run Server
# ============================

def run_server():
    try:
        app.run(host='127.0.0.1', port=5000, debug=False)
    except SystemExit:
        print("Server cannot run in this environment")

# ============================
# Tests
# ============================

def test_db():
    username = "testuser"
    password = "testpass"
    create_user(username, password)
    assert verify_user(username, password) is True


def test_rsi():
    df = pd.DataFrame({
        'Close': np.random.random(50),
        'Volume': np.random.randint(1000,10000,50)
    })
    rsi = app.calculate_rsi(df)
    assert len(rsi) == 50


def test_ema():
    df = pd.DataFrame({
        'Close': np.random.random(50),
        'Volume': np.random.randint(1000,10000,50)
    })
    ema = app.calculate_ema(df)
    assert len(ema) == 50


def test_scan():
    result = app.scan_market()
    assert isinstance(result, list)


def test_cache():
    data = app.get_cached_scan()
    assert isinstance(data, list)


def test_health():
    client = app.test_client()
    res = client.get('/health')
    assert res.status_code == 200


# ============================
# Production Server
# ============================

def run_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


# ============================
# Tests
# ============================

def test_db():
    username = "testuser"
    password = "testpass"
    create_user(username, password)
    assert verify_user(username, password) is True


def test_rsi():
    df = pd.DataFrame({
        'Close': np.random.random(50),
        'Volume': np.random.randint(1000,10000,50)
    })
    rsi = app.calculate_rsi(df)
    assert len(rsi) == 50


def test_ema():
    df = pd.DataFrame({
        'Close': np.random.random(50),
        'Volume': np.random.randint(1000,10000,50)
    })
    ema = app.calculate_ema(df)
    assert len(ema) == 50


def test_scan():
    result = app.scan_market()
    assert isinstance(result, list)


def test_cache():
    data = app.get_cached_scan()
    assert isinstance(data, list)


def test_health():
    client = app.test_client()
    res = client.get('/health')
    assert res.status_code == 200


# ============================
# Entry Point
# ============================

if __name__ == '__main__':
    if os.environ.get("RUN_TESTS") == "1":
        test_db()
        test_rsi()
        test_ema()
        test_scan()
        test_cache()
        test_health()
    else:
        run_server()
