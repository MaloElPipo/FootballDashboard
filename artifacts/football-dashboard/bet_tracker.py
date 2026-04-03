import json
import os
from datetime import datetime

BETS_FILE = os.path.join(os.path.dirname(__file__), "bets_tracker.json")
BANKROLL_FILE = os.path.join(os.path.dirname(__file__), "bankroll_config.json")

DEFAULT_BANKROLL = {
    "initial": 100.0,
    "unit": "€",
    "kelly_fraction": 0.25,
    "max_stake_pct": 5.0,
    "min_stake": 1.0,
}


def load_bankroll_config():
    if os.path.exists(BANKROLL_FILE):
        with open(BANKROLL_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_BANKROLL.copy()


def save_bankroll_config(config):
    with open(BANKROLL_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_bets():
    if os.path.exists(BETS_FILE):
        with open(BETS_FILE, "r") as f:
            return json.load(f)
    return []


def save_bets(bets):
    with open(BETS_FILE, "w") as f:
        json.dump(bets, f, indent=2, ensure_ascii=False)


def add_bet(match, side, odds, stake, model_prob=None, ev=None, notes=""):
    bets = load_bets()
    bet = {
        "id": len(bets) + 1,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "match": match,
        "side": side,
        "odds": round(odds, 2),
        "stake": round(stake, 2),
        "model_prob": round(model_prob, 1) if model_prob else None,
        "ev": round(ev, 1) if ev else None,
        "result": "pending",
        "notes": notes,
    }
    bets.append(bet)
    save_bets(bets)
    return bet


def update_bet_result(bet_id, result):
    bets = load_bets()
    for b in bets:
        if b["id"] == bet_id:
            b["result"] = result
            if result == "won":
                b["profit"] = round(b["stake"] * (b["odds"] - 1), 2)
            elif result == "lost":
                b["profit"] = -b["stake"]
            elif result == "void":
                b["profit"] = 0.0
            else:
                b.pop("profit", None)
            break
    save_bets(bets)


def delete_bet(bet_id):
    bets = load_bets()
    bets = [b for b in bets if b["id"] != bet_id]
    save_bets(bets)


def get_stats():
    bets = load_bets()
    config = load_bankroll_config()

    settled = [b for b in bets if b["result"] in ("won", "lost", "void")]
    pending = [b for b in bets if b["result"] == "pending"]

    total_staked = sum(b["stake"] for b in settled)
    total_profit = sum(b.get("profit", 0) for b in settled)
    wins = sum(1 for b in settled if b["result"] == "won")
    losses = sum(1 for b in settled if b["result"] == "lost")
    voids = sum(1 for b in settled if b["result"] == "void")

    roi = (total_profit / total_staked * 100) if total_staked > 0 else 0
    current_bankroll = config["initial"] + total_profit
    pending_exposure = sum(b["stake"] for b in pending)

    return {
        "total_bets": len(bets),
        "settled": len(settled),
        "pending": len(pending),
        "wins": wins,
        "losses": losses,
        "voids": voids,
        "win_rate": (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0,
        "total_staked": total_staked,
        "total_profit": total_profit,
        "roi": roi,
        "initial_bankroll": config["initial"],
        "current_bankroll": current_bankroll,
        "pending_exposure": pending_exposure,
        "available": current_bankroll - pending_exposure,
        "unit": config.get("unit", "€"),
    }


def kelly_stake(prob, odds, bankroll, fraction=0.25, max_pct=5.0, min_stake=1.0):
    b = odds - 1
    q = 1 - prob
    if b <= 0:
        return 0.0
    f = (prob * b - q) / b
    if f <= 0:
        return 0.0
    f_adj = f * fraction
    f_adj = min(f_adj, max_pct / 100)
    stake = bankroll * f_adj
    stake = max(stake, min_stake) if stake >= min_stake * 0.5 else 0.0
    return round(stake, 2)
