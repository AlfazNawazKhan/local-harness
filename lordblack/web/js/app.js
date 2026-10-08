// LordBlack Harness - Main Application Logic

class LordBlackApp {
    constructor() {
        this.state = {
            connected: false,
            currentModel: null,
            messages: [],
            activitySteps: [],
            settings: {}
        };
        
        this.init();
    }

    init() {
        console.log('LordBlack Harness initialized');
        
        // Load settings from backend
        this.loadSettings();
        
        // Setup event listeners
        this.setupEventListeners();
        
        // Initialize system stats monitoring
        this.startSystemStatsMonitor();
        
        // Check connection status
        this.checkConnection();
    }

    setupEventListeners() {
        // Settings modal
        document.getElementById('settingsBtn').addEventListener('click', () => {
            this.openModal('settingsModal');
        });
        
        document.getElementById('closeSettingsBtn').addEventListener('click', () => {
            this.closeModal('settingsModal');
        });
        
        // Memory modal
        document.getElementById('manageMemoryBtn').addEventListener('click', () => {
            this.openModal('memoryModal');
            this.loadMemoryEntries();
        });
        
        document.getElementById('closeMemoryBtn').addEventListener('click', () => {
            this.closeModal('memoryModal');
        });
        
        // Chat input
        const chatInput = document.getElementById('chatInput');
        const sendBtn = document.getElementById('sendBtn');
        
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        
        sendBtn.addEventListener('click', () => {
            this.sendMessage();
        });
        
        // Auto-resize textarea
        chatInput.addEventListener('input', (e) => {
            e.target.style.height = 'auto';
            e.target.style.height = Math.min(e.target.scrollHeight, 150) + 'px';
            
            // Update token counter
            this.updateTokenCounter();
        });
        
        // Settings tabs
        document.querySelectorAll('.settings-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const tabName = e.target.dataset.tab;
                this.switchSettingsTab(tabName);
            });
        });
        
        // Provider connection buttons
        document.getElementById('connectProviderBtn').addEventListener('click', () => {
            this.connectProvider();
        });
        
        document.getElementById('disconnectProviderBtn').addEventListener('click', () => {
            this.disconnectProvider();
        });
        
        document.getElementById('testConnectionBtn').addEventListener('click', () => {
            this.testConnection();
        });
        
        // API key reveal buttons
        document.querySelectorAll('.reveal-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const targetId = e.target.dataset.target;
                const input = document.getElementById(targetId);
                if (input.type === 'password') {
                    input.type = 'text';
                    e.target.textContent = '🔒';
                } else {
                    input.type = 'password';
                    e.target.textContent = '👁️';
                }
            });
        });
        
        // Save general settings
        document.getElementById('saveGeneralBtn').addEventListener('click', () => {
            this.saveGeneralSettings();
        });
        
        // Grant folder button
        document.getElementById('grantFolderBtn').addEventListener('click', () => {
            this.grantFolderAccess();
        });
        
        // Upload memory file
        document.getElementById('uploadMemoryFileBtn').addEventListener('click', () => {
            this.uploadMemoryFiles();
        });
        
        // Add memory entry
        document.getElementById('addMemoryEntryBtn').addEventListener('click', () => {
            this.showAddMemoryEntryDialog();
        });
        
        // Clear activity trace
        document.getElementById('clearActivityBtn').addEventListener('click', () => {
            this.clearActivityTrace();
        });
        
        // Agent trace toggle
        document.getElementById('traceHeader').addEventListener('click', () => {
            this.toggleAgentTrace();
        });
    }

    async loadSettings() {
        try {
            const response = await fetch('/api/system/settings');
            const settings = await response.json();
            this.state.settings = settings;
            
            // Populate form fields
            document.getElementById('maxContextTokens').value = settings.max_context_tokens || 4096;
            document.getElementById('embeddingMethod').value = settings.embedding_method || 'minilm-onnx';
            document.getElementById('memoryTopK').value = settings.memory_top_k || 5;
            document.getElementById('providerUrl').value = settings.provider_url || '';
            document.getElementById('internetEnabled').checked = settings.internet_enabled || false;
            
        } catch (error) {
            console.error('Failed to load settings:', error);
        }
    }

    async checkConnection() {
        try {
            const response = await fetch('/api/system/health');
            const data = await response.json();
            
            if (data.connected) {
                this.state.connected = true;
                this.state.currentModel = data.model;
                this.updateConnectionStatus(true);
                this.updateModelBadge(data.model);
            } else {
                this.state.connected = false;
                this.updateConnectionStatus(false);
            }
        } catch (error) {
            console.error('Health check failed:', error);
            this.updateConnectionStatus(false);
        }
    }

    updateConnectionStatus(connected) {
        const statusEl = document.getElementById('connectionStatus');
        if (connected) {
            statusEl.textContent = '● Online';
            statusEl.className = 'status-indicator online';
        } else {
            statusEl.textContent = '● Offline';
            statusEl.className = 'status-indicator offline';
        }
    }

    updateModelBadge(modelName) {
        const badge = document.querySelector('.model-badge.local');
        badge.textContent = `🖥️ Local: ${modelName}`;
    }

    async connectProvider() {
        const url = document.getElementById('providerUrl').value;
        
        try {
            const response = await fetch('/api/system/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider_url: url })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.addActivityStep('Connected to provider', result.models.length + ' models detected');
                this.updateDetectionStatus(result);
                this.state.connected = true;
                this.updateConnectionStatus(true);
                
                if (result.models.length > 0) {
                    this.state.currentModel = result.models[0];
                    this.updateModelBadge(this.state.currentModel);
                }
            } else {
                alert('Connection failed: ' + result.error);
            }
        } catch (error) {
            console.error('Connection error:', error);
            alert('Failed to connect: ' + error.message);
        }
    }

    updateDetectionStatus(data) {
        const statusEl = document.getElementById('detectionStatus');
        const modelListEl = document.getElementById('modelList');
        
        if (data.models && data.models.length > 0) {
            statusEl.innerHTML = `<p style="color: var(--success)">✓ Detection active: Found ${data.models.length} model(s)</p>`;
            modelListEl.innerHTML = data.models.map(model => 
                `<li>${model}</li>`
            ).join('');
        } else {
            statusEl.innerHTML = '<p>No models detected. Please download a model in LM Studio first.</p>';
            modelListEl.innerHTML = '';
        }
    }

    async sendMessage() {
        const input = document.getElementById('chatInput');
        const message = input.value.trim();
        
        if (!message || !this.state.connected) {
            if (!this.state.connected) {
                alert('Please connect to a local model first!');
                this.openModal('settingsModal');
                this.switchSettingsTab('models');
            }
            return;
        }
        
        // Add user message to UI
        this.addMessage('user', message);
        
        // Clear input
        input.value = '';
        input.style.height = 'auto';
        
        // Get flags
        const useRag = document.getElementById('ragToggle').checked;
        const agenticMode = document.getElementById('agenticToggle').checked;
        
        // Disable send button while processing
        document.getElementById('sendBtn').disabled = true;
        
        try {
            const response = await fetch('/api/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: message,
                    use_rag: useRag,
                    agentic_mode: agenticMode,
                    model: this.state.currentModel
                })
            });
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            let assistantMessage = '';
            const messageEl = this.addMessage('assistant', '');
            const contentEl = messageEl.querySelector('.message-content');
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                const chunk = decoder.decode(value);
                const lines = chunk.split('\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.slice(6));
                        
                        if (data.type === 'token') {
                            assistantMessage += data.content;
                            contentEl.textContent = assistantMessage;
                        } else if (data.type === 'activity') {
                            this.addActivityStep(data.step, data.details, data.latency);
                        } else if (data.type === 'memory_retrieval') {
                            this.updateMemoryFacts(data.facts);
                        } else if (data.type === 'complete') {
                            document.getElementById('latencyDisplay').textContent = 
                                `⚡ ${data.total_latency_ms}ms`;
                        }
                    }
                }
            }
            
        } catch (error) {
            console.error('Chat error:', error);
            this.addMessage('assistant', 'Error: ' + error.message);
        } finally {
            document.getElementById('sendBtn').disabled = false;
        }
    }

    addMessage(role, content) {
        const container = document.getElementById('chatContainer');
        
        // Remove welcome message if present
        const welcome = container.querySelector('.welcome-message');
        if (welcome) welcome.remove();
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        
        messageDiv.innerHTML = `
            <div class="message-role">${role === 'user' ? 'You' : 'Assistant'}</div>
            <div class="message-content">${content}</div>
        `;
        
        container.appendChild(messageDiv);
        container.scrollTop = container.scrollHeight;
        
        this.state.messages.push({ role, content });
        
        return messageDiv;
    }

    addActivityStep(stepName, details, latency) {
        const trace = document.getElementById('activityTrace');
        
        // Remove empty state if present
        const emptyState = trace.querySelector('.empty-state');
        if (emptyState) emptyState.remove();
        
        const stepDiv = document.createElement('div');
        stepDiv.className = 'activity-step';
        
        const timestamp = new Date().toLocaleTimeString();
        
        stepDiv.innerHTML = `
            <div class="step-header">
                <span class="step-name">${stepName}</span>
                <span class="step-time">${timestamp}</span>
            </div>
            ${details ? `<div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.3rem;">${details}</div>` : ''}
            ${latency ? `<div class="step-latency">⏱ ${latency}ms</div>` : ''}
        `;
        
        trace.appendChild(stepDiv);
        trace.scrollTop = trace.scrollHeight;
        
        this.state.activitySteps.push({ stepName, details, latency, timestamp });
    }

    updateMemoryFacts(facts) {
        const factsContainer = document.getElementById('memoryFacts');
        
        if (!facts || facts.length === 0) {
            factsContainer.innerHTML = '<p class="empty-state">No context retrieved</p>';
            return;
        }
        
        factsContainer.innerHTML = facts.map(fact => `
            <div class="fact-item">
                <span class="fact-label">${fact.label}:</span>
                <span>${fact.content}</span>
            </div>
        `).join('');
    }

    clearActivityTrace() {
        const trace = document.getElementById('activityTrace');
        trace.innerHTML = '<p class="empty-state">Waiting for activity...</p>';
        this.state.activitySteps = [];
    }

    toggleAgentTrace() {
        const trace = document.getElementById('agentTrace');
        const header = document.getElementById('traceHeader');
        
        if (trace.classList.contains('hidden')) {
            trace.classList.remove('hidden');
            header.querySelector('span').textContent = '▼ Live Agent Run Trace';
        } else {
            trace.classList.add('hidden');
            header.querySelector('span').textContent = '▶ Live Agent Run Trace';
        }
    }

    updateTokenCounter() {
        const input = document.getElementById('chatInput');
        const tokens = Math.ceil(input.value.length / 4); // Rough estimate
        document.getElementById('tokenCounter').textContent = `${tokens} tokens`;
    }

    switchSettingsTab(tabName) {
        // Update tab buttons
        document.querySelectorAll('.settings-tab').forEach(tab => {
            tab.classList.remove('active');
        });
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
        
        // Update panes
        document.querySelectorAll('.settings-pane').forEach(pane => {
            pane.classList.remove('active');
        });
        document.getElementById(`pane-${tabName}`).classList.add('active');
    }

    openModal(modalId) {
        document.getElementById(modalId).classList.remove('hidden');
    }

    closeModal(modalId) {
        document.getElementById(modalId).classList.add('hidden');
    }

    async saveGeneralSettings() {
        const settings = {
            max_context_tokens: parseInt(document.getElementById('maxContextTokens').value),
            embedding_method: document.getElementById('embeddingMethod').value,
            memory_top_k: parseInt(document.getElementById('memoryTopK').value)
        };
        
        try {
            const response = await fetch('/api/system/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            
            if (response.ok) {
                alert('Settings saved successfully!');
                this.state.settings = { ...this.state.settings, ...settings };
            } else {
                alert('Failed to save settings');
            }
        } catch (error) {
            console.error('Save settings error:', error);
            alert('Error saving settings: ' + error.message);
        }
    }

    async grantFolderAccess() {
        // This would integrate with browser File System Access API or show a dialog
        alert('Folder access feature requires backend implementation.\nUse the file upload button in Memory panel instead.');
    }

    async uploadMemoryFiles() {
        const input = document.createElement('input');
        input.type = 'file';
        input.multiple = true;
        input.accept = '.txt,.md';
        
        input.onchange = async (e) => {
            const files = Array.from(e.target.files);
            const formData = new FormData();
            
            files.forEach(file => {
                formData.append('files', file);
            });
            
            try {
                const response = await fetch('/api/memory/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert(`Successfully uploaded ${files.length} file(s) to memory!`);
                    this.loadMemoryEntries();
                } else {
                    alert('Upload failed: ' + result.error);
                }
            } catch (error) {
                console.error('Upload error:', error);
                alert('Upload failed: ' + error.message);
            }
        };
        
        input.click();
    }

    async loadMemoryEntries() {
        try {
            const response = await fetch('/api/memory/list');
            const entries = await response.json();
            
            const container = document.getElementById('memoryEntries');
            
            if (!entries || entries.length === 0) {
                container.innerHTML = '<p class="empty-state">No memory entries yet</p>';
                return;
            }
            
            container.innerHTML = entries.map(entry => `
                <div class="memory-entry" data-id="${entry.id}">
                    <div class="memory-entry-header">
                        <span class="memory-entry-title">${entry.source}</span>
                        <div class="memory-entry-actions">
                            <button class="tiny-btn" onclick="app.deleteMemoryEntry(${entry.id})">Delete</button>
                        </div>
                    </div>
                    <div class="memory-entry-preview">${entry.preview}</div>
                </div>
            `).join('');
            
        } catch (error) {
            console.error('Load memory error:', error);
        }
    }

    async deleteMemoryEntry(id) {
        if (!confirm('Delete this memory entry?')) return;
        
        try {
            const response = await fetch(`/api/memory/${id}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.loadMemoryEntries();
            } else {
                alert('Failed to delete entry');
            }
        } catch (error) {
            console.error('Delete error:', error);
            alert('Delete failed: ' + error.message);
        }
    }

    showAddMemoryEntryDialog() {
        const title = prompt('Memory entry title:');
        if (!title) return;
        
        const content = prompt('Memory content:');
        if (!content) return;
        
        this.addMemoryEntry(title, content);
    }

    async addMemoryEntry(title, content) {
        try {
            const response = await fetch('/api/memory/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, content })
            });
            
            if (response.ok) {
                alert('Memory entry added!');
                this.loadMemoryEntries();
            } else {
                alert('Failed to add entry');
            }
        } catch (error) {
            console.error('Add memory error:', error);
            alert('Failed to add memory: ' + error.message);
        }
    }

    startSystemStatsMonitor() {
        // Use Server-Sent Events or WebSocket for real-time stats
        // For now, poll every 2 seconds (low overhead)
        setInterval(async () => {
            try {
                const response = await fetch('/api/system/stats');
                const stats = await response.json();
                
                document.getElementById('cpuUsage').textContent = 
                    `${stats.cpu_percent.toFixed(1)}%`;
                document.getElementById('ramUsage').textContent = 
                    `${(stats.memory_used_gb).toFixed(2)} GB`;
                    
                // Draw sparkline
                this.drawSparkline(stats.history || []);
                
            } catch (error) {
                console.error('Stats fetch error:', error);
            }
        }, 2000);
    }

    drawSparkline(history) {
        const canvas = document.getElementById('systemSparkline');
        const ctx = canvas.getContext('2d');
        
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        if (history.length < 2) return;
        
        ctx.strokeStyle = '#00d9ff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        
        const maxVal = Math.max(...history);
        const scale = canvas.height / maxVal;
        
        history.forEach((val, i) => {
            const x = (i / (history.length - 1)) * canvas.width;
            const y = canvas.height - (val * scale);
            
            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });
        
        ctx.stroke();
    }

    async testConnection() {
        const url = document.getElementById('providerUrl').value;
        
        try {
            const response = await fetch('/api/system/test-connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });
            
            const result = await response.json();
            
            if (result.success) {
                alert('✓ Connection successful!\nModels found: ' + result.models.length);
            } else {
                alert('✗ Connection failed: ' + result.error);
            }
        } catch (error) {
            alert('Error testing connection: ' + error.message);
        }
    }

    async disconnectProvider() {
        try {
            await fetch('/api/system/disconnect', { method: 'POST' });
            this.state.connected = false;
            this.updateConnectionStatus(false);
            alert('Disconnected from provider');
        } catch (error) {
            console.error('Disconnect error:', error);
        }
    }
}

// Initialize app when page loads
let app;
window.addEventListener('DOMContentLoaded', () => {
    app = new LordBlackApp();
});
