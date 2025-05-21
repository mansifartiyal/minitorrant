document.addEventListener('DOMContentLoaded', function() {
    // Constants and configuration
    const TRACKER_URL = 'http://localhost:5000';
    const CHUNK_SIZE = 1024 * 1024; // 1MB chunks (should match server setting)
    let currentPeerId = generatePeerId();
    let peerPort = 8000; // Default port, could be made configurable
    let sharedFiles = {};
    let activeDownloads = {};
    let peerServer = null;

    // DOM Elements
    const peerIdEl = document.getElementById('peer-id');
    const connectionStatusEl = document.getElementById('connection-status');
    const fileListEl = document.getElementById('file-list').querySelector('tbody');
    const noFilesMessageEl = document.getElementById('no-files-message');
    const loadingFilesEl = document.getElementById('loading-files');
    const refreshFilesButton = document.getElementById('refresh-files');
    const uploadForm = document.getElementById('upload-form');
    const fileInput = document.getElementById('file-input');
    const uploadArea = document.getElementById('upload-area');
    const uploadButton = document.getElementById('upload-button');
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');
    const noDownloadsMessageEl = document.getElementById('no-downloads-message');
    const noSharingMessageEl = document.getElementById('no-sharing-message');
    const downloadsListEl = document.getElementById('downloads-list');
    const sharingListEl = document.getElementById('sharing-list');

    // Initialize UI
    peerIdEl.textContent = currentPeerId;
    
    // Check tracker connection
    checkTrackerConnection();
    
    // Event listeners
    refreshFilesButton.addEventListener('click', fetchAvailableFiles);
    
    uploadForm.addEventListener('submit', function(e) {
        e.preventDefault();
        if (fileInput.files.length > 0) {
            shareFile(fileInput.files[0]);
        }
    });
    
    fileInput.addEventListener('change', function() {
        if (fileInput.files.length > 0) {
            uploadButton.disabled = false;
            const fileName = fileInput.files[0].name;
            uploadArea.querySelector('p').textContent = fileName;
        } else {
            uploadButton.disabled = true;
            uploadArea.querySelector('p').textContent = 'Drag & drop a file or click to upload';
        }
    });
    
    // Drag and drop handling for upload area
    uploadArea.addEventListener('dragover', function(e) {
        e.preventDefault();
        uploadArea.classList.add('drag-over');
    });
    
    uploadArea.addEventListener('dragleave', function() {
        uploadArea.classList.remove('drag-over');
    });
    
    uploadArea.addEventListener('drop', function(e) {
        e.preventDefault();
        uploadArea.classList.remove('drag-over');
        
        if (e.dataTransfer.files.length > 0) {
            fileInput.files = e.dataTransfer.files;
            if (fileInput.files.length > 0) {
                uploadButton.disabled = false;
                const fileName = fileInput.files[0].name;
                uploadArea.querySelector('p').textContent = fileName;
            }
        }
    });
    
    // Tab switching
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            // Remove active class from all buttons and contents
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));
            
            // Add active class to clicked button and corresponding content
            button.classList.add('active');
            const tabId = button.getAttribute('data-tab');
            document.getElementById(tabId).classList.add('active');
        });
    });
    
    // Functions
    
    // Generate a random peer ID
    function generatePeerId() {
        return Math.random().toString(36).substring(2, 10);
    }
    
    // Check tracker connection
    function checkTrackerConnection() {
        fetch(`${TRACKER_URL}/list`)
            .then(response => {
                if (response.ok) {
                    connectionStatusEl.textContent = 'Connected';
                    connectionStatusEl.parentElement.classList.remove('disconnected');
                    connectionStatusEl.parentElement.classList.add('connected');
                    fetchAvailableFiles();
                    // Start announcements for any shared files
                    startPeriodicAnnouncements();
                    return response.json();
                } else {
                    throw new Error('Tracker connection failed');
                }
            })
            .catch(error => {
                connectionStatusEl.textContent = 'Disconnected';
                connectionStatusEl.parentElement.classList.remove('connected');
                connectionStatusEl.parentElement.classList.add('disconnected');
                showToast('Cannot connect to tracker server. Please make sure it\'s running.', 'error');
                console.error('Error connecting to tracker:', error);
            });
    }
    
    // Fetch available files from tracker
    function fetchAvailableFiles() {
        loadingFilesEl.classList.remove('hidden');
        noFilesMessageEl.classList.add('hidden');
        fileListEl.innerHTML = '';
        
        fetch(`${TRACKER_URL}/list`)
            .then(response => response.json())
            .then(data => {
                loadingFilesEl.classList.add('hidden');
                
                if (Object.keys(data.files).length === 0) {
                    noFilesMessageEl.classList.remove('hidden');
                } else {
                    noFilesMessageEl.classList.add('hidden');
                    
                    for (const [fileId, fileInfo] of Object.entries(data.files)) {
                        const row = document.createElement('tr');
                        
                        // Format file size
                        const sizeInMB = (fileInfo.size / (1024 * 1024)).toFixed(2);
                        
                        row.innerHTML = `
                            <td>${fileInfo.filename}</td>
                            <td>${sizeInMB} MB</td>
                            <td>${fileInfo.active_peers}</td>
                            <td>
                                <button class="action-button download-button" data-file-id="${fileId}">
                                    Download
                                </button>
                            </td>
                        `;
                        
                        fileListEl.appendChild(row);
                    }
                    
                    // Add event listeners to download buttons
                    document.querySelectorAll('.download-button').forEach(button => {
                        button.addEventListener('click', function() {
                            const fileId = this.getAttribute('data-file-id');
                            downloadFile(fileId);
                        });
                    });
                }
            })
            .catch(error => {
                loadingFilesEl.classList.add('hidden');
                noFilesMessageEl.classList.remove('hidden');
                noFilesMessageEl.querySelector('p').textContent = 'Error loading files';
                showToast('Failed to load file list from tracker', 'error');
                console.error('Error fetching file list:', error);
            });
    }
    
    // Share a file
    function shareFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        
        // First, generate a file ID
        fetch(`${TRACKER_URL}/generate_file_id`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                filename: file.name,
                size: file.size
            })
        })
        .then(response => response.json())
        .then(data => {
            const fileId = data.file_id;
            
            // Split the file into chunks
            splitFile(file, fileId)
                .then(fileInfo => {
                    // Announce file to tracker
                    return fetch(`${TRACKER_URL}/announce`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            peer_id: currentPeerId,
                            file_id: fileId,
                            port: peerPort,
                            filename: file.name,
                            size: file.size,
                            chunks: fileInfo.numChunks,
                            chunks: Array.from(Array(fileInfo.numChunks).keys()) // Array of chunk indices
                        })
                    });
                })
                .then(response => response.json())
                .then(data => {
                    // Add to shared files
                    sharedFiles[fileId] = {
                        filename: file.name,
                        size: file.size,
                        chunks: Array.from(Array(Math.ceil(file.size / CHUNK_SIZE)).keys()),
                        path: URL.createObjectURL(file) // Store file as blob URL
                    };
                    
                    // Update UI
                    updateSharedFilesUI();
                    
                    // Reset upload form
                    uploadForm.reset();
                    uploadArea.querySelector('p').textContent = 'Drag & drop a file or click to upload';
                    uploadButton.disabled = true;
                    
                    // Show success message
                    showToast(`File "${file.name}" is now being shared`, 'success');
                    
                    // Refresh file list
                    fetchAvailableFiles();
                })
                .catch(error => {
                    showToast('Failed to share file', 'error');
                    console.error('Error sharing file:', error);
                });
        })
        .catch(error => {
            showToast('Failed to generate file ID', 'error');
            console.error('Error generating file ID:', error);
        });
    }
    
    // Split file into chunks
    function splitFile(file, fileId) {
        return new Promise((resolve, reject) => {
            const numChunks = Math.ceil(file.size / CHUNK_SIZE);
            const chunkInfos = [];
            
            for (let i = 0; i < numChunks; i++) {
                const start = i * CHUNK_SIZE;
                const end = Math.min(file.size, start + CHUNK_SIZE);
                const chunk = file.slice(start, end);
                
                // In a real implementation, you would save these chunks to storage
                // Here, we're just storing references to file slices
                chunkInfos.push({
                    index: i,
                    size: chunk.size
                });
                
                // Store in browser storage (IndexedDB would be better for larger files)
                localStorage.setItem(`${fileId}_chunk_${i}`, URL.createObjectURL(chunk));
            }
            
            resolve({
                filename: file.name,
                size: file.size,
                numChunks: numChunks,
                chunks: chunkInfos
            });
        });
    }
    
    // Download a file
    function downloadFile(fileId) {
        // Get file info from tracker
        fetch(`${TRACKER_URL}/file/${fileId}`)
            .then(response => response.json())
            .then(fileInfo => {
                const filename = fileInfo.filename;
                const totalChunks = fileInfo.chunks;
                const peers = fileInfo.peers;
                
                if (Object.keys(peers).length === 0) {
                    showToast('No peers available for this file', 'error');
                    return;
                }
                
                // Initialize download state
                const downloadState = {
                    fileId: fileId,
                    filename: filename,
                    totalChunks: totalChunks,
                    downloadedChunks: [],
                    active: true,
                    startedAt: Date.now(),
                    progress: 0
                };
                
                activeDownloads[fileId] = downloadState;
                
                // Update UI
                updateDownloadsUI();
                
                // Show toast
                showToast(`Started downloading "${filename}"`, 'success');
                
                // In a real implementation, this would start downloading chunks from peers
                // For this simplified example, we'll simulate it
                simulateChunkDownload(downloadState, peers);
                
                // Announce to tracker that we're downloading this file
                announceDownload(fileId, downloadState.downloadedChunks);
            })
            .catch(error => {
                showToast('Failed to get file information', 'error');
                console.error('Error getting file info:', error);
            });
    }
    
    // Simulate chunk download (in a real app, this would fetch from peers)
    function simulateChunkDownload(downloadState, peers) {
        const totalChunks = downloadState.totalChunks;
        const fileId = downloadState.fileId;
        
        // Simulate downloading each chunk
        for (let i = 0; i < totalChunks; i++) {
            setTimeout(() => {
                // If download was cancelled
                if (!downloadState.active) return;
                
                // Mark chunk as downloaded
                downloadState.downloadedChunks.push(i);
                
                // Update progress
                downloadState.progress = (downloadState.downloadedChunks.length / totalChunks) * 100;
                
                // Update UI
                updateDownloadsUI();
                
                // Announce to tracker
                announceDownload(fileId, downloadState.downloadedChunks);
                
                // Check if download is complete
                if (downloadState.downloadedChunks.length === totalChunks) {
                    // In a real implementation, we would merge chunks and save the file
                    showToast(`Download of "${downloadState.filename}" completed`, 'success');
                    
                    // Add to shared files
                    sharedFiles[fileId] = {
                        filename: downloadState.filename,
                        size: 0, // We don't know the exact size in this simulation
                        chunks: Array.from(Array(totalChunks).keys())
                    };
                    
                    // Update UI
                    updateSharedFilesUI();
                    
                    // Remove from active downloads
                    delete activeDownloads[fileId];
                    updateDownloadsUI();
                }
            }, i * 1000); // 1 second per chunk for simulation
        }
    }
    
    // Announce download to tracker
    function announceDownload(fileId, downloadedChunks) {
        fetch(`${TRACKER_URL}/announce`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                peer_id: currentPeerId,
                file_id: fileId,
                port: peerPort,
                chunks: downloadedChunks
            })
        })
        .catch(error => {
            console.error('Error announcing download to tracker:', error);
        });
    }
    
    // Cancel a download
    function cancelDownload(fileId) {
        if (activeDownloads[fileId]) {
            activeDownloads[fileId].active = false;
            delete activeDownloads[fileId];
            updateDownloadsUI();
            showToast('Download cancelled', 'success');
        }
    }
    
    // Start periodic announcements for shared files
    function startPeriodicAnnouncements() {
        setInterval(() => {
            for (const [fileId, fileInfo] of Object.entries(sharedFiles)) {
                fetch(`${TRACKER_URL}/announce`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        peer_id: currentPeerId,
                        file_id: fileId,
                        port: peerPort,
                        chunks: fileInfo.chunks
                    })
                })
                .catch(error => {
                    console.error(`Error announcing file ${fileId} to tracker:`, error);
                });
            }
        }, 60000); // Announce every minute
    }
    
    // Update downloads UI
    function updateDownloadsUI() {
        downloadsListEl.innerHTML = '';
        
        if (Object.keys(activeDownloads).length === 0) {
            noDownloadsMessageEl.style.display = 'block';
        } else {
            noDownloadsMessageEl.style.display = 'none';
            
            for (const [fileId, downloadInfo] of Object.entries(activeDownloads)) {
                const downloadItem = document.createElement('div');
                downloadItem.className = 'transfer-item';
                
                downloadItem.innerHTML = `
                    <div class="transfer-header">
                        <div class="filename">${downloadInfo.filename}</div>
                        <button class="cancel-button" data-file-id="${fileId}">Cancel</button>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${downloadInfo.progress}%"></div>
                    </div>
                    <div class="transfer-details">
                        <div class="progress-text">${downloadInfo.progress.toFixed(1)}%</div>
                        <div class="chunks-text">${downloadInfo.downloadedChunks.length}/${downloadInfo.totalChunks} chunks</div>
                    </div>
                `;
                
                downloadsListEl.appendChild(downloadItem);
            }
            
            // Add event listeners to cancel buttons
            document.querySelectorAll('.cancel-button').forEach(button => {
                button.addEventListener('click', function() {
                    const fileId = this.getAttribute('data-file-id');
                    cancelDownload(fileId);
                });
            });
        }
    }
    
    // Update shared files UI
    function updateSharedFilesUI() {
        sharingListEl.innerHTML = '';
        
        if (Object.keys(sharedFiles).length === 0) {
            noSharingMessageEl.style.display = 'block';
        } else {
            noSharingMessageEl.style.display = 'none';
            
            for (const [fileId, fileInfo] of Object.entries(sharedFiles)) {
                const shareItem = document.createElement('div');
                shareItem.className = 'transfer-item';
                
                // Format file size
                const sizeInMB = fileInfo.size ? (fileInfo.size / (1024 * 1024)).toFixed(2) + ' MB' : 'Unknown size';
                
                shareItem.innerHTML = `
                    <div class="transfer-header">
                        <div class="filename">${fileInfo.filename}</div>
                        <div class="size-text">${sizeInMB}</div>
                    </div>
                    <div class="transfer-details">
                        <div class="chunks-text">Sharing ${fileInfo.chunks.length} chunks</div>
                        <div class="file-id-text">ID: ${fileId}</div>
                    </div>
                `;
                
                sharingListEl.appendChild(shareItem);
            }
        }
    }
    
    // Show toast notification
    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        
        const toastContainer = document.getElementById('toast-container');
        toastContainer.appendChild(toast);
        
        // Auto-remove after 3 seconds
        setTimeout(() => {
            toast.remove();
        }, 3000);
    }
    
    // Initial fetch of files
    fetchAvailableFiles();
});