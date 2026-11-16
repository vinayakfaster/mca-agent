import json
import os
import time

DB_FILE = "wallet_data.json"

def _load_db():
    if not os.path.exists(DB_FILE):
        return {"balance": 10.0, "transactions": []}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def _save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_balance():
    data = _load_db()
    return {"balance": data["balance"]}

def get_pricing():
    return {
        "pricing": [
            {"feature": "Study Companion (PDF Upload)", "price": 0.05, "desc": "Upload and index a PDF"},
            {"feature": "Data Analysis (Charts & SQL)", "price": 0.10, "desc": "Generate charts or run SQL"},
            {"feature": "Code Documentation (Analyze/Write)", "price": 0.05, "desc": "Analyze code or add docstrings"},
            {"feature": "Real-time Info (Weather, etc.)", "price": 0.02, "desc": "Fetch real-time data via Chat"}
        ]
    }

def deduct_payment(feature_name: str, amount: float) -> dict:
    data = _load_db()
    
    if data["balance"] < amount:
        return {"success": False, "message": f"Insufficient balance. You need {amount} USDC but have {data['balance']} USDC."}
    
    data["balance"] -= amount
    data["transactions"].append({
        "id": f"txn_{int(time.time())}",
        "feature": feature_name,
        "amount": amount,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "Success"
    })
    _save_db(data)
    return {"success": True, "message": f"{amount} USDC deducted for '{feature_name}'.", "new_balance": data["balance"]}

def get_transactions():
    data = _load_db()
    # Return latest first
    return {"transactions": data["transactions"][::-1]}

def reset_wallet():
    _save_db({"balance": 10.0, "transactions": []})
    return {"message": "Wallet reset to 10.0 USDC"}