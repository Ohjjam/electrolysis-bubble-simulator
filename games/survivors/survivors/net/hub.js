// Survivors 릴레이 허브 — 방 관리 + 중계. 게임 로직은 0줄이다(권위는 방장 브라우저).
//
// brawler/network/RelayHub.js의 방어 규약을 그대로 따른다: 패킷 크기 상한, 초당 메시지 상한,
// 시퀀스 역행 차단, 호스트 전용 패킷 강제. 이 방벽이 없으면 악의적 클라 하나가 방을 죽인다.
// (RelayHub 자체를 쓰지 않는 이유: 그쪽은 brawler의 직업/원정/계정 원장에 깊게 묶여 있다.)
import { RoomRegistry } from '../../engine/src/net/RoomRegistry.js';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import { C2S, HOST_ONLY, MAX_PLAYERS, validInput, validSnapshot } from './protocol.js';
import { DIFFICULTY_IDS, normalizeDifficulty } from '../data/difficulty.js';

const CLIENT_TYPES = new Set(C2S);
const HOST_TYPES = new Set(HOST_ONLY);
const ID_PATTERN = /^[A-Za-z0-9_-]{3,64}$/;
const ROOM_PATTERN = /^[A-HJ-NP-Z2-9]{5}$/;
const CHAR_IDS = new Set(['knight', 'mage', 'rogue', 'archer']);
const STAGE_IDS = new Set(['meadow', 'snowfield', 'ashland']);
const DIFFICULTY_ID_SET = new Set(DIFFICULTY_IDS);

// 제거 대상은 꺾쇠와 제어문자뿐 (HTML 주입·터미널 이스케이프 방지). 공백·하이픈은 이름에 남긴다.
// ⚠ 반드시 이스케이프 표기로 쓸 것 — 리터럴 제어문자를 소스에 박으면 grep이 이 파일을
//   바이너리로 오인해 검색/리뷰 도구가 통째로 눈이 먼다(실측).
const CTRL = /[<>\u0000-\u001f]/g;
const clean = (v, max = 40) => String(v ?? '').replace(CTRL, '').trim().slice(0, max);
const tokenMatches = (expected, provided) => {
  if (!expected || !provided) return false;
  const a = Buffer.from(String(expected)), b = Buffer.from(String(provided));
  return a.length === b.length && timingSafeEqual(a, b);
};

export function sanitizeProfile(profile = {}) {
  return {
    name: clean(profile.name, 12) || '모험가',
    charId: CHAR_IDS.has(profile.charId) ? profile.charId : null, // null = 아직 미선택
    ready: Boolean(profile.ready),
  };
}

export class SurvivorsHub {
  constructor({
    registry = new RoomRegistry({ capacity: MAX_PLAYERS, reconnectMs: 15_000 }),
    maxPacketBytes = 256 * 1024, // 스냅샷(몹 200+)이 커서 brawler(64KB)보다 넉넉히
    maxMessagesPerSecond = 240,
    maxRooms = 500,
    strikeLimit = 4,
    now = Date.now,
    tokenFactory = () => randomBytes(24).toString('base64url'),
    logger = null,
  } = {}) {
    Object.assign(this, { registry, maxPacketBytes, maxMessagesPerSecond, maxRooms, strikeLimit, now, tokenFactory, logger });
    this.clients = new Set();
    this.metrics = { accepted: 0, rejected: 0, messages: 0, bytesIn: 0, bytesOut: 0, roomsCreated: 0, joins: 0 };
  }

  connect(socket, meta = {}) {
    const client = {
      socket, meta, roomCode: null, playerId: null, strikes: 0,
      windowStartedAt: this.now(), messagesInWindow: 0, lastSeq: new Map(), closed: false,
    };
    this.clients.add(client);
    this.metrics.accepted++;
    socket.on('message', (raw) => this._onMessage(client, raw));
    socket.on('close', () => this.disconnect(client));
    socket.on('error', (e) => this.logger?.warn?.('relay socket error', { ip: meta.ip, error: e?.message }));
    return client;
  }

  disconnect(client) {
    if (!client || client.closed) return;
    client.closed = true;
    this.clients.delete(client);
    const room = this.registry.rooms.get(client.roomCode);
    const player = room?.players.get(client.playerId);
    if (player?.socket && player.socket !== client.socket) return; // 이미 재접속으로 대체됨
    const result = this.registry.disconnect(client.roomCode, client.playerId, this.now());
    if (result.room) this.sendRoster(result.room);
  }

  _send(socket, packet) {
    if (socket?.readyState !== 1) return false;
    const payload = JSON.stringify(packet);
    socket.send(payload);
    this.metrics.bytesOut += Buffer.byteLength(payload);
    return true;
  }

  _reject(client, code, { strike = true, close = false } = {}) {
    this.metrics.rejected++;
    if (strike) client.strikes++;
    this._send(client.socket, { type: 'error', code });
    if (close || client.strikes >= this.strikeLimit) client.socket.close?.(1008, code);
  }

