import os
import hashlib
import requests
import json
import socket
import threading
import time
import uuid
import argparse
import logging
from flask import Flask, request, jsonify

# Initialize Flask app for peer server
app = Flask(__name__)

# Global variables
TRACKER_URL = "http://localhost:5000"
DOWNLOAD_DIR = "downloads"
UPLOAD_DIR = "uploads"
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
peer_id = str(uuid.uuid4())[:8]
peer_port = None
active_downloads = {}
shared_files = {}

# Create directories if they don't exist
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_peer_address():
    """Get the IP address of this peer"""
    # This is simplified - in real life, you would use STUN or similar to get external IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def calculate_file_id(filepath):
    """Generate a file ID based on file attributes"""
    file_size = os.path.getsize(filepath)
    filename = os.path.basename(filepath)
    
    # In a real implementation, you would include a hash of file contents
    unique_string = f"{filename}-{file_size}-{time.time()}"
    return hashlib.sha256(unique_string.encode()).hexdigest()[:16]

def split_file(filepath):
    """Split a file into chunks and return chunk info"""
    file_size = os.path.getsize(filepath)
    filename = os.path.basename(filepath)
    
    # Calculate number of chunks
    num_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    
    chunks = []
    with open(filepath, 'rb') as f:
        for i in range(num_chunks):
            chunk_data = f.read(CHUNK_SIZE)
            
            # Create a chunk file
            chunk_filename = f"{filename}.{i}"
            chunk_path = os.path.join(UPLOAD_DIR, chunk_filename)
            
            with open(chunk_path, 'wb') as chunk_file:
                chunk_file.write(chunk_data)
            
            # Add chunk info (you can also add checksums here)
            chunks.append({
                "index": i,
                "filename": chunk_filename,
                "size": len(chunk_data)
            })
    
    return {
        "filename": filename,
        "size": file_size,
        "num_chunks": num_chunks,
        "chunks": chunks
    }

def share_file(filepath):
    """Share a file by splitting it and registering with tracker"""
    if not os.path.exists(filepath):
        return {"error": f"File {filepath} does not exist"}
    
    # Split the file and get chunk info
    file_info = split_file(filepath)
    
    # Calculate file ID
    file_id = calculate_file_id(filepath)
    
    # Register with tracker
    response = requests.post(
        f"{TRACKER_URL}/announce",
        json={
            "peer_id": peer_id,
            "file_id": file_id,
            "port": peer_port,
            "filename": file_info["filename"],
            "size": file_info["size"],
            "chunks": file_info["num_chunks"]
        }
    )
    
    if response.status_code == 200:
        # Add to shared files
        shared_files[file_id] = {
            "filename": file_info["filename"],
            "size": file_info["size"],
            "chunks": list(range(file_info["num_chunks"])),
            "path": filepath
        }
        
        # Start a background thread to periodically announce to tracker
        threading.Thread(
            target=announce_periodically,
            args=(file_id, file_info["num_chunks"]),
            daemon=True
        ).start()
        
        return {
            "success": True,
            "file_id": file_id,
            "message": f"File {file_info['filename']} is now being shared"
        }
    else:
        return {"error": "Failed to register with tracker", "details": response.text}




logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

#  2025-05-26 14:32:01,234 - INFO - Announced file 1234 successfully.


logger = logging.getLogger("PeerAnnounce")


ANNOUNCE_INTERVAL = 60  # seconds (can be modified if needed)

def announce_periodically(file_id, num_chunks):
    """Periodically announce to tracker for a specific file"""
    logger.info(f"Starting periodic announcements for file: {file_id}")

    while file_id in shared_files:
        try:
            response = requests.post(
                f"{TRACKER_URL}/announce",
                json={
                    "peer_id": peer_id,
                    "file_id": file_id,
                    "port": peer_port,
                    "chunks": list(range(num_chunks))
                }
            )
            if response.status_code == 200:
                logger.info(f"Announced file {file_id} successfully.")
            else:
                logger.warning(f"Announce failed for file {file_id}: {response.status_code} {response.text}")

        except Exception as e:
            logger.error(f"Failed to announce file {file_id} to tracker: {e}")

        time.sleep(ANNOUNCE_INTERVAL)  # Announce at the configured interval

    logger.info(f"Stopped announcements for file: {file_id}")

def download_file(file_id):
    """Download a file by fetching chunks from peers"""
    # Get file info from tracker
    response = requests.get(f"{TRACKER_URL}/file/{file_id}")
    
    if response.status_code != 200:
        return {"error": "Failed to get file info from tracker"}
    
    file_info = response.json()
    filename = file_info["filename"]
    total_chunks = file_info["chunks"]
    peers = file_info["peers"]
    
    if not peers:
        return {"error": "No peers available for this file"}
    
    # Initialize download state
    download_state = {
        "filename": filename,
        "total_chunks": total_chunks,
        "downloaded_chunks": [],
        "active": True,
        "started_at": time.time()
    }
    
    active_downloads[file_id] = download_state
    
    # Start download in a background thread
    threading.Thread(
        target=download_chunks_from_peers,
        args=(file_id, download_state, peers),
        daemon=True
    ).start()
    
    return {
        "success": True,
        "file_id": file_id,
        "filename": filename,
        "total_chunks": total_chunks,
        "message": f"Started downloading {filename}"
    }

