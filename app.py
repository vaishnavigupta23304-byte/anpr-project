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

UPLOAD_FOLDER = "uploads"
DB = "database.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ⭐ VERY IMPORTANT → Lazy load OCR (memory optimization)
reader = None

def get_reader():
    global reader
    if reader is None:
        print("🔥 Loading EasyOCR Model...")
        reader = easyocr.Reader(['en'], gpu=False)
    return reader


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
                ('staff','staff123','staff')
            ])

        conn.commit()

init_db()


def read_plate(path):
    img = cv2.imread(path)
    if img is None:
        return "UNKNOWN"

    img = cv2.resize(img, (700, 400))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    reader = get_reader()   # ⭐ Lazy load here
    result = reader.readtext(thresh)

    text = "".join(t.upper() for (_, t, _) in result)
    text = re.sub(r'[^A-Z0-9]', '', text)

    match = re.search(r'[A-Z]{1,2}[0-9]{2}[A-Z]{1,2}[0-9]{4}', text)
    return match.group() if match else text


@app.route("/login", methods=["POST"])
def login():
    data = request.json

    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT role FROM users WHERE username=? AND password=?",
            (data["username"], data["password"])
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
            UPDATE history SET exit_time=?, status=?
            WHERE id=?
            """, (now, "Exit", row[0]))

        conn.commit()

    return jsonify({"number": plate})


@app.route("/history")
def history():
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        rows = cur.execute("""
        SELECT id, plate, entry_time, exit_time, status, user_type
        FROM history ORDER BY id DESC
        """).fetchall()

    return jsonify([
        {
            "id": r[0],
            "plate": r[1],
            "entry_time": r[2],
            "exit_time": r[3],
            "status": r[4],
            "user_type": r[5]
        } for r in rows
    ])


@app.route("/register-vehicle", methods=["POST"])
def register_vehicle():
    data = request.json

    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO vehicles(plate,user_type) VALUES(?,?)",
                (data["plate"].upper(), data["user_type"])
            )
            conn.commit()
        except:
            return jsonify({"error": "Already exists"}), 400

    return jsonify({"msg": "Vehicle Registered"})


@app.route("/vehicles")
def vehicles():
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT plate,user_type FROM vehicles ORDER BY id DESC"
        ).fetchall()

    return jsonify([
        {"plate": r[0], "user_type": r[1]}
        for r in rows
    ])


# ⭐ PRODUCTION START
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)