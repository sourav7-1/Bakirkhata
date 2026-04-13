# ZEN Bank Tracker

A simple Flask-based money tracker to manage personal friend balances and payments.
The app stores per-user friend data and supports both account login and limited friend access.

## What it does

- Create a secure user account
- Add friends and save phone numbers
- Track money given, returned, or borrowed
- View live balance status per friend
- Send quick reminder/balance messages
- Friend access via a unique access code

## Tech stack

- Python 3
- Flask
- Jinja2 templates
- JSON file storage (`data.json`)

## Setup

1. Open a terminal inside this project folder.
2. Install the dependency:

```bash
pip install -r requirements.txt
```

3. Run the app:

```bash
python app.py
```

4. Open your browser at:

```text
http://127.0.0.1:5000
```

---

## Deploying to Render

This project is ready for Render deployment using `gunicorn`.

- A `Procfile` is included:

```text
web: gunicorn app:app --log-file -
```

- When deploying, Render can use the local SQLite database file `data.db` by default.
- If you want to override the database location, set the environment variable `DATABASE_FILE` or `DATABASE_URL`.

For local development, the app still runs with `python app.py`.

## Usage

### Admin / owner login

- Click `Login` or `Sign up`
- Existing owner credentials:
  - Username: `ZEN`
  - Password: `zen2026`

### Register a new account

- Go to `Sign up`
- Create a username and password
- You will get a private account with your own friend list

### Friend access

- Add a friend from your dashboard
- Open the friend detail page and share the access code with them
- Friend uses `Friend login` and enters their name + code
- They only see their own balance and history

## Notes

- User accounts are isolated: one account cannot see another account's friends.
- The app currently stores data in `data.json`.
- For local network friend access, use your machine's LAN IP instead of `127.0.0.1`.

## Optional command-line helper

If you want a terminal-based balance helper, use:

```bash
python bank_tracker.py
```

## Screenshots

The app provides a clean login page, a private user dashboard with friend balances, and a friend-only portal with individual transaction history.

> Add your own screenshots here once the app UI is ready.

## Future improvements

- Add a proper database backend (SQLite or PostgreSQL)
- Improve authentication with email/password reset support
- Add pagination and search for friends
- Add export to CSV or PDF for transaction history
- Add better mobile responsive layout

## License

Feel free to use and adapt this project for personal tracking.
