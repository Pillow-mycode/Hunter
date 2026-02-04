/**
 * Hunter Web Client
 * 自动化渗透测试系统 - Web 客户端
 * Version: 2.3.2 - 修复最终回复渲染顺序
 */

console.log('[Hunter] 客户端版本: 2.3.2 - 修复最终回复渲染顺序');

// 国际化文本
const i18n = {
    zh: {
        title: 'Hunter - 自动化渗透测试系统',
        subtitle: '自动化渗透测试系统',
        newSession: '新建会话',
        notConnected: '未连接',
        connected: '已连接',
        connecting: '连接中...',
        connect: '连接',
        serverAddress: '服务器地址',
        chatTitle: 'Hunter 渗透测试助手',
        welcomeTitle: '欢迎使用 Hunter',
        welcomeDesc: '我是自动化渗透测试助手，可以帮你执行各种安全测试任务。',
        inputPlaceholder: '输入渗透测试需求，例如：对 example.com 进行端口扫描',
        inputHint: '按 Enter 发送，Shift + Enter 换行',
        portScan: '端口扫描',
        subdomainEnum: '子域名枚举',
        loginBrute: '登录爆破',
        sqlInjection: 'SQL注入检测',
        taskRunning: '当前任务正在执行中，请等待完成后再发送新消息',
        taskStopped: '任务已停止',
        connectionError: '连接错误，请重试',
        taskCancelled: '任务已取消',
        startTask: '开始执行任务',
        submit: '提交',
        skip: '跳过',
        confirm: '确认执行',
        cancel: '取消',
        summary: '摘要',
        findings: '发现',
        conclusion: '结论',
        recommendations: '建议',
        taskCompleted: '任务已完成',
        error: '错误',
        switchedToSession: '已切换到会话',
        loadSessionFailed: '加载会话失败',
        deleted: '已删除会话',
        skipped: '(跳过)',
        items: '项',
        fullResultSaved: '完整结果已保存',
        running: '正在运行',
        timeout: '超时',
        needInput: '需要输入',
        language: '语言'
    },
    en: {
        title: 'Hunter - Automated Penetration Testing',
        subtitle: 'Automated Penetration Testing System',
        newSession: 'New Session',
        notConnected: 'Disconnected',
        connected: 'Connected',
        connecting: 'Connecting...',
        connect: 'Connect',
        serverAddress: 'Server Address',
        chatTitle: 'Hunter Pentest Assistant',
        welcomeTitle: 'Welcome to Hunter',
        welcomeDesc: 'I am an automated penetration testing assistant, ready to help you with security testing tasks.',
        inputPlaceholder: 'Enter your pentest request, e.g.: Scan ports on example.com',
        inputHint: 'Press Enter to send, Shift + Enter for new line',
        portScan: 'Port Scan',
        subdomainEnum: 'Subdomain Enum',
        loginBrute: 'Login Brute',
        sqlInjection: 'SQL Injection',
        taskRunning: 'Task is running, please wait for completion',
        taskStopped: 'Task stopped',
        connectionError: 'Connection error, please retry',
        taskCancelled: 'Task cancelled',
        startTask: 'Starting task',
        submit: 'Submit',
        skip: 'Skip',
        confirm: 'Confirm',
        cancel: 'Cancel',
        summary: 'Summary',
        findings: 'Findings',
        conclusion: 'Conclusion',
        recommendations: 'Recommendations',
        taskCompleted: 'Task completed',
        error: 'Error',
        switchedToSession: 'Switched to session',
        loadSessionFailed: 'Failed to load session',
        deleted: 'Session deleted',
        skipped: '(Skipped)',
        items: 'items',
        fullResultSaved: 'Full result saved',
        running: 'Running',
        timeout: 'Timeout',
        needInput: 'Input required',
        language: 'Language'
    }
};

// 获取当前语言文本
function t(key) {
    return i18n[state.language]?.[key] || i18n.zh[key] || key;
}

// 全局状态
const state = {
    serverUrl: 'localhost:8000',
    connected: false,
    currentSessionId: null,  // 当前显示的会话 ID
    websockets: {},          // 每个会话的 WebSocket 连接 { session_id: WebSocket }
    sessions: [],            // 会话列表
    messages: [],
    sessionMessages: {},     // 存储每个会话的消息历史 { session_id: [messages] }
    pendingInteractions: {}, // 存储每个会话的待处理交互 { session_id: { type, data, timestamp } }
    sessionProgress: {},     // 存储每个会话的进度消息 { session_id: [messages] }
    language: 'zh'  // 固定中文
};

