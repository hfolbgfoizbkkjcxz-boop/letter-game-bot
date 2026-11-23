import os
import random
import string
import requests
from flask import Flask, request, jsonify

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-this-secret").strip()
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
API = f"https://api.telegram.org/bot{TOKEN}"

app = Flask(__name__)
games = {}       # in-memory: resets if service restarts
players_state = {}  # user_id -> solo/game state

LETTERS = list("ابتثجحخدذرزسشصضطظعغفقكلمنهوي")
CATEGORIES = ["حيوان", "إنسان", "نبات", "جماد", "بلاد"]

def tg(method, **data):
    if not TOKEN:
        return {"ok": False, "description": "BOT_TOKEN is missing"}
    try:
        return requests.post(f"{API}/{method}", json=data, timeout=20).json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

def send(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text}
    if keyboard:
        data["reply_markup"] = {"inline_keyboard": keyboard}
    return tg("sendMessage", **data)

def main_menu(chat_id):
    send(chat_id, "🎮 لعبة حيوان إنسان نبات جماد بلاد\nاختاري شلون تريدين تلعبين:",
         [[{"text": "🎲 لعب فردي", "callback_data": "solo"},
           {"text": "👥 تحدي صديقة", "callback_data": "challenge"}]])

def make_round(game_id=None):
    return random.choice(LETTERS)

def answer_prompt(letter):
    return (f"🔤 حرف الجولة: {letter}\n\n"
            "اكتبي 5 إجابات برسالة وحدة، كل جواب بسطر وبالترتيب:\n"
            "🐾 حيوان\n👤 إنسان\n🌿 نبات\n🧱 جماد\n🌍 بلاد\n\n"
            "مثال: سمكة / سارة / سبانخ / سيارة / سوريا")

def score_answers(letter, text):
    answers = [x.strip() for x in text.replace("/", "\n").replace(",", "\n").splitlines() if x.strip()]
    answers = answers[:5]
    score = 0
    detail = []
    for i, cat in enumerate(CATEGORIES):
        ans = answers[i] if i < len(answers) else ""
        ok = bool(ans) and ans[0].replace("أ", "ا").replace("إ", "ا").replace("آ", "ا") == letter.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        points = 10 if ok else 0
        score += points
        detail.append(f"{'✅' if ok else '❌'} {cat}: {ans or '—'} ({points})")
    return score, "\n".join(detail)

@app.route("/")
def home():
    return "Letter Game Bot is running."

@app.route("/setup")
def setup_webhook():
    if request.args.get("secret") != WEBHOOK_SECRET:
        return "Forbidden", 403
    if not BASE_URL:
        return "RENDER_EXTERNAL_URL is missing", 500
    url = f"{BASE_URL}/webhook/{WEBHOOK_SECRET}"
    result = tg("setWebhook", url=url, allowed_updates=["message", "callback_query"])
    return jsonify(result)

@app.route("/webhook/<secret>", methods=["POST"])
def webhook(secret):
    if secret != WEBHOOK_SECRET:
        return "Forbidden", 403
    update = request.get_json(force=True, silent=True) or {}
    try:
        if "message" in update:
            handle_message(update["message"])
        elif "callback_query" in update:
            handle_callback(update["callback_query"])
    except Exception as e:
        print("Update handling error:", e)
    return "ok"

def handle_message(msg):
    chat_id = msg.get("chat", {}).get("id")
    user = msg.get("from", {})
    user_id = user.get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id or not user_id:
        return
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1] if len(parts) > 1 else ""
        if payload.startswith("join_"):
            join_game(chat_id, user, payload[5:])
        else:
            players_state.pop(user_id, None)
            main_menu(chat_id)
        return
    state = players_state.get(user_id)
    if not state:
        send(chat_id, "اضغطي /start حتى تبدين اللعبة.")
        return
    if state.get("mode") == "solo":
        letter = state["letter"]
        score, detail = score_answers(letter, text)
        players_state.pop(user_id, None)
        send(chat_id, f"📋 نتيجتج:\n{detail}\n\n🏆 مجموعج: {score}/50")
        main_menu(chat_id)
    elif state.get("mode") == "game":
        game = games.get(state["game_id"])
        if not game:
            send(chat_id, "الجولة انتهت أو انحذفت. اضغطي /start.")
            return
        if user_id in game["scores"]:
            send(chat_id, "إجابتج مسجلة بهالجولة بالفعل.")
            return
        score, detail = score_answers(game["letter"], text)
        game["scores"][user_id] = score
        game["details"][user_id] = detail
        game["names"][user_id] = display_name(user)
        send(chat_id, f"📋 نتيجتج:\n{detail}\n\n🏆 مجموعج: {score}/50")
        if len(game["scores"]) >= len(game["players"]):
            result = "🏁 انتهت الجولة!\n\n"
            for pid in game["players"]:
                result += f"👤 {game['names'].get(pid, game['players'][pid])}: {game['scores'].get(pid, 0)}/50\n"
            max_score = max(game["scores"].values())
            winners = [game["names"].get(pid, game["players"][pid]) for pid, sc in game["scores"].items() if sc == max_score]
            result += "\n🏆 الفائز: " + " و ".join(winners)
            for pid in game["players"]:
                send(pid, result)
                players_state.pop(pid, None)
            games.pop(state["game_id"], None)

def display_name(user):
    return user.get("first_name") or user.get("username") or "لاعب"

def handle_callback(query):
    user = query.get("from", {})
    user_id = user.get("id")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    data = query.get("data", "")
    tg("answerCallbackQuery", callback_query_id=query.get("id"))
    if data == "solo":
        letter = make_round()
        players_state[user_id] = {"mode": "solo", "letter": letter}
        send(chat_id, answer_prompt(letter))
    elif data == "challenge":
        game_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=7))
        game = {"players": {user_id: display_name(user)}, "scores": {}, "details": {}, "names": {},
                "letter": make_round(), "creator": user_id}
        games[game_id] = game
        players_state[user_id] = {"mode": "game", "game_id": game_id}
        deep_link = f"https://t.me/{get_bot_username()}?start=join_{game_id}"
        send(chat_id, "🎯 تحدي صديقة!\nدزي رابط الدعوة لصديقتج، من تدخل تبدأ الجولة:\n" + deep_link,
             [[{"text": "📤 مشاركة الدعوة", "url": f"https://t.me/share/url?url={deep_link}&text=تعالي نلعب حروف وياي 🎮"}]])
    elif data.startswith("unused"):
        pass

def get_bot_username():
    cached = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
    if cached:
        return cached
    result = tg("getMe")
    if result.get("ok"):
        return result["result"]["username"]
    return "YOUR_BOT_USERNAME"

def join_game(chat_id, user, game_id):
    game = games.get(game_id)
    if not game:
        send(chat_id, "الرابط انتهى أو الجولة مو موجودة. خلي صديقتج تسوي تحدي جديد.")
        main_menu(chat_id)
        return
    user_id = user.get("id")
    if user_id == game["creator"]:
        send(chat_id, "إنتِ صاحبة التحدي! دزي الرابط لصديقتج حتى تدخل.")
        return
    if user_id not in game["players"]:
        game["players"][user_id] = display_name(user)
    players_state[user_id] = {"mode": "game", "game_id": game_id}
    letter = game["letter"]
    text = "🎮 دخلتِ التحدي! الحرف هو:\n\n" + answer_prompt(letter)
    for pid in game["players"]:
        players_state[pid] = {"mode": "game", "game_id": game_id}
        send(pid, text if pid == user_id else f"🎉 صديقتج دخلت التحدي!\n\n" + answer_prompt(letter))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
