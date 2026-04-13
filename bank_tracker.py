import json
import os
from datetime import datetime

DATA_FILE = "data.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"friends": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Ensure older files without balance fields still work.
    for friend in data.get("friends", {}).values():
        if "balance" not in friend:
            friend["balance"] = calculate_balance(friend)
    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def format_money(amount):
    return f"{amount:.2f}"


def add_friend(data):
    name = input("Friend name: ").strip()
    if not name:
        print("Name cannot be empty.")
        return
    if name in data["friends"]:
        print("This friend already exists.")
        return
    data["friends"][name] = {"transactions": [], "balance": 0.0}
    save_data(data)
    print(f"Added friend '{name}'.")


def record_transaction(data, transaction_type):
    name = input("Friend name: ").strip()
    if not name:
        print("Name cannot be empty.")
        return
    if name not in data["friends"]:
        print("Friend not found. Add the friend first.")
        return

    try:
        amount = float(input("Amount: ").strip())
    except ValueError:
        print("Please enter a valid number.")
        return

    if amount <= 0:
        print("Amount must be greater than zero.")
        return

    note = input("Note (optional): ").strip()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    transaction = {
        "date": date_str,
        "type": transaction_type,
        "amount": amount,
        "note": note,
    }

    friend = data["friends"][name]
    friend["transactions"].append(transaction)

    if transaction_type in ("borrow", "receive"):
        friend["balance"] += amount
        verb = "received back"
    else:
        friend["balance"] -= amount
        verb = "gave"

    save_data(data)

    if transaction_type == "borrow":
        print(f"Recorded that {name} borrowed {format_money(amount)} from you.")
    elif transaction_type == "receive":
        print(f"Recorded that {name} returned {format_money(amount)} to you.")
    else:
        print(f"Recorded that you gave {format_money(amount)} to {name}.")


def calculate_balance(friend):
    if "balance" in friend:
        return friend["balance"]

    balance = 0.0
    for tx in friend["transactions"]:
        if tx["type"] in ("borrow", "receive"):
            balance += tx["amount"]
        elif tx["type"] in ("repay", "give"):
            balance -= tx["amount"]
    return balance


def view_balances(data):
    if not data["friends"]:
        print("No friends found. Add a friend first.")
        return

    print("\nCurrent balances:")
    print("-----------------")
    for name, friend in data["friends"].items():
        balance = calculate_balance(friend)
        status = "owes you" if balance > 0 else "settled" if balance == 0 else "you owe"
        print(f"{name}: {format_money(balance)} ({status})")
    print("")


def view_history(data):
    name = input("Friend name: ").strip()
    if not name:
        print("Name cannot be empty.")
        return
    if name not in data["friends"]:
        print("Friend not found.")
        return

    friend = data["friends"][name]
    if not friend["transactions"]:
        print("No transactions recorded for this friend.")
        return

    print(f"\nTransaction history for {name}:")
    print("Date                 | Type   | Amount  | Note")
    print("---------------------+--------+---------+----------------------")
    for tx in friend["transactions"]:
        print(f"{tx['date']} | {tx['type']:<6} | {format_money(tx['amount']):>7} | {tx['note']}")
    print(f"Current balance: {format_money(friend.get('balance', calculate_balance(friend)))}\n")


def delete_friend(data):
    name = input("Friend name to delete: ").strip()
    if not name:
        print("Name cannot be empty.")
        return
    if name not in data["friends"]:
        print("Friend not found.")
        return
    confirm = input(f"Are you sure you want to delete {name} and all transactions? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Deletion canceled.")
        return
    del data["friends"][name]
    save_data(data)
    print(f"Deleted friend '{name}' and all records.")


def print_menu():
    print("\n=== Loan Tracker Menu ===")
    print("1. Add friend")
    print("2. Record money you gave to friend")
    print("3. Record money friend returned to you")
    print("4. Record money friend borrowed from you")
    print("5. View all balances")
    print("6. View friend transaction history")
    print("7. Delete friend")
    print("8. Exit")


def main():
    data = load_data()
    while True:
        print_menu()
        choice = input("Choose an option: ").strip()

        if choice == "1":
            add_friend(data)
        elif choice == "2":
            record_transaction(data, "give")
        elif choice == "3":
            record_transaction(data, "receive")
        elif choice == "4":
            record_transaction(data, "borrow")
        elif choice == "5":
            view_balances(data)
        elif choice == "6":
            view_history(data)
        elif choice == "7":
            delete_friend(data)
        elif choice == "8":
            print("Goodbye!")
            break
        else:
            print("Invalid option. Please choose a number from 1 to 8.")


if __name__ == "__main__":
    main()
