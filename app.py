from datetime import datetime, timedelta
import json
import os
import secrets
import socket
import sqlite3
import string
from functools import wraps
from urllib.parse import quote_plus
from werkzeug.security import check_password_hash, generate_password_hash

from flask import Flask, render_template, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "change-this-secret")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_USE_SIGNER=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
)
if os.getenv("FLASK_ENV") == "production":
    app.config["SESSION_COOKIE_SECURE"] = True

DATA_FILE = "data.json"
DATABASE_FILE = "data.db"
VALID_USERNAME = "ZEN"
VALID_PASSWORD = "zen2026"


def get_db():
    conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_json_data(data):
    users = data.get("users", {}) or {}
    legacy_friends = data.get("friends")

    if legacy_friends:
        default_user = users.setdefault(
            VALID_USERNAME,
            {"password": generate_password_hash(VALID_PASSWORD), "friends": {}},
        )
        default_user.setdefault("friends", {}).update(legacy_friends)

    orphan_users = {
        k: v
        for k, v in data.items()
        if k not in ("users", "friends") and isinstance(v, dict) and "password" in v
    }
    for username, record in orphan_users.items():
        users.setdefault(username, record)

    return users


def migrate_json_to_db(db):
    if not os.path.exists(DATA_FILE):
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    users = normalize_json_data(data)
    for username, user in users.items():
        password = user.get("password")
        if not password:
            continue
        db.execute(
            "INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)",
            (username, password),
        )

        for friend_name, friend in (user.get("friends") or {}).items():
            phone = friend.get("phone", "")
            access_code = friend.get("access_code") or generate_access_code(8)
            db.execute(
                "INSERT OR IGNORE INTO friends (username, name, phone, access_code) VALUES (?, ?, ?, ?)",
                (username, friend_name, phone, access_code),
            )
            friend_row = db.execute(
                "SELECT id FROM friends WHERE username = ? AND name = ?",
                (username, friend_name),
            ).fetchone()
            if not friend_row:
                continue
            friend_id = friend_row["id"]
            for tx in friend.get("transactions", []):
                db.execute(
                    "INSERT INTO transactions (friend_id, date, type, amount, purpose, note, payment_method) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        friend_id,
                        tx.get("date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        tx.get("type", "give"),
                        float(tx.get("amount", 0) or 0),
                        tx.get("purpose", tx.get("note", "")),
                        tx.get("note", ""),
                        tx.get("payment_method", ""),
                    ),
                )
    db.commit()


def init_db():
    with get_db() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS friends (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, name TEXT NOT NULL, phone TEXT DEFAULT '', access_code TEXT NOT NULL, UNIQUE(username, name), FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, friend_id INTEGER NOT NULL, date TEXT NOT NULL, type TEXT NOT NULL, amount REAL NOT NULL, purpose TEXT DEFAULT '', note TEXT DEFAULT '', payment_method TEXT DEFAULT '', FOREIGN KEY(friend_id) REFERENCES friends(id) ON DELETE CASCADE)"
        )
        db.commit()

        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            migrate_json_to_db(db)

        db.execute(
            "INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)",
            (VALID_USERNAME, generate_password_hash(VALID_PASSWORD)),
        )
        db.commit()


init_db()


def query_user(username):
    with get_db() as db:
        row = db.execute("SELECT username, password FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def create_user(username, password_hash):
    with get_db() as db:
        try:
            db.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password_hash),
            )
            db.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def get_user_friends(username):
    friends = []
    with get_db() as db:
        rows = db.execute(
            "SELECT id, name, phone, access_code FROM friends WHERE username = ? ORDER BY name",
            (username,),
        ).fetchall()
        for friend_row in rows:
            friend = dict(friend_row)
            friend["transactions"] = [dict(tx) for tx in db.execute(
                "SELECT date, type, amount, purpose, note, payment_method FROM transactions WHERE friend_id = ? ORDER BY date",
                (friend["id"],),
            ).fetchall()]
            friend["balance"] = calculate_balance(friend)
            friends.append(friend)
    return friends