  _rateAllowed(client) {
    const now = this.now();
    if (now - client.windowStartedAt >= 1000) { client.windowStartedAt = now; client.messagesInWindow = 0; }
    return ++client.messagesInWindow <= this.maxMessagesPerSecond;
  }

  /** input/snapshot은 시퀀스 역행/재전송을 거부 — 오래된 입력이 뒤늦게 적용되면 캐릭터가 순간이동한다 */
  _seqAllowed(client, packet) {
    if (packet.type !== 'input' && packet.type !== 'snapshot') return true;
    const seq = Number(packet.seq);
    if (!Number.isSafeInteger(seq) || seq < 1) return false;
    const prev = client.lastSeq.get(packet.type) ?? 0;
    if (seq <= prev) return false;
    client.lastSeq.set(packet.type, seq);
    return true;
  }

  _onMessage(client, raw) {
    const size = typeof raw === 'string' ? Buffer.byteLength(raw) : raw?.byteLength ?? raw?.length ?? 0;
    this.metrics.messages++;
    this.metrics.bytesIn += size;
    if (size <= 0 || size > this.maxPacketBytes) return this._reject(client, 'PACKET_TOO_LARGE', { close: size > this.maxPacketBytes });
    if (!this._rateAllowed(client)) return this._reject(client, 'RATE_LIMITED', { close: true });

    let packet;
    try { packet = JSON.parse(String(raw)); } catch { return this._reject(client, 'INVALID_JSON'); }
    if (!packet || typeof packet !== 'object' || !CLIENT_TYPES.has(packet.type)) return this._reject(client, 'INVALID_PACKET');
    if (!this._seqAllowed(client, packet)) return this._reject(client, 'INVALID_SEQUENCE');

    if (packet.type === 'create') return this._create(client, packet);
    if (packet.type === 'join') return this._join(client, packet);

    const room = this.registry.rooms.get(client.roomCode);
    if (!room || !client.playerId || !room.players.has(client.playerId)) return this._reject(client, 'NOT_IN_ROOM', { strike: false });
    if (HOST_TYPES.has(packet.type) && client.playerId !== room.hostId) return this._reject(client, 'HOST_ONLY');

    switch (packet.type) {
      case 'lobby': {
        // 캐릭터 선택 — 서버가 중복을 막는다. 클라만 믿으면 동시 클릭에 같은 캐릭터가 둘 생긴다.
        const charId = clean(packet.charId, 12);
        const rec = room.players.get(client.playerId);
        if (charId && !CHAR_IDS.has(charId)) return this._reject(client, 'INVALID_CHARACTER', { strike: false });
        if (charId) {
          for (const [id, other] of room.players) {
            if (id !== client.playerId && other.profile.charId === charId) return this._reject(client, 'CHARACTER_TAKEN', { strike: false });
          }
        }
        rec.profile = sanitizeProfile({ ...rec.profile, charId: charId || null, ready: packet.ready ?? rec.profile.ready });
        this.sendRoster(room);
        break;
      }
      case 'start': {
        // 방장이 시작 — 시드와 파티 구성을 전원에게 확정 배포 (시드가 같아야 봇/재현 검증이 성립)
        const stageId = clean(packet.stageId, 20);
        const difficultyId = clean(packet.difficultyId ?? 'normal', 20);
        if (!STAGE_IDS.has(stageId)) return this._reject(client, 'INVALID_STAGE', { strike: false });
        if (!DIFFICULTY_ID_SET.has(difficultyId)) return this._reject(client, 'INVALID_DIFFICULTY', { strike: false });
        const party = [...room.players.values()]
          .filter((p) => p.profile.charId)
          .map((p, i) => ({ index: i, playerId: p.id, charId: p.profile.charId, name: p.profile.name }));
        if (!party.length) return this._reject(client, 'NO_CHARACTERS', { strike: false });
        room.run = { stageId, difficultyId: normalizeDifficulty(difficultyId), seed: Number(packet.seed) >>> 0, party, startedAt: this.now() };
        this.broadcast(room, { type: 'start', ...room.run });
        break;
      }
      case 'input': {
        if (!validInput(packet.state)) return this._reject(client, 'INVALID_INPUT');
        if (client.playerId === room.hostId) break; // 방장 입력은 로컬에서 바로 먹는다 — 왕복시킬 이유가 없다
        const host = room.players.get(room.hostId);
        this._send(host?.socket, { type: 'input', playerId: client.playerId, seq: packet.seq, state: packet.state });
        break;
      }
      case 'snapshot': {
        if (!validSnapshot(packet.state)) return this._reject(client, 'INVALID_SNAPSHOT');
        room.lastSnapshot = packet.state;
        this.broadcast(room, { type: 'snapshot', seq: packet.seq, state: packet.state }, client.socket);
        break;
      }
      case 'pick': {
        // 레벨업 카드 선택 — 게스트 → 방장
        const idx = Number(packet.cardIdx);
        if (!Number.isInteger(idx) || idx < 0 || idx > 5) return this._reject(client, 'INVALID_PICK', { strike: false });
        const host = room.players.get(room.hostId);
        this._send(host?.socket, { type: 'pick', playerId: client.playerId, cardIdx: idx });
        break;
      }
      case 'interact': {
        const host = room.players.get(room.hostId);
        this._send(host?.socket, { type: 'interact', playerId: client.playerId });
        break;
      }
      case 'event': {
        // 방장 → 전원: 배너/부활/레벨업 카드 배포 등 (게임 로직이 아니라 알림)
        this.broadcast(room, { type: 'event', event: packet.event }, client.socket);
        break;
      }
      case 'chat': {
        const text = clean(packet.text, 80);
        if (text) this.broadcast(room, { type: 'chat', playerId: client.playerId, text });
        break;
      }
    }
  }