// DOM 元素
const elements = {
    serverUrl: () => document.getElementById('serverUrl'),
    serverStatus: () => document.getElementById('serverStatus'),
    chatMessages: () => document.getElementById('chatMessages'),
    messageInput: () => document.getElementById('messageInput'),
    sendBtn: () => document.getElementById('sendBtn'),
    stopBtn: () => document.getElementById('stopBtn'),
    taskList: () => document.getElementById('taskList'),
    currentTaskId: () => document.getElementById('currentTaskId'),
    chatTitle: () => document.getElementById('chatTitle')
};

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    loadSessionMessages();
    autoResizeTextarea();
    updateUILanguage();
    connectServer();
});

// 更新 UI 语言
function updateUILanguage() {
    // 更新页面标题
    document.title = t('title');

    // 更新侧边栏
    document.querySelector('.sidebar-header h1').textContent = 'Hunter';
    document.querySelector('.sidebar-header p').textContent = t('subtitle');
    document.querySelector('.new-chat-btn').innerHTML = `<span>+</span> ${t('newSession')}`;

    // 更新服务器配置
    document.getElementById('serverUrl').placeholder = t('serverAddress');
    document.querySelector('.server-config button').textContent = t('connect');

    // 更新聊天标题
    if (!state.currentSessionId) {
        elements.chatTitle().textContent = t('chatTitle');
    }

    // 更新输入框
    elements.messageInput().placeholder = t('inputPlaceholder');
    document.querySelector('.input-hint').textContent = t('inputHint');

    // 更新欢迎消息（如果存在）
    const welcome = document.querySelector('.welcome-message');
    if (welcome) {
        welcome.querySelector('h2').textContent = t('welcomeTitle');
        welcome.querySelector('p').textContent = t('welcomeDesc');
        const suggestions = welcome.querySelectorAll('.suggestions button');
        if (suggestions.length >= 4) {
            suggestions[0].textContent = t('portScan');
            suggestions[1].textContent = t('subdomainEnum');
            suggestions[2].textContent = t('loginBrute');
            suggestions[3].textContent = t('sqlInjection');
        }
    }
}

// 自动调整输入框高度
function autoResizeTextarea() {
    const textarea = elements.messageInput();
    textarea.addEventListener('input', () => {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
    });
}

// 连接服务器
async function connectServer() {
    const serverUrl = elements.serverUrl().value.trim();
    if (!serverUrl) return;

    state.serverUrl = serverUrl;
    updateServerStatus('connecting');

    try {
        const response = await fetch(`http://${serverUrl}/`);
        if (response.ok) {
            state.connected = true;
            updateServerStatus('online');
        } else {
            throw new Error('Server error');
        }
    } catch (error) {
        state.connected = false;
        updateServerStatus('offline');
        console.error('连接服务器失败:', error);
    }
}

// 更新服务器状态显示
function updateServerStatus(status) {
    const statusEl = elements.serverStatus();
    const dot = statusEl.querySelector('.status-dot');
    const text = statusEl.querySelector('span:last-child');

    dot.className = 'status-dot ' + status;

    const statusText = {
        'online': t('connected'),
        'offline': t('notConnected'),
        'connecting': t('connecting')
    };
    text.textContent = statusText[status] || status;
}

