const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const pino = require('pino');
const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const { spawn } = require('child_process');
const path = require('path');

const VERSION = '4.2.0';
const ENV_PATH = path.join(__dirname, '.env');
const AUTH_DIR = path.join(__dirname, 'auth_whatsapp');
const BOT_PY = path.join(__dirname, 'bot.py');

// ==============================================================================
// LEITURA DINÂMICA DO ARQUIVO .ENV (SEM DEPENDÊNCIAS EXTERNAS EXTRAS)
// ==============================================================================
function getEnvConfig() {
    const cfg = {
        PANEL_USER: process.env.PANEL_USER || 'saudelab',
        PANEL_PASS: process.env.PANEL_PASS || 'SaudeLab@2026',
        PANEL_SECRET: process.env.PANEL_SECRET || 'saudelab-auth-secret-key-2026',
        PORT: parseInt(process.env.PORT || process.env.STATUS_PORT || '5006', 10),
        BOT_ENGINE_PORT: parseInt(process.env.BOT_ENGINE_PORT || '5007', 10)
    };

    if (fs.existsSync(ENV_PATH)) {
        const lines = fs.readFileSync(ENV_PATH, 'utf-8').split(/\r?\n/);
        for (const raw of lines) {
            const line = raw.trim();
            if (!line || line.startsWith('#') || !line.includes('=')) continue;
            const idx = line.indexOf('=');
            const k = line.slice(0, idx).trim();
            const v = line.slice(idx + 1).trim();
            if (k && v !== undefined) cfg[k] = v;
        }
    }
    return cfg;
}

const initialCfg = getEnvConfig();
const STATUS_PORT = parseInt(initialCfg.PORT || '5006', 10);
const ENGINE_URL = `http://127.0.0.1:${initialCfg.BOT_ENGINE_PORT || 5007}`;

function resolvePythonExecutable() {
    if (process.env.PYTHON_EXE && fs.existsSync(process.env.PYTHON_EXE)) {
        return process.env.PYTHON_EXE;
    }
    const winPython = 'C:\\Users\\User\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe';
    if (process.platform === 'win32' && fs.existsSync(winPython)) {
        return winPython;
    }
    return process.platform === 'win32' ? 'python' : 'python3';
}

const PYTHON_EXE = resolvePythonExecutable();

let currentSocket = null;
let inactivityTimer = null;
let pythonProc = null;
let latestQrDataUrl = null;
let connectionStatus = 'INICIANDO...';
let connectedPhone = '';
const sentByBotIds = new Set();
const activeCalls = new Map();

function log(msg) {
    const ts = new Date().toLocaleTimeString('pt-BR');
    console.log(`[${ts}] ${msg}`);
}

// ==============================================================================
// AUTENTICAÇÃO DO PAINEL WEB (COOKIE ASSINADO HMAC-SHA256)
// ==============================================================================
function createAuthToken(user, pass, secret) {
    return crypto.createHmac('sha256', secret).update(`${user}:${pass}`).digest('hex');
}

function parseCookies(req) {
    const list = {};
    const cookieHeader = req.headers.cookie;
    if (!cookieHeader) return list;
    cookieHeader.split(';').forEach((cookie) => {
        const parts = cookie.split('=');
        const key = parts.shift().trim();
        const val = decodeURIComponent(parts.join('='));
        list[key] = val;
    });
    return list;
}

function isAuthenticated(req) {
    const cfg = getEnvConfig();
    const cookies = parseCookies(req);
    const expected = createAuthToken(cfg.PANEL_USER, cfg.PANEL_PASS, cfg.PANEL_SECRET);
    return cookies.saudelab_session === expected;
}

function readPostBody(req) {
    return new Promise((resolve) => {
        let body = '';
        req.on('data', (chunk) => {
            body += chunk.toString();
            if (body.length > 1e5) req.socket.destroy();
        });
        req.on('end', () => resolve(body));
    });
}

// ==============================================================================
// MOTOR PYTHON PERSISTENTE (PORTA 5007)
// ==============================================================================
function startPythonEngine() {
    pythonProc = spawn(PYTHON_EXE, [BOT_PY], {
        cwd: __dirname,
        stdio: ['ignore', 'pipe', 'pipe']
    });

    pythonProc.stdout.on('data', (d) => {
        const line = d.toString().trim();
        if (line && !line.includes('GET /api/') && !line.includes('POST /api/')) {
            console.log(line);
        }
    });

    pythonProc.stderr.on('data', (d) => {
        const line = d.toString().trim();
        if (line && !line.includes('POST /api/') && !line.includes('GET /api/') && !line.includes('WARNING:')) {
            console.error('[PYTHON]', line);
        }
    });

    pythonProc.on('exit', (code) => {
        log(`Motor Python encerrado (${code}). Reiniciando em 2s...`);
        setTimeout(startPythonEngine, 2000);
    });
}

// ==============================================================================
// COMPONENTE COMPARTILHADO: BANNER DE NOTIFICAÇÃO + MODAL DE INSTALAÇÃO PWA
// ==============================================================================
const PWA_INSTALL_SNIPPET = `
    <!-- Banner de Notificação Flutuante para Instalar o App -->
    <div id="installBanner" class="install-toast" style="display:none;">
        <div class="install-toast-content">
            <img src="/app-icon-192.png" alt="App" class="install-toast-icon">
            <div class="install-toast-text">
                <strong>Instalar App Saúdelab Bot?</strong>
                <span>Adicione na tela inicial do seu celular ou PC para acesso rápido.</span>
            </div>
        </div>
        <div class="install-toast-actions">
            <button type="button" class="btn-toast-install" onclick="triggerInstallApp()">📲 Instalar Agora</button>
            <button type="button" class="btn-toast-close" onclick="dismissInstallBanner()" aria-label="Fechar">✕</button>
        </div>
    </div>

    <!-- Modal Explicativo de Instalação (iOS / Android / Desktop) -->
    <div id="installModal" class="modal-backdrop" style="display:none;" onclick="if(event.target===this)closeInstallModal()">
        <div class="modal-box">
            <div class="modal-header">
                <img src="/app-icon-192.png" alt="Saúdelab" class="modal-logo">
                <div>
                    <h3>Instalar Aplicativo Saúdelab</h3>
                    <p>Deixe como um atalho direto na sua tela inicial</p>
                </div>
            </div>
            <div id="installModalBody" class="modal-body"></div>
            <button type="button" class="modal-close-btn" onclick="closeInstallModal()">Entendi</button>
        </div>
    </div>
`;