  _create(client, packet) {
    if (client.playerId) return this._reject(client, 'ALREADY_IN_ROOM');
    const playerId = String(packet.playerId ?? '');
    if (!ID_PATTERN.test(playerId)) return this._reject(client, 'INVALID_PLAYER_ID');
    if (this.registry.rooms.size >= this.maxRooms) return this._reject(client, 'SERVER_FULL', { strike: false });

    const room = this.registry.create(playerId, sanitizeProfile(packet.profile));
    const rec = room.players.get(playerId);
    rec.resumeToken = this.tokenFactory();
    rec.socket = client.socket;
    client.playerId = playerId;
    client.roomCode = room.code;
    this.metrics.roomsCreated++;
    this._send(client.socket, { type: 'room_created', room: room.code, hostId: playerId, resumeToken: rec.resumeToken });
    this.sendRoster(room);
  }

  _join(client, packet) {
    if (client.playerId) return this._reject(client, 'ALREADY_IN_ROOM');
    const playerId = String(packet.playerId ?? '');
    const code = String(packet.room ?? '').trim().toUpperCase();
    if (!ID_PATTERN.test(playerId)) return this._reject(client, 'INVALID_PLAYER_ID');
    if (!ROOM_PATTERN.test(code)) return this._reject(client, 'INVALID_ROOM_CODE', { strike: false });

    // 같은 playerId로 재입장하려면 서버가 발급한 토큰이 있어야 한다 — 없으면 남의 슬롯 탈취가 된다
    const existingRoom = this.registry.rooms.get(code);
    const existing = existingRoom?.players.get(playerId);
    if (existing && !tokenMatches(existing.resumeToken, packet.resumeToken)) {
      return this._reject(client, 'RECONNECT_TOKEN_REQUIRED', { strike: false });
    }

    const result = this.registry.join(code, playerId, sanitizeProfile(packet.profile));
    if (!result.ok) return this._reject(client, result.reason, { strike: false });

    const rec = result.room.players.get(playerId);
    if (!rec.resumeToken) rec.resumeToken = this.tokenFactory();
    if (rec.socket && rec.socket !== client.socket && rec.socket.readyState === 1) rec.socket.close?.(4001, 'REPLACED_BY_RECONNECT');
    rec.socket = client.socket;
    client.playerId = playerId;
    client.roomCode = result.room.code;
    this.metrics.joins++;

    this._send(client.socket, {
      type: 'joined', room: result.room.code, hostId: result.room.hostId,
      reconnect: result.reconnect, resumeToken: rec.resumeToken,
    });
    this.sendRoster(result.room);
    // 진행 중인 판에 복귀 — 시작 정보와 최신 스냅샷을 즉시 던져준다
    if (result.room.run) this._send(client.socket, { type: 'start', ...result.room.run, reconnect: true });
    if (result.room.lastSnapshot) this._send(client.socket, { type: 'snapshot', state: result.room.lastSnapshot, reconnect: true });
  }

  broadcast(room, packet, except = null) {
    for (const p of room.players.values()) if (p.socket !== except) this._send(p.socket, packet);
  }

  sendRoster(room) {
    this.broadcast(room, {
      type: 'roster',
      room: room.code,
      hostId: room.hostId,
      players: [...room.players.values()].map(({ id, profile, connected }) => ({ id, profile, connected, host: id === room.hostId })),
    });
  }

  /** 방장이 재접속 유예를 넘겨 사라지면 방을 닫는다 — 권위가 없으면 게임이 진행될 수 없다 */
  sweep(now = this.now()) {
    const closed = this.registry.sweep(now);
    for (const room of closed) this.broadcast(room, { type: 'room_closed', reason: 'HOST_LEFT' });
    return closed;
  }

  status() {
    return {
      rooms: this.registry.rooms.size,
      clients: this.clients.size,
      connectedPlayers: [...this.registry.rooms.values()]
        .reduce((n, r) => n + [...r.players.values()].filter((p) => p.connected).length, 0),
      ...this.metrics,
    };
  }
}