def get_user_friend(username, name):
    with get_db() as db:
        friend_row = db.execute(
            "SELECT id, name, phone, access_code FROM friends WHERE username = ? AND name = ?",
            (username, name),
        ).fetchone()
        if not friend_row:
            return None
        friend = dict(friend_row)
        friend["transactions"] = [dict(tx) for tx in db.execute(
            "SELECT date, type, amount, purpose, note, payment_method FROM transactions WHERE friend_id = ? ORDER BY date",
            (friend["id"],),
        ).fetchall()]
        friend["balance"] = calculate_balance(friend)
        return friend


def get_friend_with_owner(name, code):
    with get_db() as db:
        row = db.execute(
            "SELECT friends.id AS id, friends.name AS name, friends.phone AS phone, friends.access_code AS access_code, users.username AS owner "
            "FROM friends JOIN users ON friends.username = users.username "
            "WHERE friends.name = ? AND friends.access_code = ?",
            (name, code),
        ).fetchone()
        if not row:
            return None, None
        friend = dict(row)
        friend["transactions"] = [dict(tx) for tx in db.execute(
            "SELECT date, type, amount, purpose, note, payment_method FROM transactions WHERE friend_id = ? ORDER BY date",
            (friend["id"],),
        ).fetchall()]
        friend["balance"] = calculate_balance(friend)
        return friend["owner"], friend


def add_friend_to_db(username, name, phone=""):
    with get_db() as db:
        access_code = generate_access_code(8)
        db.execute(
            "INSERT INTO friends (username, name, phone, access_code) VALUES (?, ?, ?, ?)",
            (username, name, phone, access_code),
        )
        db.commit()


def add_transaction_to_db(username, name, transaction_type, amount, purpose, payment_method):
    with get_db() as db:
        friend_row = db.execute(
            "SELECT id FROM friends WHERE username = ? AND name = ?",
            (username, name),
        ).fetchone()
        if not friend_row:
            return False
        friend_id = friend_row["id"]
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            "INSERT INTO transactions (friend_id, date, type, amount, purpose, note, payment_method) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (friend_id, date_str, transaction_type, amount, purpose, purpose, payment_method),
        )
        db.commit()
        return True


def delete_friend_from_db(username, name):
    with get_db() as db:
        db.execute(
            "DELETE FROM friends WHERE username = ? AND name = ?",
            (username, name),
        )
        db.commit()


def find_friend_owner(data, name, code):
    # Compatibility wrapper for older code paths.
    return get_friend_with_owner(name, code)


def is_logged_in():
    return session.get("user") is not None


def is_friend_logged_in():
    return session.get("friend_user") is not None


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.context_processor
def inject_user():
    return {
        "logged_in": is_logged_in(),
        "current_user": session.get("user"),
        "friend_logged_in": is_friend_logged_in(),
        "friend_user": session.get("friend_user"),
    }


def generate_access_code(length=6):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def calculate_balance(friend):
    if "balance" in friend:
        return friend["balance"]

    balance = 0.0
    for tx in friend["transactions"]:
        if tx["type"] in ("borrow", "receive"):
            balance += tx["amount"]
        else:
            balance -= tx["amount"]
    return balance


def format_phone_digits(phone):
    return ''.join(ch for ch in phone if ch.isdigit())


def build_phone_link(channel, phone, message):
    digits = format_phone_digits(phone)
    if not digits:
        return None
    encoded = quote_plus(message)
    if channel == "whatsapp":
        return f"https://wa.me/{digits}?text={encoded}"
    if channel == "sms":
        return f"sms:{digits}?body={encoded}"
    return None


@app.route("/")
@login_required
def index():
    friends = []
    for friend in get_user_friends(session["user"]):
        friends.append({
            "name": friend["name"],
            "phone": friend.get("phone", ""),
            "balance": friend["balance"],
            "status": "owes you" if friend["balance"] > 0 else "settled" if friend["balance"] == 0 else "you owe",
        })
    return render_template("index.html", friends=friends)