const PWA_INSTALL_CSS = `
    .install-toast {
        position: fixed;
        bottom: max(16px, calc(env(safe-area-inset-bottom, 12px) + 8px));
        left: 12px;
        right: 12px;
        max-width: 520px;
        margin: 0 auto;
        background: #0f172a;
        color: #ffffff;
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 14px 34px rgba(15, 23, 42, 0.38);
        border: 1px solid rgba(255, 255, 255, 0.14);
        z-index: 9998;
        display: flex;
        flex-direction: column;
        gap: 12px;
        animation: slideUpToast 0.3s ease-out;
    }
    @keyframes slideUpToast {
        from { transform: translateY(30px); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
    }
    .install-toast-content {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .install-toast-icon {
        width: 44px;
        height: 44px;
        border-radius: 10px;
        flex-shrink: 0;
        background: #fff;
    }
    .install-toast-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }
    .install-toast-text strong {
        font-size: 0.92rem;
        color: #f8fafc;
    }
    .install-toast-text span {
        font-size: 0.78rem;
        color: #cbd5e1;
        line-height: 1.35;
    }
    .install-toast-actions {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .btn-toast-install {
        flex: 1;
        background: #14b8a6;
        color: #042f2e;
        border: none;
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 0.85rem;
        font-weight: 800;
        cursor: pointer;
    }
    .btn-toast-close {
        background: rgba(255, 255, 255, 0.12);
        color: #cbd5e1;
        border: none;
        border-radius: 10px;
        width: 38px;
        height: 38px;
        font-size: 0.95rem;
        font-weight: 700;
        cursor: pointer;
        flex-shrink: 0;
    }
    .modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(15, 23, 42, 0.68);
        backdrop-filter: blur(3px);
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 16px;
    }
    .modal-box {
        background: #ffffff;
        color: #1e293b;
        width: 100%;
        max-width: 420px;
        border-radius: 18px;
        padding: 22px 20px;
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.35);
    }
    .modal-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 16px;
    }
    .modal-logo {
        width: 48px;
        height: 48px;
        border-radius: 12px;
        flex-shrink: 0;
    }
    .modal-header h3 {
        font-size: 1.02rem;
        color: #0f172a;
    }
    .modal-header p {
        font-size: 0.78rem;
        color: #64748b;
    }
    .modal-body {
        font-size: 0.86rem;
        color: #334155;
        line-height: 1.5;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 14px;
        margin-bottom: 16px;
    }
    .step-item {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        margin-bottom: 10px;
    }
    .step-item:last-child { margin-bottom: 0; }
    .step-num {
        background: #0f766e;
        color: #fff;
        width: 22px;
        height: 22px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 700;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        margin-top: 1px;
    }
    .modal-close-btn {
        width: 100%;
        background: #0f766e;
        color: #ffffff;
        border: none;
        border-radius: 10px;
        padding: 12px;
        font-size: 0.9rem;
        font-weight: 700;
        cursor: pointer;
    }
`;

const PWA_INSTALL_JS = `
    let deferredInstallPrompt = null;

    function isRunningStandalone() {
        return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    }

    function isIosDevice() {
        const ua = window.navigator.userAgent || '';
        return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    }

    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js').catch(() => {});
        });
    }

    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredInstallPrompt = e;
        if (!isRunningStandalone() && sessionStorage.getItem('hide_install_banner') !== '1') {
            const b = document.getElementById('installBanner');
            if (b) b.style.display = 'flex';
        }
    });

    window.addEventListener('appinstalled', () => {
        deferredInstallPrompt = null;
        const b = document.getElementById('installBanner');
        if (b) b.style.display = 'none';
    });

    if (isRunningStandalone() && isIosDevice()) {
        document.documentElement.classList.add('ios-standalone');
    }

    window.addEventListener('DOMContentLoaded', () => {
        if (isRunningStandalone()) {
            if (isIosDevice()) document.documentElement.classList.add('ios-standalone');
            const hBtn = document.querySelector('.btn-header-install');
            if (hBtn) hBtn.style.display = 'none';
        }
        if (!isRunningStandalone() && sessionStorage.getItem('hide_install_banner') !== '1') {
            setTimeout(() => {
                const b = document.getElementById('installBanner');
                if (b) b.style.display = 'flex';
            }, 900);
        }
    });

    function dismissInstallBanner() {
        sessionStorage.setItem('hide_install_banner', '1');
        const b = document.getElementById('installBanner');
        if (b) b.style.display = 'none';
    }

    function closeInstallModal() {
        const m = document.getElementById('installModal');
        if (m) m.style.display = 'none';
    }

    async function triggerInstallApp() {
        if (deferredInstallPrompt) {
            deferredInstallPrompt.prompt();
            try {
                const choice = await deferredInstallPrompt.userChoice;
                if (choice && choice.outcome === 'accepted') {
                    dismissInstallBanner();
                }
            } catch (_) {}
            deferredInstallPrompt = null;
            return;
        }

        const body = document.getElementById('installModalBody');
        const modal = document.getElementById('installModal');
        if (!body || !modal) return;

        if (isRunningStandalone()) {
            body.innerHTML = '<p>✅ <b>Este painel já está instalado</b> e rodando como aplicativo no seu aparelho!</p>';
        } else if (isIosDevice()) {
            body.innerHTML =
                '<div class="step-item"><span class="step-num">1</span><div>Toque no botão <b>Compartilhar</b> (ícone de quadrado com seta para cima <b>↑</b> na barra inferior ou superior do Safari/Chrome).</div></div>' +
                '<div class="step-item"><span class="step-num">2</span><div>Role o menu para baixo e toque em <b>"Adicionar à Tela de Início"</b>.</div></div>' +
                '<div class="step-item"><span class="step-num">3</span><div>Toque em <b>"Adicionar"</b> no canto superior direito. O ícone <b>Saúdelab Bot</b> ficará salvo junto aos seus aplicativos!</div></div>';
        } else {
            body.innerHTML =
                '<div class="step-item"><span class="step-num">1</span><div>Toque no menu do navegador (ícone <b>⋮</b> no canto superior direito do Chrome/Edge).</div></div>' +
                '<div class="step-item"><span class="step-num">2</span><div>Selecione <b>"Instalar aplicativo"</b> ou <b>"Adicionar à tela inicial"</b>.</div></div>' +
                '<div class="step-item"><span class="step-num">3</span><div>Confirme em <b>Instalar</b> para criar o atalho direto no seu aparelho.</div></div>';
        }
        modal.style.display = 'flex';
    }
`;