// 发送消息
async function sendMessage() {
    const input = elements.messageInput();
    const message = input.value.trim();

    if (!message || !state.connected) return;

    // 检查当前会话是否正在执行任务
    if (state.currentSessionId) {
        const session = state.sessions.find(s => s.id === state.currentSessionId);
        if (session && session.status === 'running') {
            console.log(`[发送消息] 当前会话正在执行任务，阻止发送`);
            addMessage('assistant', t('taskRunning'), 'error');
            return;
        }
    }

    // 清空输入框
    input.value = '';
    input.style.height = 'auto';

    // 隐藏欢迎消息
    const welcome = document.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    // 添加用户消息
    addMessage('user', message);

    console.log(`[发送消息] 当前会话ID: ${state.currentSessionId}`);

    try {
        // 如果没有当前会话，先创建会话
        if (!state.currentSessionId) {
            console.log(`[发送消息] 创建新会话`);
            const response = await fetch(`http://${state.serverUrl}/session`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: message.substring(0, 30) })
            });

            if (!response.ok) throw new Error('创建会话失败');

            const data = await response.json();
            const sessionId = data.session_id;

            console.log(`[发送消息] 新会话ID: ${sessionId}`);

            // 添加到会话列表
            addSession({
                id: sessionId,
                name: message.substring(0, 30),
                status: 'idle',
                created_at: new Date().toISOString()
            });

            // 初始化会话消息历史
            state.sessionMessages[sessionId] = [];

            // 更新当前会话 ID
            state.currentSessionId = sessionId;
            elements.currentTaskId().textContent = `会话 ID: ${sessionId}`;

            // 连接 WebSocket
            await connectWebSocket(sessionId);
        }

        const sessionId = state.currentSessionId;

        // 如果该会话的 WebSocket 未连接，重新连接
        const ws = state.websockets[sessionId];
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            console.log(`[发送消息] WebSocket 未连接，重新连接`);
            await connectWebSocket(sessionId);
        }

        // 保存消息到当前会话
        saveMessageToSession(sessionId, 'user', message);

        // 通过 WebSocket 发送消息
        const currentWs = state.websockets[sessionId];
        if (currentWs && currentWs.readyState === WebSocket.OPEN) {
            currentWs.send(JSON.stringify({
                type: 'message',
                data: { message: message }
            }));
            console.log(`[发送消息] 已通过 WebSocket 发送消息`);

            // 显示加载指示器
            addTypingIndicator();
            showStopButton();
            updateSessionStatus(sessionId, 'running');
        } else {
            throw new Error('WebSocket 连接失败');
        }

    } catch (error) {
        console.error(`[发送消息] 错误:`, error);
        addMessage('assistant', `错误: ${error.message}`);
        showSendButton();
    }
}

// 发送建议
function sendSuggestion(text) {
    elements.messageInput().value = text;
    sendMessage();
}

// 连接 WebSocket
function connectWebSocket(sessionId) {
    return new Promise((resolve, reject) => {
        // 如果该会话已经有连接且是打开状态，直接返回
        if (state.websockets[sessionId] && state.websockets[sessionId].readyState === WebSocket.OPEN) {
            console.log(`[WebSocket] 会话 ${sessionId} 已有连接`);
            resolve();
            return;
        }

        console.log(`[WebSocket] 连接会话 ${sessionId}`);

        const wsUrl = `ws://${state.serverUrl}/ws/${sessionId}`;
        const ws = new WebSocket(wsUrl);
        state.websockets[sessionId] = ws;

        ws.onopen = () => {
            console.log(`[WebSocket] 已连接: ${sessionId}`);
            resolve();
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log(`[WebSocket] 收到消息 (会话 ${sessionId}):`, data.type);
            handleServerMessage(sessionId, data);
        };

        ws.onclose = () => {
            console.log(`[WebSocket] 已关闭: ${sessionId}`);
            delete state.websockets[sessionId];

            // 只在当前会话时更新 UI
            if (sessionId === state.currentSessionId) {
                removeTypingIndicator();
                showSendButton();
            }

            // 更新会话状态
            updateSessionStatus(sessionId, 'idle');
        };

        ws.onerror = (error) => {
            console.error(`[WebSocket] 错误 (${sessionId}):`, error);
            delete state.websockets[sessionId];

            // 只在当前会话时显示错误
            if (sessionId === state.currentSessionId) {
                removeTypingIndicator();
                addMessage('assistant', '连接错误，请重试');
                showSendButton();
            }
            reject(error);
        };
    });
}