@app.route("/add-friend", methods=["POST"])
@login_required
def add_friend():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    if not name:
        flash("Friend name cannot be empty.", "error")
        return redirect(url_for("index"))

    existing = get_user_friend(session["user"], name)
    if existing:
        flash("This friend already exists.", "error")
        return redirect(url_for("index"))

    add_friend_to_db(session["user"], name, phone)
    flash(f"Added friend '{name}'.", "success")
    return redirect(url_for("index"))


@app.route("/friend/<name>")
@login_required
def friend_detail(name):
    friend = get_user_friend(session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    balance = friend["balance"]
    message_text = session.pop("message_text", None)
    if message_text is None:
        message_text = session.pop("reminder_text", None)
    return render_template(
        "friend.html",
        name=name,
        friend=friend,
        balance=balance,
        status="owes you" if balance > 0 else "settled" if balance == 0 else "you owe",
        message_text=message_text,
    )


@app.route("/friend-login", methods=["GET", "POST"])
def friend_login():
    if is_friend_logged_in():
        return redirect(url_for("friend_portal"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        owner, friend = get_friend_with_owner(name, code)
        if friend:
            session.permanent = True
            session["friend_owner"] = owner
            session["friend_user"] = name
            flash("Friend access granted.", "success")
            return redirect(url_for("friend_portal"))
        flash("Invalid name or access code.", "error")
        return redirect(url_for("friend_login"))

    return render_template("friend_login.html")


def friend_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not is_friend_logged_in():
            return redirect(url_for("friend_login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.route("/friend-portal")
@friend_required
def friend_portal():
    owner = session.get("friend_owner")
    name = session.get("friend_user")
    friend = get_user_friend(owner, name)
    if not friend:
        session.pop("friend_owner", None)
        session.pop("friend_user", None)
        return redirect(url_for("friend_login"))

    balance = friend["balance"]
    return render_template(
        "friend_portal.html",
        name=name,
        friend=friend,
        balance=balance,
        status="owes you" if balance > 0 else "settled" if balance == 0 else "you owe",
    )


@app.route("/friend-logout")
def friend_logout():
    session.pop("friend_user", None)
    session.pop("friend_owner", None)
    flash("Friend logged out.", "success")
    return redirect(url_for("friend_login"))


@app.route("/friend/<name>/transaction", methods=["POST"])
@login_required
def add_friend_transaction(name):
    friend = get_user_friend(session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    transaction_type = request.form.get("type")
    purpose = request.form.get("purpose", "").strip()
    payment_method = request.form.get("payment_method", "").strip()
    amount_text = request.form.get("amount", "0").strip()

    try:
        amount = float(amount_text)
    except ValueError:
        flash("Please enter a valid amount.", "error")
        return redirect(url_for("friend_detail", name=name))

    if amount <= 0:
        flash("Amount must be greater than zero.", "error")
        return redirect(url_for("friend_detail", name=name))

    add_transaction_to_db(session["user"], name, transaction_type, amount, purpose, payment_method)

    if transaction_type == "give":
        flash(f"Recorded that you gave {amount:.2f} to {name}.", "success")
    elif transaction_type == "receive":
        flash(f"Recorded that {name} returned {amount:.2f} to you.", "success")
    else:
        flash(f"Recorded that {name} borrowed {amount:.2f} from you.", "success")

    return redirect(url_for("friend_detail", name=name))


@app.route("/friend/<name>/delete", methods=["POST"])
@login_required
def delete_friend(name):
    friend = get_user_friend(session["user"], name)
    if friend:
        delete_friend_from_db(session["user"], name)
        flash(f"Deleted friend '{name}'.", "success")
    else:
        flash("Friend not found.", "error")
    return redirect(url_for("index"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if is_logged_in():
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = query_user(username)
        valid_user = (username == VALID_USERNAME and password == VALID_PASSWORD) or (
            user and check_password_hash(user["password"], password)
        )

        if valid_user:
            session.permanent = True
            session["user"] = username
            flash("Login successful.", "success")
            return redirect(url_for("index"))

        flash("Invalid ID or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if is_logged_in():
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not username or not password:
            flash("Please fill in both username and password.", "error")
            return redirect(url_for("signup"))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("signup"))

        if username == VALID_USERNAME:
            flash("That username is reserved.", "error")
            return redirect(url_for("signup"))

        if query_user(username):
            flash("This username is already taken.", "error")
            return redirect(url_for("signup"))

        create_user(username, generate_password_hash(password))
        session.permanent = True
        session["user"] = username
        flash("Account created and logged in successfully.", "success")
        return redirect(url_for("index"))

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/friend/<name>/reminder", methods=["POST"])
@login_required
def send_reminder(name):
    friend = get_user_friend(session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    balance = friend["balance"]
    if balance == 0:
        message_text = f"{name} has no pending balance right now."
    elif balance > 0:
        message_text = (
            f"Dear {name},\n\nYou currently owe me {balance:.2f} taka. "
            "Please pay it back as soon as possible.\n\nThank you."
        )
    else:
        message_text = (
            f"Dear {name},\n\nI have given you {abs(balance):.2f} taka. "
            "Please confirm when you can settle this.\n\nThank you."
        )

    session["message_text"] = message_text
    flash("Reminder message generated. Copy it and send to your friend.", "success")
    return redirect(url_for("friend_detail", name=name))


@app.route("/friend/<name>/balance-update", methods=["POST"])
@login_required
def send_balance_update(name):
    friend = get_user_friend(session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    balance = friend["balance"]
    if balance == 0:
        message_text = (
            f"Dear {name},\n\nYour balance is currently settled. "
            "No payment is due on either side.\n\nThank you."
        )
    elif balance > 0:
        message_text = (
            f"Dear {name},\n\nYour current outstanding balance is {balance:.2f} taka owed to me. "
            "Please let me know when you can settle it.\n\nThank you."
        )
    else:
        message_text = (
            f"Dear {name},\n\nThe current balance shows that I have given you {abs(balance):.2f} taka. "
            "Please confirm when you can return it.\n\nThank you."
        )

    session["message_text"] = message_text
    flash("Balance update message generated. Copy it and send to your friend.", "success")
    return redirect(url_for("friend_detail", name=name))


@app.route("/friend/<name>/send-via/<channel>", methods=["POST"])
@login_required
def send_via_phone(name, channel):
    friend = get_user_friend(session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    phone = friend.get("phone", "").strip()
    if not phone:
        flash("No phone number saved for this friend.", "error")
        return redirect(url_for("friend_detail", name=name))

    balance = friend["balance"]
    if balance == 0:
        message = (
            f"Dear {name},\n\nYour balance is currently settled. "
            "No payment is due on either side.\n\nThank you."
        )
    elif balance > 0:
        message = (
            f"Dear {name},\n\nYour current outstanding balance is {balance:.2f} taka owed to me. "
            "Please let me know when you can settle it.\n\nThank you."
        )
    else:
        message = (
            f"Dear {name},\n\nThe current balance shows that I have given you {abs(balance):.2f} taka. "
            "Please confirm when you can return it.\n\nThank you."
        )

    link = build_phone_link(channel, phone, message)
    if not link:
        flash("Unable to build a phone link for this number.", "error")
        return redirect(url_for("friend_detail", name=name))

    return redirect(link)


@app.route("/friend-access-info/<name>", methods=["POST"])
@login_required
def send_access_info(name):
    friend = get_user_friend(session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    host_ip = get_local_ip()
    message = (
        f"Hello {name},\n\nYou can access your ZEN balance portal with the following details:\n"
        f"Name: {name}\n"
        f"Access code: {friend.get('access_code')}\n\n"
        f"Visit: http://{host_ip}:5000/friend-login\n\nThank you."
    )

    phone = friend.get("phone", "").strip()
    if not phone:
        session["message_text"] = message
        flash("Access details generated. Copy it and send to your friend.", "success")
        return redirect(url_for("friend_detail", name=name))

    link = build_phone_link("whatsapp", phone, message)
    if not link:
        flash("Unable to build a phone link for this number.", "error")
        return redirect(url_for("friend_detail", name=name))

    return redirect(link)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
