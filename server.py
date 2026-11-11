#!/usr/bin/env python3
"""
pollable — Flask + sqlite3 backend
Browser calls Pollinations, then POSTs outcomes here.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "pollable.db"

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
    static_url_path="/static",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # Auto-create schema if missing (WSGI / first request)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                models_json TEXT NOT NULL DEFAULT '[]',
                answers_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_questions_created ON questions(created_at DESC)"
        )
        conn.commit()
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                models_json TEXT NOT NULL DEFAULT '[]',
                answers_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_questions_created ON questions(created_at DESC)"
        )
        conn.commit()
    finally:
        conn.close()


def list_questions(limit: int = 500) -> list[dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT id, question, models_json, answers_json, created_at
        FROM questions
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    out = []
    for row in rows:
        answers = json.loads(row["answers_json"] or "[]")
        models = json.loads(row["models_json"] or "[]")
        out.append(
            {
                "id": row["id"],
                "question": row["question"],
                "models": models,
                "answerCount": len(answers),
                "preview": [
                    {
                        "model": a.get("model"),
                        "name": a.get("name"),
                        "icon": a.get("icon"),
                        "ok": a.get("ok"),
                    }
                    for a in answers[:8]
                ],
                "at": row["created_at"],
            }
        )
    return out


def get_question(qid: str) -> dict | None:
    db = get_db()
    row = db.execute(
        """
        SELECT id, question, models_json, answers_json, created_at
        FROM questions
        WHERE id = ?
        """,
        (qid,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "question": row["question"],
        "models": json.loads(row["models_json"] or "[]"),
        "answers": json.loads(row["answers_json"] or "[]"),
        "at": row["created_at"],
    }


def insert_question(question: str, models: list, answers: list) -> str:
    qid = str(uuid.uuid4())
    created = utcnow()
    models_json = json.dumps(models)
    answers_json = json.dumps(
        [
            {
                "model": a.get("model"),
                "name": a.get("name"),
                "icon": a.get("icon"),
                "ok": bool(a.get("ok", True)),
                "text": (a.get("text") or "")[:8000],
            }
            for a in answers
        ]
    )
    db = get_db()
    db.execute(
        """
        INSERT INTO questions (id, question, models_json, answers_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (qid, question, models_json, answers_json, created),
    )
    db.commit()
    return qid


init_db()  # create tables on import (works under WSGI)

# ---------- Pages ----------

@app.get("/")
def page_index():
    return render_template("index.html")


@app.get("/questions")
def page_questions():
    return render_template("questions.html")


@app.get("/q")
def page_question():
    return render_template("question.html")


@app.get("/models.json")
def models_json():
    return send_from_directory(app.static_folder, "models.json", mimetype="application/json")


# ---------- API ----------

@app.get("/api/questions")
def api_list_questions():
    return jsonify({"questions": list_questions()})


@app.get("/api/questions/<qid>")
def api_get_question(qid: str):
    item = get_question(qid)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(item)


@app.post("/api/questions")
def api_create_question():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    models = data.get("models") or []
    answers = data.get("answers") or []

    if not question:
        return jsonify({"error": "Question is required"}), 400
    if not answers and not models:
        return jsonify({"error": "Answers or models required"}), 400

    qid = insert_question(question, models, answers)
    return jsonify({"id": qid, "ok": True}), 201


# ---------- CLI ----------

def main():
    init_db()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"pollable → http://127.0.0.1:{port}")
    print(f"sqlite3 → {DB_PATH}")
    app.run(host="0.0.0.0", port=port, debug=debug)


if __name__ == "__main__":
    main()
