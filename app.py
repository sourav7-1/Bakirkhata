from datetime import datetime, timedelta
import json
import os
import secrets
import socket
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
VALID_USERNAME = "ZEN"
VALID_PASSWORD = "zen2026"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    legacy_friends = data.pop("friends", None)
    data.setdefault("users", {})

    if legacy_friends:
        default_user = data.setdefault(VALID_USERNAME, {"password": generate_password_hash(VALID_PASSWORD), "friends": {}})
        default_user.setdefault("friends", {}).update(legacy_friends)

    for user in data["users"].values():
        user.setdefault("friends", {})
        for friend in user.get("friends", {}).values():
            if "balance" not in friend:
                friend["balance"] = calculate_balance(friend)
            if "phone" not in friend:
                friend["phone"] = ""
            if "access_code" not in friend:
                friend["access_code"] = generate_access_code()
            for tx in friend.get("transactions", []):
                if "purpose" not in tx:
                    tx["purpose"] = tx.get("note", "")
                if "payment_method" not in tx:
                    tx["payment_method"] = ""
    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_user_record(data, username, create=False):
    user = data["users"].get(username)
    if user is None and create:
        user = data["users"][username] = {"password": "", "friends": {}}
    if user is not None:
        user.setdefault("friends", {})
    return user


def get_user_friend(data, username, name):
    user = get_user_record(data, username)
    if not user:
        return None
    return user["friends"].get(name)


def find_friend_owner(data, name, code):
    for owner, user in data.get("users", {}).items():
        friend = user.get("friends", {}).get(name)
        if friend and friend.get("access_code") == code:
            return owner, friend
    return None, None


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


def add_friend_to_data(data, username, name, phone=""):
    user = get_user_record(data, username, create=True)
    user["friends"][name] = {
        "transactions": [],
        "balance": 0.0,
        "phone": phone,
        "access_code": generate_access_code(8),
    }
    save_data(data)


def add_transaction(data, username, name, transaction_type, amount, purpose, payment_method):
    friend = get_user_friend(data, username, name)
    if not friend:
        return

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    transaction = {
        "date": date_str,
        "type": transaction_type,
        "amount": amount,
        "purpose": purpose,
        "payment_method": payment_method,
        "note": purpose,
    }
    friend["transactions"].append(transaction)

    if transaction_type in ("borrow", "receive"):
        friend["balance"] += amount
    else:
        friend["balance"] -= amount

    save_data(data)


@app.route("/")
@login_required
def index():
    data = load_data()
    user = get_user_record(data, session["user"], create=True)
    friends = []
    for name, friend in sorted(user["friends"].items()):
        friends.append({
            "name": name,
            "phone": friend.get("phone", ""),
            "balance": calculate_balance(friend),
            "status": "owes you" if calculate_balance(friend) > 0 else "settled" if calculate_balance(friend) == 0 else "you owe",
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

    data = load_data()
    user = get_user_record(data, session["user"], create=True)
    if name in user["friends"]:
        flash("This friend already exists.", "error")
        return redirect(url_for("index"))

    add_friend_to_data(data, session["user"], name, phone)
    flash(f"Added friend '{name}'.", "success")
    return redirect(url_for("index"))


@app.route("/friend/<name>")
@login_required
def friend_detail(name):
    data = load_data()
    friend = get_user_friend(data, session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    balance = calculate_balance(friend)
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
        data = load_data()
        owner, friend = find_friend_owner(data, name, code)
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
    data = load_data()
    friend = data.get("users", {}).get(owner, {}).get("friends", {}).get(name)
    if not friend:
        session.pop("friend_owner", None)
        session.pop("friend_user", None)
        return redirect(url_for("friend_login"))

    balance = calculate_balance(friend)
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
    data = load_data()
    friend = get_user_friend(data, session["user"], name)
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

    add_transaction(data, session["user"], name, transaction_type, amount, purpose, payment_method)

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
    data = load_data()
    user = get_user_record(data, session["user"])
    if user and name in user["friends"]:
        del user["friends"][name]
        save_data(data)
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
        data = load_data()
        user = data["users"].get(username)
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

        data = load_data()
        if username in data["users"]:
            flash("This username is already taken.", "error")
            return redirect(url_for("signup"))

        data["users"][username] = {
            "password": generate_password_hash(password),
            "friends": {}
        }
        save_data(data)
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
    data = load_data()
    friend = get_user_friend(data, session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    balance = calculate_balance(friend)
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
    data = load_data()
    friend = get_user_friend(data, session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    balance = calculate_balance(friend)
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
    data = load_data()
    friend = get_user_friend(data, session["user"], name)
    if not friend:
        flash("Friend not found.", "error")
        return redirect(url_for("index"))

    phone = friend.get("phone", "").strip()
    if not phone:
        flash("No phone number saved for this friend.", "error")
        return redirect(url_for("friend_detail", name=name))

    balance = calculate_balance(friend)
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
    data = load_data()
    friend = get_user_friend(data, session["user"], name)
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