// ==============================================================================
// TELA DE LOGIN DO PAINEL WEB (100% RESPONSIVA + PWA)
// ==============================================================================
function renderLoginPage(errorMsg = '') {
    return `<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <meta name="theme-color" content="#0f766e">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Saúdelab Bot">
    <link rel="manifest" href="/manifest.json">
    <link rel="icon" type="image/png" href="/app-icon-192.png">
    <link rel="apple-touch-icon" href="/app-icon-192.png">
    <title>Login — Painel Saúdelab Bot 24h</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body {
            width: 100%;
            max-width: 100%;
            overflow-x: hidden;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(145deg, #0d4f4b 0%, #0f766e 50%, #115e59 100%);
            min-height: 100vh;
            color: #1e293b;
            -webkit-text-size-adjust: 100%;
        }
        body {
            display: flex;
            align-items: center;
            justify-content: center;
            padding-top: max(24px, calc(env(safe-area-inset-top, 0px) + 20px));
            padding-left: max(16px, env(safe-area-inset-left, 16px));
            padding-right: max(16px, env(safe-area-inset-right, 16px));
            padding-bottom: max(90px, calc(env(safe-area-inset-bottom, 20px) + 70px));
        }
        html.ios-standalone body {
            padding-top: max(58px, calc(env(safe-area-inset-top, 47px) + 18px));
        }
        .login-card {
            background: #ffffff;
            width: 100%;
            max-width: 400px;
            border-radius: 18px;
            padding: 28px 22px;
            box-shadow: 0 20px 45px rgba(0, 0, 0, 0.28);
            text-align: center;
        }
        .brand-logo {
            width: 68px;
            height: 68px;
            border-radius: 16px;
            margin-bottom: 12px;
            box-shadow: 0 4px 12px rgba(15, 118, 110, 0.25);
        }
        h1 {
            font-size: 1.28rem;
            color: #0f172a;
            margin-bottom: 4px;
        }
        .subtitle {
            font-size: 0.84rem;
            color: #64748b;
            margin-bottom: 20px;
        }
        .error-box {
            background: #fef2f2;
            border: 1px solid #fecaca;
            color: #b91c1c;
            padding: 10px 12px;
            border-radius: 10px;
            font-size: 0.84rem;
            font-weight: 600;
            margin-bottom: 16px;
        }
        .form-group {
            text-align: left;
            margin-bottom: 14px;
        }
        label {
            display: block;
            font-size: 0.82rem;
            font-weight: 600;
            color: #334155;
            margin-bottom: 6px;
        }
        input {
            width: 100%;
            padding: 12px 14px;
            border: 1.5px solid #cbd5e1;
            border-radius: 10px;
            font-size: 16px;
            outline: none;
            transition: border-color 0.2s;
        }
        input:focus {
            border-color: #0f766e;
        }
        .btn-submit {
            width: 100%;
            padding: 13px;
            background: #0f766e;
            color: #ffffff;
            font-size: 0.96rem;
            font-weight: 700;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            margin-top: 4px;
        }
        .btn-install-login {
            width: 100%;
            padding: 11px;
            background: #f0fdfa;
            color: #0f766e;
            border: 1.5px solid #99f6e4;
            border-radius: 10px;
            font-size: 0.85rem;
            font-weight: 700;
            cursor: pointer;
            margin-top: 10px;
        }
        .footer {
            margin-top: 20px;
            font-size: 0.74rem;
            color: #94a3b8;
        }
        ${PWA_INSTALL_CSS}
    </style>
</head>
<body>
    <div class="login-card">
        <img src="/app-icon-192.png" alt="Saúdelab" class="brand-logo">
        <h1>Saúdelab Exames</h1>
        <p class="subtitle">Painel de Conexão WhatsApp e Triagem 24h</p>
        ${errorMsg ? `<div class="error-box">${errorMsg}</div>` : ''}
        <form method="POST" action="/login">
            <div class="form-group">
                <label for="username">Usuário</label>
                <input type="text" id="username" name="username" placeholder="Digite seu usuário" required autocomplete="username">
            </div>
            <div class="form-group">
                <label for="password">Senha</label>
                <input type="password" id="password" name="password" placeholder="Digite sua senha" required autocomplete="current-password">
            </div>
            <button type="submit" class="btn-submit">Entrar no Painel</button>
        </form>
        <button type="button" class="btn-install-login" onclick="triggerInstallApp()">
            📲 Instalar Aplicativo no Celular / PC
        </button>
        <div class="footer">
            Criado por: Caio Araujo - Analista de TI | Build v${VERSION}
        </div>
    </div>
    ${PWA_INSTALL_SNIPPET}
    <script>${PWA_INSTALL_JS}</script>
</body>
</html>`;
}

