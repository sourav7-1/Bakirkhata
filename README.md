# Bank Loan Tracker

A simple Python project to track money you and your friends exchange.

## Features

- Add friends
- Record money you gave to a friend
- Record money a friend returned to you
- Record when a friend borrowed money from you
- View current balances for each friend
- See transaction history for a friend
- Persist data in `data.json`

## Running the app

### Option 1: Web UI

1. Open a terminal in this folder.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the Flask app:

```bash
python app.py
```

4. Open `http://127.0.0.1:5000` in your browser.

5. Log in with your portal credentials.

   - ID: `ZEN`
   - Password: `zen2026`

6. To let a friend see only their own balance, send them the access code from the friend detail page and ask them to use the friend login link on your computer’s local network.

   If you share the app with someone on the same Wi-Fi, use your computer’s LAN IP address instead of `127.0.0.1`, for example:

```text
http://192.168.x.y:5000/friend-login
```

   The app now runs on all network interfaces so friends on your local network can open it.

### Option 2: Command-line

Run:

```bash
python bank_tracker.py
```

## How it works

- Positive balance means your friend owes you money.
- Negative balance means you owe your friend money.
- `give` means you gave money to the friend.
- `receive` means the friend returned money to you.
- `borrow` means the friend borrowed money from you.
- Balances are updated from all recorded transactions.
