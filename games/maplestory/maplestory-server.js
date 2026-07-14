/* =========================================================
   메이플 클론 스토리 — 멀티플레이 서버 (의존성 0개)
   실행:  node maplestory-server.js  [포트]
   접속:  http://localhost:3000  (같은 공유기/LAN 친구는 표시되는 IP로)
   ========================================================= */
"use strict";
const http = require("http");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const os = require("os");

const SHARED = require("./maplestory-shared.js");
const PORT = parseInt(process.argv[2] || process.env.PORT || "3000", 10);
const ROOT = __dirname;

// ---------- 게임 호스트 ----------
const host = new SHARED.GameHost();
const sockets = new Map(); // id -> socket
host.onSend = (id, msg) => {
  const s = sockets.get(id);
  if (s && !s.destroyed) wsSendText(s, JSON.stringify(msg));
};
setInterval(() => host.tick(Date.now()), 100);

// ---------- 캐릭터 영구 저장 (maplestory-saves.json) ----------
const SAVE_FILE = path.join(ROOT, "maplestory-saves.json");
let saves = {};
try { saves = JSON.parse(fs.readFileSync(SAVE_FILE, "utf8")) || {}; } catch (e) {}
let saveDirty = false;
host.persist = {
  load: (name) => saves[name] || null,
  save: (name, data) => {
    if (!name || JSON.stringify(data).length > 20000) return;
    saves[name] = data;
    saveDirty = true;
  },
};
setInterval(() => {
  if (!saveDirty) return;
  saveDirty = false;
  fs.writeFile(SAVE_FILE, JSON.stringify(saves), (err) => {
    if (err) console.error("저장 실패:", err.message);
  });
}, 4000);

// ---------- 정적 파일 ----------
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png", ".ico": "image/x-icon", ".svg": "image/svg+xml",
};
const server = http.createServer((req, res) => {
  if (req.method !== "GET") { res.writeHead(405); res.end(); return; }
  let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
  if (urlPath === "/") urlPath = "/maplestory.html";
  const file = path.normalize(path.join(ROOT, urlPath));
  if (!file.startsWith(ROOT)) { res.writeHead(403); res.end(); return; }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }); res.end("404 Not Found"); return; }
    res.writeHead(200, { "Content-Type": MIME[path.extname(file).toLowerCase()] || "application/octet-stream" });
    res.end(data);
  });
});

// ---------- WebSocket (직접 구현) ----------
const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const MAX_PAYLOAD = 64 * 1024;

function wsFrame(opcode, payload) {
  const len = payload.length;
  let header;
  if (len < 126) {
    header = Buffer.alloc(2);
    header[1] = len;
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(len), 2);
  }
  header[0] = 0x80 | opcode;
  return Buffer.concat([header, payload]);
}
function wsSendText(sock, str) {
  try { sock.write(wsFrame(0x1, Buffer.from(str, "utf8"))); } catch (e) {}
}
function wsSendRaw(sock, opcode, payload) {
  try { sock.write(wsFrame(opcode, payload || Buffer.alloc(0))); } catch (e) {}
}

function attachWS(sock, onMessage, onClose) {
  let buf = Buffer.alloc(0);
  let frags = null;
  let closed = false;
  const close = () => { if (closed) return; closed = true; onClose(); try { sock.destroy(); } catch (e) {} };

  sock.on("data", (chunk) => {
    buf = buf.length ? Buffer.concat([buf, chunk]) : chunk;
    while (true) {
      if (buf.length < 2) break;
      const b0 = buf[0], b1 = buf[1];
      const fin = (b0 & 0x80) !== 0;
      const op = b0 & 0x0f;
      const masked = (b1 & 0x80) !== 0;
      let len = b1 & 0x7f;
      let off = 2;
      if (len === 126) {
        if (buf.length < 4) break;
        len = buf.readUInt16BE(2);
        off = 4;
      } else if (len === 127) {
        if (buf.length < 10) break;
        const big = buf.readBigUInt64BE(2);
        if (big > BigInt(MAX_PAYLOAD)) { close(); return; }
        len = Number(big);
        off = 10;
      }
      if (len > MAX_PAYLOAD) { close(); return; }
      let mask = null;
      if (masked) {
        if (buf.length < off + 4) break;
        mask = buf.slice(off, off + 4);
        off += 4;
      }
      if (buf.length < off + len) break;
      let payload = Buffer.from(buf.slice(off, off + len)); // 복사본 (마스킹 해제용)
      buf = buf.slice(off + len);
      if (mask) for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i & 3];

      if (op === 0x8) { // close
        try { sock.write(wsFrame(0x8, Buffer.alloc(0))); } catch (e) {}
        close();
        return;
      } else if (op === 0x9) { // ping
        wsSendRaw(sock, 0xA, payload);
      } else if (op === 0xA) {
        // pong — 무시
      } else if (op === 0x1 || op === 0x2 || op === 0x0) {
        if (op !== 0x0 && !fin) { frags = [payload]; continue; }
        if (op === 0x0) {
          if (!frags) continue;
          frags.push(payload);
          if (!fin) continue;
          payload = Buffer.concat(frags);
          frags = null;
        }
        onMessage(payload.toString("utf8"));
      }
    }
  });
  sock.on("close", close);
  sock.on("error", close);
  sock.on("end", close);
  return { close };
}

let nextId = 1;
server.on("upgrade", (req, sock, head) => {
  const key = req.headers["sec-websocket-key"];
  if (!key || (req.headers.upgrade || "").toLowerCase() !== "websocket") { sock.destroy(); return; }
  const accept = crypto.createHash("sha1").update(key + WS_GUID).digest("base64");
  sock.write(
    "HTTP/1.1 101 Switching Protocols\r\n" +
    "Upgrade: websocket\r\n" +
    "Connection: Upgrade\r\n" +
    "Sec-WebSocket-Accept: " + accept + "\r\n\r\n"
  );
  sock.setNoDelay(true);

  const id = "p" + (nextId++) + Math.random().toString(36).slice(2, 6);
  sockets.set(id, sock);
  host.addPlayer(id); // 게임 호스트에 플레이어 등록 (hello 전송)
  console.log("[+] 연결: " + id + " (" + (req.socket.remoteAddress || "?") + ")");

  if (head && head.length) sock.unshift(head); // 핸드셰이크 직후 도착한 데이터 보존

  attachWS(
    sock,
    (text) => {
      let msg = null;
      try { msg = JSON.parse(text); } catch (e) { return; }
      try { host.handle(id, msg); } catch (e) { console.error("handle 오류:", e.message); }
    },
    () => {
      if (sockets.has(id)) {
        sockets.delete(id);
        host.removePlayer(id);
        console.log("[-] 종료: " + id);
      }
    }
  );
});

// 25초마다 ping (연결 유지)
setInterval(() => {
  sockets.forEach((s) => { if (!s.destroyed) wsSendRaw(s, 0x9, Buffer.alloc(0)); });
}, 25000);

// ---------- 시작 ----------
server.listen(PORT, () => {
  const ips = [];
  const ifs = os.networkInterfaces();
  for (const name in ifs) {
    for (const ni of ifs[name]) {
      if (ni.family === "IPv4" && !ni.internal) ips.push(ni.address);
    }
  }
  console.log("==============================================");
  console.log("  🍁 메이플 클론 스토리 — 멀티플레이 서버");
  console.log("==============================================");
  console.log("  본인 접속  : http://localhost:" + PORT);
  ips.forEach((ip) => console.log("  친구 접속  : http://" + ip + ":" + PORT + "  (같은 네트워크)"));
  console.log("  종료       : Ctrl + C");
  console.log("==============================================");
});