// ==============================================================================
// SERVIDOR WEB (LOGIN + PAINEL PWA + LOGS AO VIVO + CONTROLES) NA PORTA 5006
// ==============================================================================
const server = http.createServer(async (req, res) => {
    const urlPath = req.url.split('?')[0];

    // Endpoint público de Healthcheck / Keep-Alive 24h
    if (urlPath === '/health' || urlPath === '/ping') {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({
            ok: true,
            version: VERSION,
            connectionStatus,
            connectedPhone: connectedPhone || null,
            timestamp: new Date().toISOString()
        }));
        return;
    }

    // Ícones reais PNG (192x192 e 512x512) para PWA Mobile / Desktop
    if (urlPath === '/app-icon.png' || urlPath === '/app-icon-192.png') {
        const fileName = urlPath === '/app-icon-192.png' ? 'app-icon-192.png' : 'app-icon.png';
        const fallbackPath = path.join(__dirname, 'app-icon.png');
        const iconPath = fs.existsSync(path.join(__dirname, fileName))
            ? path.join(__dirname, fileName)
            : fallbackPath;
        if (fs.existsSync(iconPath)) {
            res.writeHead(200, {
                'Content-Type': 'image/png',
                'Cache-Control': 'public, max-age=86400'
            });
            fs.createReadStream(iconPath).pipe(res);
            return;
        }
    }

    if (urlPath === '/manifest.json') {
        res.writeHead(200, { 'Content-Type': 'application/manifest+json; charset=utf-8' });
        res.end(JSON.stringify({
            id: '/',
            name: 'Saúdelab Exames — Painel do Bot 24h',
            short_name: 'Saúdelab Bot',
            description: 'Painel de QR Code, Status e Logs do Bot de Triagem Saúdelab Exames',
            start_url: '/',
            scope: '/',
            display: 'standalone',
            orientation: 'portrait',
            background_color: '#0f766e',
            theme_color: '#0f766e',
            icons: [
                {
                    src: '/app-icon-192.png',
                    sizes: '192x192',
                    type: 'image/png',
                    purpose: 'any'
                },
                {
                    src: '/app-icon-192.png',
                    sizes: '192x192',
                    type: 'image/png',
                    purpose: 'maskable'
                },
                {
                    src: '/app-icon.png',
                    sizes: '512x512',
                    type: 'image/png',
                    purpose: 'any'
                },
                {
                    src: '/app-icon.png',
                    sizes: '512x512',
                    type: 'image/png',
                    purpose: 'maskable'
                }
            ]
        }));
        return;
    }

    if (urlPath === '/sw.js') {
        res.writeHead(200, { 'Content-Type': 'application/javascript; charset=utf-8' });
        res.end(`
            self.addEventListener('install', (e) => self.skipWaiting());
            self.addEventListener('activate', (e) => self.clients.claim());
            self.addEventListener('fetch', (e) => {
                e.respondWith(fetch(e.request).catch(() => new Response('Offline')));
            });
        `);
        return;
    }

    // Rotas de Login / Logout
    if (urlPath === '/login' && req.method === 'GET') {
        if (isAuthenticated(req)) {
            res.writeHead(302, { Location: '/' });
            res.end();
            return;
        }
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(renderLoginPage());
        return;
    }

    if (urlPath === '/login' && req.method === 'POST') {
        const rawBody = await readPostBody(req);
        const params = new URLSearchParams(rawBody);
        const user = (params.get('username') || '').trim();
        const pass = (params.get('password') || '').trim();
        const cfg = getEnvConfig();

        if (user === cfg.PANEL_USER && pass === cfg.PANEL_PASS) {
            const token = createAuthToken(cfg.PANEL_USER, cfg.PANEL_PASS, cfg.PANEL_SECRET);
            res.writeHead(302, {
                'Set-Cookie': `saudelab_session=${token}; HttpOnly; Path=/; Max-Age=2592000; SameSite=Lax`,
                Location: '/'
            });
            res.end();
        } else {
            res.writeHead(401, { 'Content-Type': 'text/html; charset=utf-8' });
            res.end(renderLoginPage('Usuário ou senha incorretos.'));
        }
        return;
    }

    if (urlPath === '/logout') {
        res.writeHead(302, {
            'Set-Cookie': 'saudelab_session=; HttpOnly; Path=/; Max-Age=0',
            Location: '/login'
        });
        res.end();
        return;
    }

    // Proteção de rotas: exige autenticação
    if (!isAuthenticated(req)) {
        if (urlPath.startsWith('/api/')) {
            res.writeHead(401, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: 'Não autorizado' }));
        } else {
            res.writeHead(302, { Location: '/login' });
            res.end();
        }
        return;
    }

    // Endpoint para alternar entre Modo Teste (#saudelab) e Produção 24h
    if (urlPath === '/api/toggle-mode' && req.method === 'POST') {
        try {
            const body = await readPostBody(req);
            const parsed = JSON.parse(body || '{}');
            const r = await fetch(`${ENGINE_URL}/api/toggle_mode`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ test_mode: Boolean(parsed.test_mode) })
            });
            const data = await r.json();
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify(data));
        } catch (err) {
            res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ ok: false, error: err.message }));
        }
        return;
    }

    // Endpoint para desconectar o WhatsApp atual e gerar um novo QR Code
    if (urlPath === '/api/whatsapp-logout' && req.method === 'POST') {
        try {
            log('Solicitação de desconexão do WhatsApp recebida pelo painel.');
            connectionStatus = 'GERANDO NOVO QR CODE...';
            connectedPhone = '';
            latestQrDataUrl = null;
            if (currentSocket) {
                try { await currentSocket.logout(); } catch (_) {}
                try { currentSocket.end(); } catch (_) {}
            }
            if (fs.existsSync(AUTH_DIR)) {
                fs.rmSync(AUTH_DIR, { recursive: true, force: true });
            }
            setTimeout(() => startBot(), 1200);
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ ok: true }));
        } catch (err) {
            res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ ok: false, error: err.message }));
        }
        return;
    }

    // Endpoint JSON em tempo real consumido pelo Dashboard a cada 3 segundos
    if (urlPath === '/api/live') {
        let engineStatus = {
            version: VERSION,
            test_mode: true,
            trigger_word: '#saudelab',
            inactivity_minutes: 5,
            max_followups: 2,
            active_sessions: [],
            recent_triagens: [],
            logs: []
        };
        try {
            const r = await fetch(`${ENGINE_URL}/api/status`);
            if (r.ok) engineStatus = await r.json();
        } catch (_) {}

        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({
            connectionStatus,
            connectedPhone,
            latestQrDataUrl,
            engineStatus
        }));
        return;
    }

    // Página Principal do Painel Autenticado (100% Responsiva Mobile / Tablet / Desktop)
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(`<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <meta name="theme-color" content="#0f766e">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Saúdelab Bot">
    <link rel="manifest" href="/manifest.json">
    <link rel="icon" type="image/png" href="/app-icon-192.png">
    <link rel="apple-touch-icon" href="/app-icon-192.png">
    <title>Saúdelab Exames — Painel do Bot 24h</title>
    <style>
        :root {
            --primary: #0f766e;
            --primary-dark: #115e59;
            --bg: #f1f5f9;
            --card: #ffffff;
            --text: #1e293b;
            --muted: #64748b;
            --border: #e2e8f0;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body {
            width: 100%;
            max-width: 100%;
            overflow-x: hidden;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            -webkit-text-size-adjust: 100%;
        }
        body {
            padding-bottom: max(90px, calc(env(safe-area-inset-bottom, 20px) + 70px));
        }
        header {
            width: 100%;
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: #fff;
            padding-top: max(14px, calc(env(safe-area-inset-top, 0px) + 12px));
            padding-bottom: 14px;
            padding-left: max(14px, env(safe-area-inset-left, 14px));
            padding-right: max(14px, env(safe-area-inset-right, 14px));
            position: sticky;
            top: 0;
            z-index: 50;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.14);
        }
        html.ios-standalone header {
            padding-top: max(54px, calc(env(safe-area-inset-top, 47px) + 12px));
        }
        .header-inner {
            max-width: 1120px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            flex-wrap: wrap;
        }
        .header-brand {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
            flex: 1 1 200px;
        }
        .header-brand img {
            width: 38px;
            height: 38px;
            border-radius: 10px;
            background: #fff;
            flex-shrink: 0;
        }
        .header-title {
            min-width: 0;
            flex: 1;
        }
        .header-title h1 {
            font-size: 0.96rem;
            font-weight: 700;
            line-height: 1.25;
            word-break: break-word;
        }
        .header-title p {
            font-size: 0.73rem;
            opacity: 0.9;
            line-height: 1.25;
        }
        @media (max-width: 430px) {
            .header-inner {
                gap: 8px;
            }
            .header-title h1 {
                font-size: 0.9rem;
            }
            .header-title p {
                font-size: 0.7rem;
            }
        }
        .header-actions {
            display: flex;
            align-items: center;
            gap: 6px;
            flex-shrink: 0;
        }
        .btn-header-install {
            background: #ffffff;
            color: #0f766e;
            border: none;
            font-size: 0.76rem;
            font-weight: 800;
            padding: 7px 10px;
            border-radius: 8px;
            cursor: pointer;
            white-space: nowrap;
        }
        .btn-logout {
            background: rgba(255, 255, 255, 0.16);
            color: #fff;
            text-decoration: none;
            font-size: 0.76rem;
            font-weight: 600;
            padding: 7px 11px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.28);
            white-space: nowrap;
        }
        .container {
            width: 100%;
            max-width: 1120px;
            margin: 14px auto;
            padding: 0 12px;
            display: grid;
            grid-template-columns: minmax(0, 1fr);
            gap: 14px;
        }
        @media (min-width: 860px) {
            .container {
                grid-template-columns: 380px minmax(0, 1fr);
                padding: 0 16px;
            }
            .full-width {
                grid-column: 1 / -1;
            }
        }
        .card {
            background: var(--card);
            border-radius: 14px;
            padding: 15px;
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
            border: 1px solid var(--border);
            min-width: 0;
            width: 100%;
            max-width: 100%;
            overflow: hidden;
        }
        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 12px;
        }
        .card-header h2 {
            font-size: 0.95rem;
            color: #0f172a;
            font-weight: 700;
        }
        .badge {
            display: inline-block;
            padding: 5px 10px;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 700;
            max-width: 100%;
            word-break: break-word;
            text-align: center;
        }
        .badge-ok { background: #dcfce7; color: #166534; }
        .badge-warn { background: #fef9c3; color: #854d0e; }
        .info-row {
            font-size: 0.83rem;
            margin: 8px 0;
            color: #334155;
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 6px;
            border-bottom: 1px dashed #e2e8f0;
            padding-bottom: 7px;
        }
        .info-row strong {
            color: #0f172a;
            word-break: break-word;
            text-align: right;
        }
        .qr-wrapper {
            text-align: center;
            margin-top: 12px;
            padding: 12px;
            background: #f8fafc;
            border-radius: 12px;
            border: 1px dashed #cbd5e1;
        }
        .qr-wrapper img {
            width: 100%;
            max-width: 220px;
            height: auto;
            aspect-ratio: 1 / 1;
            border-radius: 8px;
            display: block;
            margin: 0 auto;
        }
        .btn-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 14px;
        }
        .btn {
            width: 100%;
            padding: 11px 12px;
            border-radius: 10px;
            font-size: 0.83rem;
            font-weight: 700;
            cursor: pointer;
            border: none;
            text-align: center;
            line-height: 1.3;
        }
        .btn-mode {
            background: #0f766e;
            color: #ffffff;
        }
        .btn-install-card {
            background: #f0fdfa;
            color: #0f766e;
            border: 1.5px solid #99f6e4;
        }
        .btn-disconnect {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fecaca;
        }
        .log-box {
            background: #0f172a;
            color: #e2e8f0;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 0.76rem;
            line-height: 1.48;
            height: 280px;
            overflow-y: auto;
            overflow-x: hidden;
            padding: 12px;
            border-radius: 10px;
            width: 100%;
        }
        .log-line {
            padding: 3px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            word-break: break-word;
            overflow-wrap: anywhere;
        }
        .log-line.ok { color: #4ade80; }
        .log-line.warn { color: #facc15; }
        .log-line.info { color: #38bdf8; }

        /* Tabelas Responsivas: Desktop = Tabela | Mobile = Cards Empilhados */
        .table-wrap {
            width: 100%;
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.81rem;
        }
        th, td {
            text-align: left;
            padding: 9px 8px;
            border-bottom: 1px solid #f1f5f9;
            word-break: break-word;
        }
        th {
            color: var(--muted);
            font-weight: 600;
            font-size: 0.72rem;
            text-transform: uppercase;
        }
        @media (max-width: 680px) {
            table, thead, tbody, th, td, tr {
                display: block;
                width: 100%;
            }
            thead tr {
                display: none;
            }
            tbody tr.data-row {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                padding: 10px 12px;
                margin-bottom: 10px;
            }
            tbody tr.data-row td {
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 10px;
                padding: 5px 0;
                border-bottom: 1px dashed #e2e8f0;
                text-align: right;
            }
            tbody tr.data-row td:last-child {
                border-bottom: none;
            }
            tbody tr.data-row td::before {
                content: attr(data-label);
                font-weight: 600;
                font-size: 0.73rem;
                color: #64748b;
                text-transform: uppercase;
                text-align: left;
                flex-shrink: 0;
            }
        }
        footer {
            text-align: center;
            font-size: 0.74rem;
            color: var(--muted);
            margin-top: 18px;
            padding: 0 12px;
        }
        ${PWA_INSTALL_CSS}
    </style>
</head>
<body>
    <header>
        <div class="header-inner">
            <div class="header-brand">
                <img src="/app-icon-192.png" alt="Saúdelab">
                <div class="header-title">
                    <h1>Saúdelab Exames — Triagem 24h</h1>
                    <p>Painel de Controle, QR Code e Auditoria ao Vivo</p>
                </div>
            </div>
            <div class="header-actions">
                <button type="button" class="btn-header-install" onclick="triggerInstallApp()">📲 Instalar App</button>
                <a href="/logout" class="btn-logout">Sair</a>
            </div>
        </div>
    </header>

    <div class="container">
        <!-- Card de Status + QR Code + Botões de Controle -->
        <div class="card">
            <div class="card-header">
                <h2>Conexão WhatsApp</h2>
                <span id="connBadge" class="badge badge-warn">CARREGANDO...</span>
            </div>
            <div class="info-row">
                <span>Número Conectado:</span>
                <strong id="phoneText">-</strong>
            </div>
            <div class="info-row">
                <span>Modo de Operação:</span>
                <strong id="modeText">-</strong>
            </div>
            <div class="info-row">
                <span>Timer de Ociosidade:</span>
                <strong id="timerText">5 min (até 2 avisos)</strong>
            </div>
            <div id="qrArea"></div>

            <div class="btn-group">
                <button id="btnToggleMode" class="btn btn-mode" onclick="toggleOperationMode()">
                    Alternar Modo (Teste / Produção 24h)
                </button>
                <button type="button" class="btn btn-install-card" onclick="triggerInstallApp()">
                    📲 Instalar Aplicativo na Tela Inicial
                </button>
                <button type="button" class="btn btn-disconnect" onclick="disconnectWhatsApp()">
                    Desconectar / Trocar WhatsApp (Gerar QR Code)
                </button>
            </div>
        </div>

        <!-- Card de Logs em Tempo Real -->
        <div class="card">
            <div class="card-header">
                <h2>Logs de Atividade em Tempo Real</h2>
                <span style="font-size:0.72rem; color:#64748b;">Atualiza a cada 3s</span>
            </div>
            <div id="logBox" class="log-box">Carregando logs...</div>
        </div>

        <!-- Card de Sessões Ativas -->
        <div class="card full-width">
            <div class="card-header">
                <h2>Conversas em Andamento / Pausadas para Recepcionista</h2>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Cliente</th>
                            <th>Etapa Atual</th>
                            <th>Avisos (5m)</th>
                            <th>Última Interação</th>
                        </tr>
                    </thead>
                    <tbody id="sessionsBody">
                        <tr><td colspan="4" style="color:#64748b;">Nenhuma conversa ativa no momento.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Card de Últimas Triagens Concluídas -->
        <div class="card full-width">
            <div class="card-header">
                <h2>Últimas Triagens Concluídas</h2>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Data/Hora</th>
                            <th>WhatsApp</th>
                            <th>Modalidade</th>
                            <th>Exames / Solicitação</th>
                            <th>Paciente</th>
                            <th>CPF / Nascimento</th>
                        </tr>
                    </thead>
                    <tbody id="triagensBody">
                        <tr><td colspan="6" style="color:#64748b;">Nenhuma triagem registrada ainda.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <footer>
        Criado por: Caio Araujo - Analista de TI | Build v${VERSION}
    </footer>

    ${PWA_INSTALL_SNIPPET}

    <script>
        ${PWA_INSTALL_JS}

        let currentTestMode = true;

        async function toggleOperationMode() {
            const targetMode = !currentTestMode;
            const msg = targetMode
                ? 'Deseja ativar o MODO TESTE? O bot responderá apenas quando enviarem a palavra #saudelab.'
                : 'Deseja ativar o MODO PRODUÇÃO 24H? O bot responderá automaticamente a todos os clientes que entrarem em contato.';
            if (!confirm(msg)) return;
            try {
                await fetch('/api/toggle-mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ test_mode: targetMode })
                });
                refreshPanel();
            } catch (e) {}
        }

        async function disconnectWhatsApp() {
            if (!confirm('Deseja desconectar o WhatsApp atual e gerar um novo QR Code para escanear?')) return;
            try {
                await fetch('/api/whatsapp-logout', { method: 'POST' });
                refreshPanel();
            } catch (e) {}
        }

        async function refreshPanel() {
            try {
                const r = await fetch('/api/live');
                if (r.status === 401) {
                    window.location.href = '/login';
                    return;
                }
                if (!r.ok) return;
                const d = await r.json();
                const st = d.engineStatus || {};
                currentTestMode = Boolean(st.test_mode);

                const badge = document.getElementById('connBadge');
                const isOk = d.connectionStatus.includes('CONECTADO');
                badge.textContent = d.connectionStatus;
                badge.className = 'badge ' + (isOk ? 'badge-ok' : 'badge-warn');

                document.getElementById('phoneText').textContent = d.connectedPhone || 'Aguardando leitura';
                document.getElementById('modeText').textContent = st.test_mode
                    ? 'MODO TESTE (' + (st.trigger_word || '#saudelab') + ')'
                    : 'PRODUÇÃO 24H (Todos os clientes)';

                const btnMode = document.getElementById('btnToggleMode');
                btnMode.textContent = st.test_mode
                    ? 'Ativar MODO PRODUÇÃO 24H (Todos os clientes)'
                    : 'Voltar para MODO TESTE (#saudelab)';
                btnMode.style.background = st.test_mode ? '#0f766e' : '#0369a1';

                document.getElementById('timerText').textContent =
                    (st.inactivity_minutes || 5) + ' min (até ' + (st.max_followups || 2) + ' avisos)';

                const qrArea = document.getElementById('qrArea');
                if (d.latestQrDataUrl && !isOk) {
                    qrArea.innerHTML = '<div class="qr-wrapper"><p style="font-size:0.82rem;margin-bottom:8px;color:#334155;">Abra o WhatsApp da clínica &gt; <b>Aparelhos conectados</b> &gt; <b>Conectar aparelho</b>:</p><img src="' + d.latestQrDataUrl + '" alt="QR Code WhatsApp"></div>';
                } else {
                    qrArea.innerHTML = '';
                }

                const logBox = document.getElementById('logBox');
                const logs = st.logs || [];
                if (logs.length === 0) {
                    logBox.innerHTML = '<div class="log-line">Nenhum evento registrado ainda.</div>';
                } else {
                    logBox.innerHTML = logs.map(line => {
                        let cls = 'log-line';
                        if (line.includes('CONCLUIDA') || line.includes('MENU_ENVIADO')) cls += ' ok';
                        else if (line.includes('INATIVIDADE') || line.includes('INVALIDO') || line.includes('CHAMADA')) cls += ' warn';
                        else if (line.includes('INTENCAO') || line.includes('AVANCO')) cls += ' info';
                        return '<div class="' + cls + '">' + line.replace(/</g, '&lt;') + '</div>';
                    }).join('');
                }

                const sessions = st.active_sessions || [];
                const sBody = document.getElementById('sessionsBody');
                if (sessions.length === 0) {
                    sBody.innerHTML = '<tr><td colspan="4" style="color:#64748b;">Nenhuma conversa ativa no momento.</td></tr>';
                } else {
                    sBody.innerHTML = sessions.map(s => {
                        const statusLabel = s.paused_for_human
                            ? '<span class="badge badge-ok">Com a Recepcionista</span>'
                            : '<span class="badge badge-warn">' + s.state + '</span>';
                        return '<tr class="data-row">'
                            + '<td data-label="Cliente"><b>' + (s.phone || '').split('@')[0] + '</b></td>'
                            + '<td data-label="Etapa Atual">' + statusLabel + '</td>'
                            + '<td data-label="Avisos (5m)">' + (s.followup_count || 0) + '/' + (st.max_followups || 2) + '</td>'
                            + '<td data-label="Última Interação">' + (s.updated_at || '-') + '</td>'
                            + '</tr>';
                    }).join('');
                }

                const triagens = st.recent_triagens || [];
                const tBody = document.getElementById('triagensBody');
                if (triagens.length === 0) {
                    tBody.innerHTML = '<tr><td colspan="6" style="color:#64748b;">Nenhuma triagem registrada ainda.</td></tr>';
                } else {
                    tBody.innerHTML = triagens.map(t => {
                        return '<tr class="data-row">'
                            + '<td data-label="Data/Hora">' + (t.created_at || '-') + '</td>'
                            + '<td data-label="WhatsApp">' + (t.phone || '').split('@')[0] + '</td>'
                            + '<td data-label="Modalidade">' + (t.modality || '-') + '</td>'
                            + '<td data-label="Exames">' + (t.exams || '-') + '</td>'
                            + '<td data-label="Paciente"><b>' + (t.patient_name || '-') + '</b></td>'
                            + '<td data-label="CPF / Nasc.">' + (t.cpf_or_birth || '-') + '</td>'
                            + '</tr>';
                    }).join('');
                }
            } catch (e) {}
        }

        refreshPanel();
        setInterval(refreshPanel, 3000);
    </script>
</body>
</html>`);
});