def download_chunks_from_peers(file_id, download_state, peers):
    """Download file chunks from available peers"""
    filename = download_state["filename"]
    total_chunks = download_state["total_chunks"]
    
    # Announce that we're downloading this file
    try:
        requests.post(
            f"{TRACKER_URL}/announce",
            json={
                "peer_id": peer_id,
                "file_id": file_id,
                "port": peer_port,
                "chunks": download_state["downloaded_chunks"]
            }
        )
    except:
        print(f"Failed to announce download of file {file_id} to tracker")
    
    # For each chunk, find a peer that has it and download
    for chunk_index in range(total_chunks):
        # If download was cancelled
        if not download_state["active"]:
            return
        
        # Check if we already have this chunk
        if chunk_index in download_state["downloaded_chunks"]:
            continue
        
        # Find a peer with this chunk
        chunk_downloaded = False
        for p_id, peer_info in peers.items():
            if chunk_index in peer_info["chunks"]:
                try:
                    # Request the chunk from the peer
                    peer_url = f"http://{peer_info['ip']}:{peer_info['port']}/chunk"
                    response = requests.get(
                        peer_url,
                        params={"file_id": file_id, "chunk_index": chunk_index},
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        # Save the chunk
                        chunk_path = os.path.join(DOWNLOAD_DIR, f"{filename}.{chunk_index}")
                        with open(chunk_path, 'wb') as f:
                            f.write(response.content)
                        
                        # Update download state
                        download_state["downloaded_chunks"].append(chunk_index)
                        print(f"Downloaded chunk {chunk_index+1}/{total_chunks} of {filename}")
                        chunk_downloaded = True
                        
                        # Announce our new chunk to the tracker
                        try:
                            requests.post(
                                f"{TRACKER_URL}/announce",
                                json={
                                    "peer_id": peer_id,
                                    "file_id": file_id,
                                    "port": peer_port,
                                    "chunks": download_state["downloaded_chunks"]
                                }
                            )
                        except:
                            print(f"Failed to announce new chunk to tracker")
                        
                        break
                except Exception as e:
                    print(f"Failed to download chunk {chunk_index} from peer {p_id}: {e}")
        
        if not chunk_downloaded:
            print(f"Failed to download chunk {chunk_index}. Will retry later.")
            time.sleep(5)  # Wait a bit and retry
            
            # Update peers list
            try:
                response = requests.get(f"{TRACKER_URL}/file/{file_id}")
                if response.status_code == 200:
                    peers = response.json()["peers"]
            except:
                print("Failed to update peers list from tracker")
    
    # Check if all chunks downloaded
    if len(download_state["downloaded_chunks"]) == total_chunks:
        # Merge chunks into the final file
        merge_chunks(filename, total_chunks)
        
        # Update shared files (we now have the complete file)
        shared_files[file_id] = {
            "filename": filename,
            "size": os.path.getsize(os.path.join(DOWNLOAD_DIR, filename)),
            "chunks": list(range(total_chunks)),
            "path": os.path.join(DOWNLOAD_DIR, filename)
        }
        
        print(f"Download of {filename} completed!")

def merge_chunks(filename, total_chunks):
    """Merge downloaded chunks into a single file"""
    output_path = os.path.join(DOWNLOAD_DIR, filename)
    
    with open(output_path, 'wb') as outfile:
        for i in range(total_chunks):
            chunk_path = os.path.join(DOWNLOAD_DIR, f"{filename}.{i}")
            if os.path.exists(chunk_path):
                with open(chunk_path, 'rb') as chunk_file:
                    outfile.write(chunk_file.read())
    
    # Optionally, clean up chunk files
    for i in range(total_chunks):
        chunk_path = os.path.join(DOWNLOAD_DIR, f"{filename}.{i}")
        if os.path.exists(chunk_path):
            os.remove(chunk_path)

def cancel_download(file_id):
    """Cancel an active download"""
    if file_id in active_downloads:
        active_downloads[file_id]["active"] = False
        return {"success": True, "message": f"Download of {active_downloads[file_id]['filename']} cancelled"}
    else:
        return {"error": "Download not found"}

@app.route('/chunk', methods=['GET'])
def serve_chunk():
    """Serve a chunk of a file to another peer"""
    file_id = request.args.get('file_id')
    chunk_index = int(request.args.get('chunk_index', 0))
    
    if file_id not in shared_files:
        return jsonify({"error": "File not found"}), 404
    
    file_info = shared_files[file_id]
    filename = file_info["filename"]
    
    # Check if this is a complete file or just chunks
    if os.path.exists(file_info["path"]):
        # Complete file - read the specific chunk
        with open(file_info["path"], 'rb') as f:
            f.seek(chunk_index * CHUNK_SIZE)
            chunk_data = f.read(CHUNK_SIZE)
    else:
        # We have chunks - serve the specific chunk file
        chunk_path = os.path.join(UPLOAD_DIR, f"{filename}.{chunk_index}")
        if not os.path.exists(chunk_path):
            return jsonify({"error": "Chunk not found"}), 404
        
        with open(chunk_path, 'rb') as f:
            chunk_data = f.read()
    
    return chunk_data

@app.route('/status', methods=['GET'])
def get_status():
    """Get status of shared files and active downloads"""
    return jsonify({
        "peer_id": peer_id,
        "shared_files": shared_files,
        "active_downloads": active_downloads
    })

def start_peer_server(port):
    """Start the peer server"""
    global peer_port
    peer_port = port
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    print(f"Peer server started on port {port}")

def print_help():
    """Print CLI usage help"""
    print("\n--- Mini-Torrent Peer Client ---")
    print("Commands:")
    print("  list              - List available files from tracker")
    print("  download [id]     - Download a file by ID")
    print("  share [path]      - Share a file from local storage")
    print("  status            - Show status of downloads and shared files")
    print("  cancel [id]       - Cancel an active download")
    print("  help              - Show this help message")
    print("  exit              - Exit the client")

def cli():
    """Simple command-line interface for the peer"""
    print_help()
    
    while True:
        try:
            cmd = input("\n> ").strip().split()
            
            if not cmd:
                continue
            
            if cmd[0] == "exit":
                break
            
            elif cmd[0] == "help":
                print_help()
            
            elif cmd[0] == "list":
                try:
                    response = requests.get(f"{TRACKER_URL}/list")
                    
                    if response.status_code == 200:
                        files = response.json()["files"]
                        
                        if not files:
                            print("No files available")
                        else:
                            print("\nAvailable files:")
                            print("-" * 60)
                            print(f"{'ID':<18} {'Filename':<30} {'Size':<10} {'Peers'}")
                            print("-" * 60)
                            
                            for file_id, file_info in files.items():
                                size_str = f"{file_info['size'] / (1024*1024):.2f} MB"
                                print(f"{file_id:<18} {file_info['filename']:<30} {size_str:<10} {file_info['active_peers']}")
                    else:
                        print(f"Error getting file list: {response.text}")
                except Exception as e:
                    print(f"Error connecting to tracker: {e}")
            
            elif cmd[0] == "download":
                if len(cmd) < 2:
                    print("Usage: download [file_id]")
                    continue
                
                file_id = cmd[1]
                result = download_file(file_id)
                
                if "error" in result:
                    print(f"Error: {result['error']}")
                else:
                    print(f"Started downloading {result['filename']} ({result['total_chunks']} chunks)")
            
            elif cmd[0] == "share":
                if len(cmd) < 2:
                    print("Usage: share [filepath]")
                    continue
                
                filepath = cmd[1]
                result = share_file(filepath)
                
                if "error" in result:
                    print(f"Error: {result['error']}")
                else:
                    print(f"Sharing file: {result['message']}")
                    print(f"File ID: {result['file_id']}")
            
            elif cmd[0] == "status":
                print("\nShared Files:")
                if not shared_files:
                    print("  No files being shared")
                else:
                    for file_id, info in shared_files.items():
                        print(f"  {info['filename']} (ID: {file_id})")
                
                print("\nActive Downloads:")
                if not active_downloads:
                    print("  No active downloads")
                else:
                    for file_id, info in active_downloads.items():
                        progress = len(info["downloaded_chunks"]) / info["total_chunks"] * 100
                        print(f"  {info['filename']} - {progress:.1f}% ({len(info['downloaded_chunks'])}/{info['total_chunks']} chunks)")
            
            elif cmd[0] == "cancel":
                if len(cmd) < 2:
                    print("Usage: cancel [file_id]")
                    continue
                
                file_id = cmd[1]
                result = cancel_download(file_id)
                
                if "error" in result:
                    print(f"Error: {result['error']}")
                else:
                    print(result["message"])
            
            else:
                print(f"Unknown command: {cmd[0]}")
                print_help()
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
    
    print("Exiting peer client")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='P2P File Sharing Peer')
    parser.add_argument('--port', type=int, default=8001, help='Port to run the peer server on')
    parser.add_argument('--tracker', type=str, default='http://localhost:5000', help='Tracker URL')
    
    args = parser.parse_args()
    TRACKER_URL = args.tracker
    
    # Start the peer server
    start_peer_server(args.port)
    
    # Start the CLI
    cli()