// 处理服务器消息
function handleServerMessage(sessionId, data) {
    const { type, data: payload } = data;

    // 检查是否是当前显示的会话
    const isCurrentSession = (sessionId === state.currentSessionId);

    console.log(`[消息处理] 会话 ${sessionId}, 类型: ${type}, 是否当前会话: ${isCurrentSession}`);

    switch (type) {
        case 'connected':
            // WebSocket 连接成功
            console.log(`[消息处理] WebSocket 连接成功`);
            break;

        case 'status':
            updateSessionStatus(sessionId, payload.status);
            break;

        case 'task_started':
            // 任务开始执行
            console.log(`[消息处理] 任务开始: ${payload.command}`);
            updateSessionStatus(sessionId, 'running');
            // 清除该会话的待处理交互和进度
            delete state.pendingInteractions[sessionId];
            state.sessionProgress[sessionId] = [];
            break;

        case 'progress':
            // 缓存进度消息
            if (!state.sessionProgress[sessionId]) {
                state.sessionProgress[sessionId] = [];
            }
            state.sessionProgress[sessionId].push({
                message: payload.message,
                timestamp: data.timestamp
            });

            // 只在当前会话时显示进度
            if (isCurrentSession) {
                console.log(`[消息处理] 显示进度消息: ${payload.message}`);
                handleProgressMessage(payload.message, data.timestamp);
            }
            break;

        case 'need_input':
            // 缓存待处理的输入请求
            state.pendingInteractions[sessionId] = {
                type: 'need_input',
                prompt: payload.prompt,
                timestamp: data.timestamp
            };

            if (isCurrentSession) {
                removeTypingIndicator();
                addInputRequest(payload.prompt, sessionId);
            } else {
                console.log(`[消息处理] 会话 ${sessionId} 需要输入，已缓存`);
                // 更新会话状态为需要输入
                updateSessionStatus(sessionId, 'need_input');
            }
            break;

        case 'need_confirm':
            // 缓存待处理的确认请求
            state.pendingInteractions[sessionId] = {
                type: 'need_confirm',
                message: payload.message,
                task: payload.task,
                timestamp: data.timestamp
            };

            if (isCurrentSession) {
                removeTypingIndicator();
                addConfirmRequest(payload.message, payload.task, sessionId);
            } else {
                console.log(`[消息处理] 会话 ${sessionId} 需要确认，已缓存`);
                // 更新会话状态为需要确认
                updateSessionStatus(sessionId, 'need_confirm');
            }
            break;

        case 'task_completed':
            console.log(`[消息处理] 会话 ${sessionId} 任务完成`);
            updateSessionStatus(sessionId, 'idle');
            // 清除待处理交互
            delete state.pendingInteractions[sessionId];

            // 只在当前会话时更新 UI
            if (isCurrentSession) {
                removeTypingIndicator();
                handleCompleted(payload.result);
                showSendButton();
            }
            // WebSocket 保持连接，等待下一条消息
            console.log(`[消息处理] 任务完成，WebSocket 保持连接`);
            break;

        case 'error':
            updateSessionStatus(sessionId, 'idle');
            // 清除待处理交互
            delete state.pendingInteractions[sessionId];

            if (isCurrentSession) {
                removeTypingIndicator();
                addMessage('assistant', `错误: ${payload.message}`, 'error');
                showSendButton();
            }
            break;

        case 'cancelled':
            updateSessionStatus(sessionId, 'idle');
            // 清除待处理交互
            delete state.pendingInteractions[sessionId];

            if (isCurrentSession) {
                removeTypingIndicator();
                addMessage('assistant', '任务已取消');
                showSendButton();
            }
            break;
    }
}

// 处理进度消息
function handleProgressMessage(message, timestamp) {
    // 检查是否是回复消息
    if (message.startsWith('[回复]')) {
        removeTypingIndicator();
        const reply = message.substring(4).trim();
        addMessage('assistant', reply);
        addTypingIndicator();
        return;
    }

    // 检查是否是文件保存通知
    if (message.startsWith('[文件]')) {
        const fileInfo = message.substring(4).trim();
        addFileNotification(fileInfo);
        return;
    }

    // 检查是否是武器大师运行命令
    if (message.startsWith('[武器大师] 正在运行:')) {
        const cmd = message.substring('[武器大师] 正在运行:'.length).trim();
        addCommandLine(cmd, timestamp);
        return;
    }

    // 普通进度消息
    addProgressLine(message, timestamp);
}

// 添加文件通知
function addFileNotification(fileInfo) {
    const container = elements.chatMessages();

    const notificationEl = document.createElement('div');
    notificationEl.className = 'message assistant file-notification';
    notificationEl.innerHTML = `
        <div class="message-avatar">📁</div>
        <div class="message-content file-content">
            <div class="file-header">完整结果已保存</div>
            <div class="file-path">${escapeHtml(fileInfo)}</div>
        </div>
    `;

    // 插入到 typing indicator 之前
    const typingMsg = container.querySelector('.message.typing');
    if (typingMsg) {
        container.insertBefore(notificationEl, typingMsg);
    } else {
        container.appendChild(notificationEl);
    }

    scrollToBottom();
}

// 添加命令行显示
function addCommandLine(cmd, timestamp) {
    const container = elements.chatMessages();
    // 查找最后一个进度消息容器
    const progressMsgs = container.querySelectorAll('.message.progress');
    let progressMsg = progressMsgs.length > 0 ? progressMsgs[progressMsgs.length - 1] : null;

    if (!progressMsg) {
        progressMsg = document.createElement('div');
        progressMsg.className = 'message assistant progress';
        progressMsg.innerHTML = `
            <div class="message-avatar"><img src="hunter.png" alt="Hunter" class="avatar-icon"></div>
            <div class="message-content"></div>
        `;
        const typingMsg = container.querySelector('.message.typing');
        if (typingMsg) {
            container.insertBefore(progressMsg, typingMsg);
        } else {
            container.appendChild(progressMsg);
        }
    }

    const content = progressMsg.querySelector('.message-content');
    const time = timestamp ? new Date(timestamp).toLocaleTimeString() : '';

    const line = document.createElement('div');
    line.className = 'progress-line command-line';
    line.innerHTML = `
        <span class="progress-time">${time}</span>
        <span class="command-label">正在运行:</span>
        <code class="command-text">${escapeHtml(cmd)}</code>
    `;
    content.appendChild(line);

    scrollToBottom();
}

