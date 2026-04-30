import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

APP_SECRET = os.getenv("APP_SECRET", os.urandom(24).hex())
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
CRON_SECRET = os.getenv("CRON_SECRET", "change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")
IG_USER_ID = os.getenv("IG_USER_ID", "")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v22.0")

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

app = Flask(__name__)
app.secret_key = APP_SECRET


def is_postgres():
    return DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")


def db_conn():
    if is_postgres():
        return psycopg2.connect(DATABASE_URL, sslmode="require")
    path = DATABASE_URL.replace("sqlite:///", "")
    return sqlite3.connect(path)


def init_db():
    conn = db_conn()
    cur = conn.cursor()
    if is_postgres():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id SERIAL PRIMARY KEY,
                caption TEXT NOT NULL,
                video_url TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                creation_id TEXT,
                ig_media_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caption TEXT NOT NULL,
                video_url TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                creation_id TEXT,
                ig_media_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
    conn.commit()
    conn.close()


def query_all(sql, params=()):
    conn = db_conn()
    if is_postgres():
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
    else:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def execute(sql, params=()):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    conn.close()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("ok"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def graph_url(path):
    return f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}"


def create_ig_container(post):
    r = requests.post(
        graph_url(f"{IG_USER_ID}/media"),
        data={
            "media_type": "REELS",
            "video_url": post["video_url"],
            "caption": post["caption"],
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=60,
    )
    data = r.json()
    if not r.ok:
        raise RuntimeError(data)
    return data["id"]


def container_status(creation_id):
    r = requests.get(
        graph_url(creation_id),
        params={"fields": "status_code,status", "access_token": IG_ACCESS_TOKEN},
        timeout=30,
    )
    data = r.json()
    if not r.ok:
        raise RuntimeError(data)
    return data


def publish_container(creation_id):
    r = requests.post(
        graph_url(f"{IG_USER_ID}/media_publish"),
        data={"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN},
        timeout=60,
    )
    data = r.json()
    if not r.ok:
        raise RuntimeError(data)
    return data.get("id")


def process_due_posts(limit=5):
    now = datetime.now(timezone.utc).isoformat()
    rows = query_all(
        "SELECT * FROM posts WHERE scheduled_at <= %s AND status IN ('pending','processing') ORDER BY scheduled_at ASC LIMIT %s" if is_postgres()
        else "SELECT * FROM posts WHERE scheduled_at <= ? AND status IN ('pending','processing') ORDER BY scheduled_at ASC LIMIT ?",
        (now, limit),
    )
    results = []
    for post in rows:
        try:
            if post["status"] == "pending":
                creation_id = create_ig_container(post)
                execute(
                    "UPDATE posts SET status=%s, creation_id=%s, error=NULL WHERE id=%s" if is_postgres()
                    else "UPDATE posts SET status=?, creation_id=?, error=NULL WHERE id=?",
                    ("processing", creation_id, post["id"]),
                )
                results.append({"id": post["id"], "status": "processing", "creation_id": creation_id})
            else:
                status = container_status(post["creation_id"])
                if status.get("status_code") == "FINISHED":
                    media_id = publish_container(post["creation_id"])
                    execute(
                        "UPDATE posts SET status=%s, ig_media_id=%s, error=NULL WHERE id=%s" if is_postgres()
                        else "UPDATE posts SET status=?, ig_media_id=?, error=NULL WHERE id=?",
                        ("published", media_id, post["id"]),
                    )
                    results.append({"id": post["id"], "status": "published", "ig_media_id": media_id})
                elif status.get("status_code") == "ERROR":
                    raise RuntimeError(status)
                else:
                    results.append({"id": post["id"], "status": status.get("status_code", "processing")})
        except Exception as e:
            execute(
                "UPDATE posts SET status=%s, error=%s WHERE id=%s" if is_postgres()
                else "UPDATE posts SET status=?, error=? WHERE id=?",
                ("error", str(e)[:1000], post["id"]),
            )
            results.append({"id": post["id"], "status": "error", "error": str(e)[:300]})
    return results


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["ok"] = True
            return redirect(url_for("index"))
        return render_template("login.html", error="Contraseña incorrecta")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/", methods=["GET"])
@login_required
def index():
    posts = query_all("SELECT * FROM posts ORDER BY scheduled_at DESC")
    return render_template("index.html", posts=posts, cron_secret=CRON_SECRET)


@app.route("/posts", methods=["POST"])
@login_required
def create_post():
    caption = request.form.get("caption", "").strip()
    scheduled_local = request.form.get("scheduled_at", "").strip()
    video = request.files.get("video")
    if not caption or not scheduled_local or not video:
        return "Faltan campos", 400

    # datetime-local llega sin zona; asumimos hora local del navegador/usuario.
    local_dt = datetime.fromisoformat(scheduled_local)
    scheduled_utc = local_dt.astimezone().astimezone(timezone.utc).isoformat()

    upload = cloudinary.uploader.upload_large(
        video,
        resource_type="video",
        folder="instagram_scheduler",
        chunk_size=6_000_000,
    )
    video_url = upload["secure_url"]
    now = datetime.now(timezone.utc).isoformat()
    execute(
        "INSERT INTO posts (caption, video_url, scheduled_at, status, created_at) VALUES (%s,%s,%s,%s,%s)" if is_postgres()
        else "INSERT INTO posts (caption, video_url, scheduled_at, status, created_at) VALUES (?,?,?,?,?)",
        (caption, video_url, scheduled_utc, "pending", now),
    )
    return redirect(url_for("index"))


@app.route("/delete/<int:post_id>", methods=["POST"])
@login_required
def delete_post(post_id):
    execute("DELETE FROM posts WHERE id=%s" if is_postgres() else "DELETE FROM posts WHERE id=?", (post_id,))
    return redirect(url_for("index"))


@app.route("/api/cron")
def cron():
    if request.args.get("secret") != CRON_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 403
    return jsonify({"ok": True, "results": process_due_posts()})


@app.route("/health")
def health():
    return "ok"


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
