import os
import sqlite3
import re
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import easyocr
import cv2

app = Flask(__name__)
CORS(app)

@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    return response


UPLOAD_FOLDER = "uploads"
DB = "database.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

reader = easyocr.Reader(['en'], gpu=False)


def init_db():
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT,
                image TEXT,
                entry_time TEXT,
                exit_time TEXT,
                status TEXT,
                user_type TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS vehicles(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT UNIQUE,
                user_type TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT
            )
        """)

        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.executemany("""
                INSERT INTO users(username,password,role)
                VALUES(?,?,?)
            """, [
                ('admin','admin123','admin'),
                ('staff','staff123','staff'),
                ('delete','delete123','admin')
            ])

        conn.commit()


init_db()


def read_plate(image_path):

    img = cv2.imread(image_path)
    if img is None:
        return "UNKNOWN"

    img = cv2.resize(img, (700, 400))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    result = reader.readtext(thresh)

    text = "".join(t.upper() for (_, t, _) in result)
    text = re.sub(r'[^A-Z0-9]', '', text)

    match = re.search(r'[A-Z]{1,2}[0-9]{2}[A-Z]{1,2}[0-9]{4}', text)

    return match.group() if match else text


@app.route("/login", methods=["POST"])
def login():

    data = request.json or {}

    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT role FROM users WHERE username=? AND password=?",
            (data.get("username"), data.get("password"))
        )

        user = cur.fetchone()

    if user:
        return jsonify({"success": True, "role": user[0]})

    return jsonify({"success": False}), 401


@app.route("/upload", methods=["POST"])
def upload():

    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    file = request.files["file"]

    filename = datetime.now().strftime("%Y%m%d%H%M%S") + ".jpg"
    path = os.path.join(UPLOAD_FOLDER, filename)

    file.save(path)

    plate = read_plate(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()

        cur.execute("SELECT user_type FROM vehicles WHERE plate=?", (plate,))
        v = cur.fetchone()

        user_type = v[0] if v else "Guest"

        cur.execute("""
            SELECT id, status FROM history
            WHERE plate=?
            ORDER BY id DESC LIMIT 1
        """, (plate,))

        row = cur.fetchone()

        if not row or row[1] == "Exit":
            cur.execute("""
                INSERT INTO history(plate,image,entry_time,status,user_type)
                VALUES(?,?,?,?,?)
            """, (plate, filename, now, "Inside", user_type))
        else:
            cur.execute("""
                UPDATE history
                SET exit_time=?, status=?
                WHERE id=?
            """, (now, "Exit", row[0]))

        conn.commit()

    return jsonify({"number": plate})


@app.route("/history", methods=["GET"])
def history():

    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()

        rows = cur.execute("""
            SELECT id, plate, entry_time, exit_time, status, user_type
            FROM history
            ORDER BY id DESC
        """).fetchall()

    return jsonify([
        {
            "id": r[0],
            "plate": r[1],
            "entry_time": r[2],
            "exit_time": r[3],
            "status": r[4],
            "user_type": r[5]
        }
        for r in rows
    ])


@app.route("/delete-history", methods=["POST"])
def delete_history():

    data = request.json or {}

    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT role FROM users WHERE username=? AND password=?",
            (data.get("username"), data.get("password"))
        )

        user = cur.fetchone()

        if not user or user[0] != "admin":
            return jsonify({"error": "Unauthorized"}), 401

        cur.execute("DELETE FROM history")
        cur.execute("DELETE FROM sqlite_sequence WHERE name='history'")
        conn.commit()

    return jsonify({"msg": "History deleted & ID reset"})


# ⭐ REGISTER ROUTE PROPERLY HERE
@app.route("/register-vehicle", methods=["POST"])
def register_vehicle():

    data = request.json or {}

    plate = data.get("plate")
    user_type = data.get("user_type")

    if not plate or not user_type:
        return jsonify({"error": "Missing data"}), 400

    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO vehicles(plate,user_type)
                VALUES(?,?)
            """, (plate.upper(), user_type))

            conn.commit()

        except:
            return jsonify({"error": "Vehicle already registered"}), 400

    return jsonify({"msg": "Vehicle Registered"})

@app.route("/vehicles", methods=["GET"])
def get_vehicles():

    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()

        rows = cur.execute("""
            SELECT plate, user_type
            FROM vehicles
            ORDER BY id DESC
        """).fetchall()

    return jsonify([
        {
            "plate": r[0],
            "user_type": r[1]
        }
        for r in rows
    ])

if __name__ == "__main__":
    print("🚀 Server running at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)