// 添加进度行
function addProgressLine(message, timestamp) {
    const container = elements.chatMessages();
    // 查找最后一个进度消息容器
    const progressMsgs = container.querySelectorAll('.message.progress');
    let progressMsg = progressMsgs.length > 0 ? progressMsgs[progressMsgs.length - 1] : null;

    if (!progressMsg) {
        progressMsg = document.createElement('div');
        progressMsg.className = 'message assistant progress';
        progressMsg.innerHTML = `
            <div class="message-avatar"><img src="hunter.png" alt="Hunter" class="avatar-icon"></div>
            <div class="message-content"></div>
        `;
        // 插入到 typing indicator 之前
        const typingMsg = container.querySelector('.message.typing');
        if (typingMsg) {
            container.insertBefore(progressMsg, typingMsg);
        } else {
            container.appendChild(progressMsg);
        }
    }

    const content = progressMsg.querySelector('.message-content');
    const time = timestamp ? new Date(timestamp).toLocaleTimeString() : '';

    const line = document.createElement('div');
    line.className = 'progress-line';
    line.innerHTML = `
        <span class="progress-time">${time}</span>
        <span class="progress-text">${escapeHtml(message)}</span>
    `;
    content.appendChild(line);

    scrollToBottom();
}

// 添加消息
function addMessage(role, content, type = '') {
    const container = elements.chatMessages();

    const messageEl = document.createElement('div');
    messageEl.className = `message ${role} ${type}`;

    const avatar = role === 'user' ? '👤' : '<img src="hunter.png" alt="Hunter" class="avatar-icon">';

    messageEl.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">${formatMessage(content)}</div>
    `;

    // 找到 typing indicator
    const typingMsg = container.querySelector('.message.typing');
    if (typingMsg) {
        // 插入到 typing indicator 之前
        container.insertBefore(messageEl, typingMsg);
    } else {
        // 没有 typing indicator，直接添加到末尾
        container.appendChild(messageEl);
    }

    // 保存消息到当前会话
    if (state.currentSessionId) {
        saveMessageToSession(state.currentSessionId, role, content);
    }

    scrollToBottom();
}

// 添加输入请求
function addInputRequest(prompt, sessionId) {
    const container = elements.chatMessages();

    const messageEl = document.createElement('div');
    messageEl.className = 'message assistant input-required';
    messageEl.innerHTML = `
        <div class="message-avatar">🎯</div>
        <div class="message-content">
            <p>${escapeHtml(prompt)}</p>
            <div class="input-form">
                <textarea placeholder="请输入..." rows="2"></textarea>
                <div class="btn-group">
                    <button class="btn-submit" onclick="submitInput(this, '${sessionId}')">提交</button>
                    <button class="btn-skip" onclick="skipInput(this, '${sessionId}')">跳过</button>
                </div>
            </div>
        </div>
    `;

    container.appendChild(messageEl);
    scrollToBottom();

    // 聚焦输入框
    messageEl.querySelector('textarea').focus();
}

// 提交输入
function submitInput(btn, sessionId) {
    const form = btn.closest('.input-form');
    const textarea = form.querySelector('textarea');
    const value = textarea.value.trim();

    if (!value) return;

    // 禁用表单
    textarea.disabled = true;
    btn.disabled = true;

    // 清除待处理交互
    delete state.pendingInteractions[sessionId];
    updateSessionStatus(sessionId, 'running');

    // 发送到服务器
    const ws = state.websockets[sessionId];
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'input',
            data: { input: value }
        }));
    }

    // 添加用户回复
    addMessage('user', value);
    addTypingIndicator();
}

// 跳过输入
function skipInput(btn, sessionId) {
    const form = btn.closest('.input-form');
    const textarea = form.querySelector('textarea');

    textarea.disabled = true;
    btn.disabled = true;
    form.querySelector('.btn-submit').disabled = true;

    // 清除待处理交互
    delete state.pendingInteractions[sessionId];
    updateSessionStatus(sessionId, 'running');

    const ws = state.websockets[sessionId];
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'input',
            data: { input: 'skip' }
        }));
    }

    addMessage('user', '(跳过)');
    addTypingIndicator();
}

// 添加确认请求
function addConfirmRequest(message, task, sessionId) {
    const container = elements.chatMessages();

    const taskInfo = task ? `\n任务: ${task.action} -> ${task.target}` : '';

    const messageEl = document.createElement('div');
    messageEl.className = 'message assistant confirm-required';
    messageEl.innerHTML = `
        <div class="message-avatar">🎯</div>
        <div class="message-content">
            <p>${escapeHtml(message)}${escapeHtml(taskInfo)}</p>
            <div class="confirm-buttons">
                <button class="btn-yes" onclick="confirmAction(true, this, '${sessionId}')">确认执行</button>
                <button class="btn-no" onclick="confirmAction(false, this, '${sessionId}')">取消</button>
            </div>
        </div>
    `;

    container.appendChild(messageEl);
    scrollToBottom();
}

// 确认操作
function confirmAction(confirmed, btn, sessionId) {
    const buttons = btn.closest('.confirm-buttons');
    buttons.querySelectorAll('button').forEach(b => b.disabled = true);

    // 清除待处理交互
    delete state.pendingInteractions[sessionId];
    if (confirmed) {
        updateSessionStatus(sessionId, 'running');
    } else {
        updateSessionStatus(sessionId, 'idle');
    }

    const ws = state.websockets[sessionId];
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'input',
            data: { input: confirmed ? 'y' : 'n' }
        }));
    }

    addMessage('user', confirmed ? '确认执行' : '取消');
    if (confirmed) {
        addTypingIndicator();
    }
}

// 处理完成
function handleCompleted(result) {
    if (!result) return;

    const status = result.status;
    const report = result.report;

    if (status === 'completed' && report) {
        const hasFindings = report.findings && Object.values(report.findings).some(v =>
            (Array.isArray(v) && v.length > 0) ||
            (typeof v === 'object' && Object.keys(v).length > 0)
        );
        const hasRecommendations = report.recommendations && report.recommendations.length > 0;
        const hasConclusion = report.conclusion && report.conclusion.trim() !== '';

        // 如果只有摘要且没有其他内容，说明是简单回答
        if (report.summary && !hasConclusion && !hasFindings && !hasRecommendations) {
            // 简单回答模式 - 使用 addFinalMessage 确保添加到最后
            addFinalMessage('assistant', report.summary);
        } else {
            // 完整报告模式
            let content = '';

            if (report.summary) {
                content += `**摘要**\n${report.summary}\n\n`;
            }

            if (hasFindings) {
                content += `**发现**\n`;
                for (const [key, value] of Object.entries(report.findings)) {
                    if (Array.isArray(value) && value.length > 0) {
                        content += `- ${key}: ${value.length} 项\n`;
                    } else if (typeof value === 'object' && Object.keys(value).length > 0) {
                        content += `- ${key}: ${Object.keys(value).length} 项\n`;
                    }
                }
                content += '\n';
            }

            if (hasConclusion) {
                content += `**结论**\n${report.conclusion}\n\n`;
            }

            if (hasRecommendations) {
                content += `**建议**\n`;
                report.recommendations.forEach((rec, i) => {
                    content += `${i + 1}. ${rec}\n`;
                });
            }

            addFinalMessage('assistant', content || '任务已完成');
        }
    } else if (status === 'aborted') {
        addFinalMessage('assistant', `任务被中止: ${result.reason || '未知原因'}`, 'error');
    } else {
        addFinalMessage('assistant', `任务状态: ${status}`);
    }
}

// 添加最终消息（始终添加到容器末尾）
function addFinalMessage(role, content, type = '') {
    const container = elements.chatMessages();

    const messageEl = document.createElement('div');
    messageEl.className = `message ${role} ${type}`;

    const avatar = role === 'user' ? '👤' : '<img src="hunter.png" alt="Hunter" class="avatar-icon">';

    messageEl.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">${formatMessage(content)}</div>
    `;

    // 始终添加到容器末尾
    container.appendChild(messageEl);

    // 保存消息到当前会话
    if (state.currentSessionId) {
        saveMessageToSession(state.currentSessionId, role, content);
    }

    scrollToBottom();
}

