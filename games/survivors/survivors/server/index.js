// Survivors 멀티 서버 — 정적 파일 + WebSocket 릴레이를 한 포트에서.
//
// 배포 형태가 이 설계를 강제한다: Caddy가 `/survivors/*` 하위경로 하나를 단일 포트로 프록시하므로,
// 게임 파일과 WS가 같은 오리진·같은 포트에 있어야 한다(별도 WS 포트를 열면 서브경로 프록시가 깨진다).
// 게임 로직은 여기 0줄 — 권위는 방장 브라우저다. 밸런스를 고쳐도 이 서버는 재배포가 필요 없다.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, extname, normalize, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { WebSocketServer } from 'ws';
import { SurvivorsHub } from '../net/hub.js';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.glb': 'model/gltf-binary',
  '.gltf': 'model/gltf+json',
  '.bin': 'application/octet-stream',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.wav': 'audio/wav',
  '.ogg': 'audio/ogg',
  '.mp3': 'audio/mpeg',
  '.ico': 'image/x-icon',
};

export function createSurvivorsServer({
  host = '0.0.0.0',
  port = 3010,
  root: rootOpt = resolve(process.cwd(), 'dist'),
  wsPath = '/ws',
  logger = console,
} = {}) {
  const root = resolve(rootOpt); // 경로 탈출 검사가 문자열 비교라 양쪽 다 정규화해야 한다
  const hub = new SurvivorsHub({ logger });
  const startedAt = Date.now();

  const server = createServer(async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host ?? 'localhost'}`);

    if (url.pathname === '/healthz') {
      const body = JSON.stringify({ ok: true, service: 'survivors', uptimeSeconds: Math.floor((Date.now() - startedAt) / 1000), ...hub.status() });
      res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
      return res.end(body);
    }

    // 정적 파일 — 경로 탈출(../) 차단 후 root 아래만 서빙
    let rel = decodeURIComponent(url.pathname);
    if (rel.endsWith('/')) rel += 'index.html';
    const safe = normalize(rel).replace(/^(\.\.[/\\])+/, '').replace(/^[/\\]+/, '');
    const file = resolve(root, safe);
    if (!file.startsWith(root)) { res.writeHead(403); return res.end('Forbidden'); }

    try {
      const info = await stat(file);
      if (info.isDirectory()) throw new Error('EISDIR');
      const data = await readFile(file);
      const ext = extname(file).toLowerCase();
      res.writeHead(200, {
        'content-type': MIME[ext] ?? 'application/octet-stream',
        'content-length': data.length,
        // 에셋(GLB/오디오)은 수십 MB — 캐시가 없으면 재접속마다 전부 다시 받는다
        'cache-control': ext === '.html' ? 'no-cache' : 'public, max-age=604800',
      });
      res.end(data);
    } catch {
      // SPA 폴백: 알 수 없는 경로는 index.html (딥링크 ?room=XXXXX 지원)
      try {
        const html = await readFile(join(root, 'index.html'));
        res.writeHead(200, { 'content-type': MIME['.html'], 'cache-control': 'no-cache' });
        res.end(html);
      } catch {
        res.writeHead(404);
        res.end('Not found');
      }
    }
  });

  const wss = new WebSocketServer({ noServer: true, maxPayload: hub.maxPacketBytes });
  const ipCounts = new Map();
  const MAX_PER_IP = 8;

  server.on('upgrade', (req, socket, head) => {
    const url = new URL(req.url, `http://${req.headers.host ?? 'localhost'}`);
    // Caddy handle_path가 접두사를 떼므로 서버에는 /ws로 도착한다. 접미 일치로 둘 다 받는다.
    if (!url.pathname.endsWith(wsPath)) {
      socket.write('HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n');
      return socket.destroy();
    }
    const ip = req.socket.remoteAddress ?? 'unknown';
    if ((ipCounts.get(ip) ?? 0) >= MAX_PER_IP) {
      socket.write('HTTP/1.1 429 Too Many Requests\r\nConnection: close\r\n\r\n');
      return socket.destroy();
    }
    wss.handleUpgrade(req, socket, head, (client) => wss.emit('connection', client, req));
  });

  wss.on('connection', (socket, req) => {
    const ip = req.socket.remoteAddress ?? 'unknown';
    ipCounts.set(ip, (ipCounts.get(ip) ?? 0) + 1);
    socket.isAlive = true;
    socket.on('pong', () => { socket.isAlive = true; });
    socket.once('close', () => {
      const next = (ipCounts.get(ip) ?? 1) - 1;
      if (next > 0) ipCounts.set(ip, next); else ipCounts.delete(ip);
    });
    hub.connect(socket, { ip, origin: req.headers.origin });
  });

  // 죽은 소켓 청소 — 브라우저 탭을 그냥 닫으면 close가 안 오는 경우가 있다
  const sweepTimer = setInterval(() => hub.sweep(), 1000);
  const beatTimer = setInterval(() => {
    for (const s of wss.clients) {
      if (s.isAlive === false) { s.terminate(); continue; }
      s.isAlive = false;
      s.ping();
    }
  }, 30_000);
  sweepTimer.unref?.();
  beatTimer.unref?.();

  return {
    server, wss, hub,
    async listen() {
      await new Promise((res, rej) => {
        server.once('error', rej);
        server.listen(port, host, () => { server.off('error', rej); res(); });
      });
      logger?.info?.(`survivors: http://${host}:${port}  (ws ${wsPath}, root ${root})`);
      return server.address();
    },
    async close() {
      clearInterval(sweepTimer);
      clearInterval(beatTimer);
      for (const s of wss.clients) s.close(1001, 'SERVER_SHUTDOWN');
      await new Promise((r) => wss.close(r));
      if (server.listening) await new Promise((r, j) => server.close((e) => (e ? j(e) : r())));
    },
  };
}

// 직접 실행 시 (systemd). pathToFileURL로 비교해야 한다 — 문자열 조립은 Windows 백슬래시와
// URL 인코딩(한글 경로) 때문에 조용히 어긋나서, 서버가 아무 로그도 없이 즉시 종료한다(실측).
if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  const srv = createSurvivorsServer({
    port: Number(process.env.PORT ?? 3010),
    host: process.env.HOST ?? '0.0.0.0',
    root: process.env.STATIC_ROOT ?? resolve(process.cwd(), 'dist'),
  });
  await srv.listen();
  for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => srv.close().then(() => process.exit(0)));
}