server.listen(STATUS_PORT, '0.0.0.0', () => {
    log(`Painel Web Autenticado + PWA disponível em: http://127.0.0.1:${STATUS_PORT}`);
});

// ==============================================================================
// COMUNICAÇÃO COM O MOTOR PYTHON
// ==============================================================================
async function callPythonMessage(jid, text, fromMe, isMedia, isAudio) {
    try {
        const resp = await fetch(`${ENGINE_URL}/api/message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jid, text, fromMe, isMedia, isAudio })
        });
        if (!resp.ok) return null;
        const data = await resp.json();
        return data.reply || null;
    } catch (err) {
        log(`Erro ao comunicar com motor Python: ${err.message}`);
        return null;
    }
}

async function callPythonMissedCall(jid) {
    try {
        const resp = await fetch(`${ENGINE_URL}/api/missed_call`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jid })
        });
        if (!resp.ok) return null;
        const data = await resp.json();
        return data.reply || null;
    } catch (err) {
        log(`Erro ao registrar chamada perdida no motor Python: ${err.message}`);
        return null;
    }
}

async function runInactivityCheck() {
    if (!currentSocket || connectionStatus !== 'CONECTADO COM SUCESSO') return;
    try {
        const resp = await fetch(`${ENGINE_URL}/api/inactivity`, { method: 'POST' });
        if (!resp.ok) return;
        const data = await resp.json();
        const items = data.items || [];

        for (const item of items) {
            if (!item.jid || !item.text) continue;
            const targetJid = item.jid.includes('@') ? item.jid : `${item.jid}@s.whatsapp.net`;
            const sentMsg = await currentSocket.sendMessage(targetJid, { text: item.text });
            if (sentMsg && sentMsg.key && sentMsg.key.id) {
                sentByBotIds.add(sentMsg.key.id);
            }
            log(`[INATIVIDADE - ${item.attempt}] Enviado para ${targetJid}`);
        }
    } catch (err) {
        log(`Erro no timer de inatividade: ${err.message}`);
    }
}

function extractMessageContent(message) {
    if (!message) return { text: '', isMedia: false, isAudio: false };

    if (message.ephemeralMessage?.message) {
        return extractMessageContent(message.ephemeralMessage.message);
    }
    if (message.viewOnceMessage?.message) {
        return extractMessageContent(message.viewOnceMessage.message);
    }
    if (message.viewOnceMessageV2?.message) {
        return extractMessageContent(message.viewOnceMessageV2.message);
    }

    if (message.audioMessage) {
        return { text: '[Áudio enviado pelo cliente]', isMedia: false, isAudio: true };
    }

    const text = (
        message.conversation ||
        message.extendedTextMessage?.text ||
        message.imageMessage?.caption ||
        message.documentMessage?.caption ||
        message.buttonsResponseMessage?.selectedDisplayText ||
        message.listResponseMessage?.title ||
        ''
    ).trim();

    if (message.imageMessage || message.documentMessage || message.documentWithCaptionMessage) {
        return {
            text: text || '[Foto/ Arquivo do Pedido Médico enviado]',
            isMedia: true,
            isAudio: false
        };
    }

    return { text, isMedia: false, isAudio: false };
}

// ==============================================================================
// CONEXÃO BAILEYS WHATSAPP (MENSAGENS + ÁUDIOS + CHAMADAS NÃO ATENDIDAS)
// ==============================================================================
async function startBot() {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion();

    const sock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'silent' }),
        browser: ['Saudelab Triagem', 'Chrome', '4.1.0'],
        syncFullHistory: false,
        markOnlineOnConnect: false
    });

    currentSocket = sock;
    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            connectionStatus = 'AGUARDANDO LEITURA DO QR CODE';
            qrcodeTerminal.generate(qr, { small: true });
            latestQrDataUrl = await QRCode.toDataURL(qr, { width: 320, margin: 1 });
            log(`QR Code gerado! Acesse http://127.0.0.1:${STATUS_PORT} para escanear.`);
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            connectionStatus = 'DESCONECTADO (RECONECTANDO...)';
            log(`Conexão fechada (código: ${statusCode}). Reconectar: ${shouldReconnect}`);
            if (shouldReconnect) {
                setTimeout(() => startBot(), 3000);
            } else {
                connectionStatus = 'DESCONECTADO (NECESSÁRIO NOVO QR CODE)';
            }
        } else if (connection === 'open') {
            connectionStatus = 'CONECTADO COM SUCESSO';
            latestQrDataUrl = null;
            connectedPhone = (sock.user?.id || '').split(':')[0];
            log(`WhatsApp CONECTADO (${connectedPhone})`);

            if (inactivityTimer) clearInterval(inactivityTimer);
            inactivityTimer = setInterval(runInactivityCheck, 15000);
        }
    });

    sock.ev.on('call', async (calls) => {
        for (const call of calls) {
            const callId = call.id;
            const callerJid = call.from || call.chatId || '';
            if (!callerJid || callerJid.endsWith('@g.us')) continue;

            if (call.status === 'offer') {
                activeCalls.set(callId, { fromJid: callerJid, answered: false });
                log(`[CHAMADA RECEBIDA] Ligação recebida de ${callerJid} (aguardando atendimento...)`);
            } else if (call.status === 'accept') {
                const info = activeCalls.get(callId) || { fromJid: callerJid, answered: true };
                info.answered = true;
                activeCalls.set(callId, info);
                log(`[CHAMADA ATENDIDA] Ligação de ${callerJid} foi atendida pela equipe. Bot não enviará mensagem.`);
            } else if (call.status === 'timeout' || call.status === 'reject' || call.status === 'terminate') {
                const info = activeCalls.get(callId);
                const wasAnswered = info ? info.answered : false;
                activeCalls.delete(callId);

                if (!wasAnswered && (call.status === 'timeout' || call.status === 'reject' || call.status === 'terminate')) {
                    log(`[CHAMADA NÃO ATENDIDA] Ligação perdida de ${callerJid} (${call.status}). Verificando envio da triagem...`);
                    const reply = await callPythonMissedCall(callerJid);
                    if (reply) {
                        const sent = await sock.sendMessage(callerJid, { text: reply });
                        if (sent?.key?.id) sentByBotIds.add(sent.key.id);
                        log(`Triagem enviada para chamada perdida de ${callerJid}`);
                    }
                }
            }
        }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;

        for (const msg of messages) {
            try {
                if (!msg.message) continue;

                const msgId = msg.key.id;
                if (sentByBotIds.has(msgId)) {
                    sentByBotIds.delete(msgId);
                    continue;
                }

                const remoteJid = msg.key.remoteJid || '';
                if (!remoteJid || remoteJid.endsWith('@g.us') || remoteJid === 'status@broadcast' || remoteJid.includes('@newsletter')) {
                    continue;
                }

                const fromMe = Boolean(msg.key.fromMe);
                const { text, isMedia, isAudio } = extractMessageContent(msg.message);
                if (!text && !isMedia && !isAudio) continue;

                const reply = await callPythonMessage(remoteJid, text, fromMe, isMedia, isAudio);
                if (reply) {
                    const sent = await sock.sendMessage(remoteJid, { text: reply });
                    if (sent && sent.key && sent.key.id) {
                        sentByBotIds.add(sent.key.id);
                    }
                    log(`Respondido para ${remoteJid}`);
                }
            } catch (err) {
                log(`Erro ao processar mensagem: ${err.message}`);
            }
        }
    });
}

startPythonEngine();
setTimeout(() => startBot(), 1200);

// Auto Keep-Alive para hospedagem gratuita em nuvem (Render / Koyeb)
const externalUrl = process.env.RENDER_EXTERNAL_URL || process.env.PUBLIC_URL || (process.env.KOYEB_PUBLIC_DOMAIN ? `https://${process.env.KOYEB_PUBLIC_DOMAIN}` : '');
if (externalUrl) {
    const pingUrl = `${externalUrl.replace(/\/$/, '')}/health`;
    setInterval(() => {
        fetch(pingUrl).catch(() => {});
    }, 240000);
}