// 添加加载指示器
function addTypingIndicator() {
    removeTypingIndicator();

    const container = elements.chatMessages();
    const indicator = document.createElement('div');
    indicator.className = 'message assistant typing';
    indicator.innerHTML = `
        <div class="message-avatar">🎯</div>
        <div class="typing-indicator">
            <span></span>
            <span></span>
            <span></span>
        </div>
    `;
    container.appendChild(indicator);
    scrollToBottom();
}

// 移除加载指示器
function removeTypingIndicator() {
    const indicator = document.querySelector('.message.typing');
    if (indicator) indicator.remove();
}

// 新建聊天
function newChat() {
    // 不关闭其他会话的 WebSocket，让它们继续在后台运行

    state.currentSessionId = null;
    state.messages = [];

    elements.currentTaskId().textContent = '';
    elements.chatTitle().textContent = 'Hunter 渗透测试助手';

    const container = elements.chatMessages();
    container.innerHTML = `
        <div class="welcome-message">
            <div class="welcome-icon"><img src="hunter.png" alt="Hunter" class="welcome-logo"></div>
            <h2>欢迎使用 Hunter</h2>
            <p>我是自动化渗透测试助手，可以帮你执行各种安全测试任务。</p>
            <div class="suggestions">
                <button onclick="sendSuggestion('对 192.168.1.1 进行端口扫描')">端口扫描</button>
                <button onclick="sendSuggestion('对 example.com 进行子域名枚举')">子域名枚举</button>
                <button onclick="sendSuggestion('对 example.com/login 进行登录爆破')">登录爆破</button>
                <button onclick="sendSuggestion('检测 example.com 是否存在 SQL 注入')">SQL注入检测</button>
            </div>
        </div>
    `;

    showSendButton();

    // 更新会话列表高亮
    renderSessionList();
}

