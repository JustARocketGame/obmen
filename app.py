from flask import Flask, jsonify

app = Flask(__name__)

clients_template = {"username": {"PC_NAME": "abc123", "RAM": "6", "Succes": True}}
clients = {}

@app.route("/")
def index():
    return jsonify({"Succes": False, "Error": "Acces Denied"})

@app.route("/clients/")
def getClients():
    return jsonify(clients)

@app.route("/client/<client>/")
def getClient(client):
    return jsonify(clients.get(client, {"Succes": False}))

if __name__ == "__main__":
    app.run(debug=True)
