from flask import Flask, request, jsonify
import json
import os
import hashlib
import time
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Store information about torrents and peers
# Structure:
# {
#   "file_id": {
#     "filename": "example.mp4",
#     "size": 123456,
#     "created_at": timestamp,
#     "chunks": 5,
#     "peers": {
#       "peer_id": {
#         "ip": "127.0.0.1",
#         "port": 5000,
#         "last_seen": timestamp,
#         "chunks": [0, 1, 2]  # Chunks this peer has
#       }
#     }
#   }
# }

# Check if the database file exists, if not create an empty one
DB_FILE = "tracker_db.json"
if not os.path.exists(DB_FILE):
    with open(DB_FILE, "w") as f:
        json.dump({}, f)

def load_db():
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

@app.route('/announce', methods=['POST'])
def announce():
    """
    Endpoint for peers to announce their presence and update their status
    """
    data = request.json
    peer_id = data.get('peer_id')
    file_id = data.get('file_id')
    ip = request.remote_addr
    port = data.get('port')
    chunks = data.get('chunks', [])
    
    if not peer_id or not file_id or not port:
        return jsonify({"error": "Missing required fields"}), 400
    
    db = load_db()
    
    # Initialize file entry if it doesn't exist
    if file_id not in db and 'filename' in data and 'size' in data and 'chunks' in data:
        db[file_id] = {
            "filename": data['filename'],
            "size": data['size'],
            "created_at": time.time(),
            "chunks": data['chunks'],
            "peers": {}
        }
    elif file_id not in db:
        return jsonify({"error": "File not found and insufficient information to create"}), 404
    
    # Update peer information
    if peer_id not in db[file_id]["peers"]:
        db[file_id]["peers"][peer_id] = {}
    
    db[file_id]["peers"][peer_id] = {
        "ip": ip,
        "port": port,
        "last_seen": time.time(),
        "chunks": chunks
    }
    
    save_db(db)
    
   
@app.route('/list', methods=['GET'])
def list_files():
    """
    List all available files in the tracker
    """
    db = load_db()
    files = {}
    
    for file_id, file_info in db.items():
        # Count active peers (seen in the last 5 minutes)
        active_peers = 0
        for peer_info in file_info["peers"].values():
            if time.time() - peer_info["last_seen"] < 300:
                active_peers += 1
        
        files[file_id] = {
            "filename": file_info["filename"],
            "size": file_info["size"],
            "chunks": file_info["chunks"],
            "active_peers": active_peers
        }
    
    return jsonify({"files": files})

@app.route('/file/<file_id>', methods=['GET'])
def get_file_info(file_id):
    """
    Get detailed information about a specific file
    """
    db = load_db()
    
    if file_id not in db:
        return jsonify({"error": "File not found"}), 404
    
    file_info = db[file_id]
    active_peers = {}
    
    for peer_id, peer_info in file_info["peers"].items():
        if time.time() - peer_info["last_seen"] < 300:
            active_peers[peer_id] = {
                "ip": peer_info["ip"],
                "port": peer_info["port"],
                "chunks": peer_info["chunks"]
            }
    
    return jsonify({
        "file_id": file_id,
        "filename": file_info["filename"],
        "size": file_info["size"],
        "chunks": file_info["chunks"],
        "peers": active_peers
    })

@app.route('/generate_file_id', methods=['POST'])
def generate_file_id():
    """
    Generate a unique file ID based on file properties
    """
    data = request.json
    filename = data.get('filename')
    size = data.get('size')
    
    if not filename or not size:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Create a unique file ID by hashing filename and size
    # In a real implementation, this would include file hash too
    unique_string = f"{filename}-{size}-{time.time()}"
    file_id = hashlib.sha256(unique_string.encode()).hexdigest()[:16]
    
    return jsonify({"file_id": file_id})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)