// 会话管理
function addSession(session) {
    state.sessions.unshift(session);
    saveSessions();
    renderSessionList();
}

function updateSessionStatus(sessionId, status) {
    const session = state.sessions.find(s => s.id === sessionId);
    if (session) {
        session.status = status;
        saveSessions();
        renderSessionList();
    }
}

function renderSessionList() {
    const container = elements.taskList();
    container.innerHTML = state.sessions.map(session => {
        // 根据状态显示不同图标
        let statusIcon = '';
        if (session.status === 'running') {
            statusIcon = '🔄';
        } else if (session.status === 'need_input' || session.status === 'need_confirm') {
            statusIcon = '⚠️';
        }

        return `
        <div class="task-item ${session.id === state.currentSessionId ? 'active' : ''}"
             onclick="loadSession('${session.id}')">
            <span class="task-icon">📋</span>
            <div class="task-info">
                <div class="task-name">${escapeHtml(session.name.substring(0, 30))}${session.name.length > 30 ? '...' : ''}</div>
                <div class="task-time">${formatTime(session.created_at)}</div>
            </div>
            <span class="task-status-icon">${statusIcon}</span>
            <span class="task-status ${session.status}"></span>
            <button class="task-delete-btn" onclick="event.stopPropagation(); deleteSession('${session.id}')" title="删除">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 6L6 18M6 6l12 12"/>
                </svg>
            </button>
        </div>
    `}).join('');
}

async function loadSession(sessionId) {
    // 允许随时切换会话，不再检查 isRunning
    // 后台会话的任务会继续执行

    // 切换到指定会话
    state.currentSessionId = sessionId;

    // 更新 UI
    const session = state.sessions.find(s => s.id === sessionId);
    if (session) {
        elements.currentTaskId().textContent = `会话 ID: ${sessionId}`;
        elements.chatTitle().textContent = session.name.substring(0, 50) + (session.name.length > 50 ? '...' : '');
    }

    // 清空当前聊天区域
    const container = elements.chatMessages();
    container.innerHTML = '';

    // 显示加载提示
    addTypingIndicator();

    try {
        // 从服务器获取会话的对话历史
        const response = await fetch(`http://${state.serverUrl}/session/${sessionId}/messages`);
        if (!response.ok) throw new Error('获取对话历史失败');

        const data = await response.json();
        const messages = data.messages || [];

        removeTypingIndicator();

        // 渲染对话历史
        if (messages.length === 0) {
            // 如果没有对话历史，显示会话信息
            addMessageWithoutSave('assistant', `已切换到会话: ${session.name}`);
        } else {
            // 渲染所有历史消息
            messages.forEach(msg => {
                const role = msg.role === 'user' ? 'user' : 'assistant';
                addMessageWithoutSave(role, msg.content);
            });
        }

        // 恢复缓存的进度消息
        const cachedProgress = state.sessionProgress[sessionId] || [];
        if (cachedProgress.length > 0) {
            console.log(`[加载会话] 恢复 ${cachedProgress.length} 条进度消息`);
            cachedProgress.forEach(p => {
                handleProgressMessage(p.message, p.timestamp);
            });
        }

        // 检查是否有待处理的交互请求
        const pendingInteraction = state.pendingInteractions[sessionId];
        if (pendingInteraction) {
            console.log(`[加载会话] 恢复待处理交互: ${pendingInteraction.type}`);
            if (pendingInteraction.type === 'need_input') {
                addInputRequest(pendingInteraction.prompt, sessionId);
            } else if (pendingInteraction.type === 'need_confirm') {
                addConfirmRequest(pendingInteraction.message, pendingInteraction.task, sessionId);
            }
        }

        // 如果该会话没有 WebSocket 连接，建立连接
        if (!state.websockets[sessionId] || state.websockets[sessionId].readyState !== WebSocket.OPEN) {
            await connectWebSocket(sessionId);
        }

        // 根据会话状态更新按钮
        if (session && (session.status === 'running' || session.status === 'need_input' || session.status === 'need_confirm')) {
            // 如果有待处理交互，不显示 typing indicator
            if (!pendingInteraction) {
                addTypingIndicator();
            }
            showStopButton();
        } else {
            showSendButton();
        }

        // 更新会话列表高亮
        renderSessionList();

    } catch (error) {
        removeTypingIndicator();
        addMessage('assistant', `加载会话失败: ${error.message}`, 'error');
        console.error('加载会话失败:', error);
    }
}

// 添加消息但不保存（用于渲染历史消息）
function addMessageWithoutSave(role, content, type = '') {
    const container = elements.chatMessages();

    const messageEl = document.createElement('div');
    messageEl.className = `message ${role} ${type}`;

    const avatar = role === 'user' ? '👤' : '<img src="hunter.png" alt="Hunter" class="avatar-icon">';

    messageEl.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">${formatMessage(content)}</div>
    `;

    container.appendChild(messageEl);
    scrollToBottom();
}

// 保存消息到会话历史
function saveMessageToSession(sessionId, role, content) {
    if (!state.sessionMessages[sessionId]) {
        state.sessionMessages[sessionId] = [];
    }
    state.sessionMessages[sessionId].push({ role, content, timestamp: new Date().toISOString() });
    saveSessionMessages();
}

function saveSessionMessages() {
    localStorage.setItem('hunter_session_messages', JSON.stringify(state.sessionMessages));
}

function loadSessionMessages() {
    const saved = localStorage.getItem('hunter_session_messages');
    if (saved) {
        state.sessionMessages = JSON.parse(saved);
    }
}

function saveSessions() {
    localStorage.setItem('hunter_sessions', JSON.stringify(state.sessions));
}

function loadSessions() {
    const saved = localStorage.getItem('hunter_sessions');
    if (saved) {
        state.sessions = JSON.parse(saved);
        renderSessionList();
    }
}

// 删除会话
function deleteSession(sessionId) {
    // 如果该会话有 WebSocket 连接，先关闭
    const ws = state.websockets[sessionId];
    if (ws) {
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'cancel', data: {} }));
        }
        ws.close();
        delete state.websockets[sessionId];
    }

    // 从会话列表中删除
    state.sessions = state.sessions.filter(s => s.id !== sessionId);
    saveSessions();

    // 删除会话消息历史
    delete state.sessionMessages[sessionId];
    saveSessionMessages();

    // 如果删除的是当前会话，切换到新建聊天
    if (state.currentSessionId === sessionId) {
        newChat();
    } else {
        renderSessionList();
    }

    console.log(`[删除会话] 已删除会话: ${sessionId}`);
}

// 工具函数
function scrollToBottom() {
    const container = elements.chatMessages();
    container.scrollTop = container.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatMessage(content) {
    // 简单的 Markdown 支持
    return content
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
}

function formatTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
    return date.toLocaleDateString();
}

function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// 显示/隐藏发送和停止按钮
function showStopButton() {
    elements.sendBtn().style.display = 'none';
    elements.stopBtn().style.display = 'flex';
}

function showSendButton() {
    elements.sendBtn().style.display = 'flex';
    elements.stopBtn().style.display = 'none';
}

// 停止当前任务
function stopTask() {
    if (!state.currentSessionId) return;

    const ws = state.websockets[state.currentSessionId];
    if (ws && ws.readyState === WebSocket.OPEN) {
        // 发送取消消息
        ws.send(JSON.stringify({
            type: 'cancel',
            data: {}
        }));
        console.log(`[停止任务] 已发送取消请求: ${state.currentSessionId}`);
    }

    // 更新 UI
    removeTypingIndicator();
    addMessage('assistant', '任务已停止');
    updateSessionStatus(state.currentSessionId, 'idle');
    showSendButton();
}
