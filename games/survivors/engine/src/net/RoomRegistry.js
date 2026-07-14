const ROOM_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

export function makeRoomCode(random = Math.random) {
  return Array.from({ length: 5 }, () => ROOM_ALPHABET[Math.floor(random() * ROOM_ALPHABET.length)]).join('');
}

export class RoomRegistry {
  constructor({ capacity = 4, reconnectMs = 10_000, random = Math.random } = {}) {
    this.capacity = capacity; this.reconnectMs = reconnectMs; this.random = random; this.rooms = new Map();
  }

  create(playerId, profile = {}) {
    let code; do code = makeRoomCode(this.random); while (this.rooms.has(code));
    const room = { code, hostId: playerId, players: new Map(), createdAt: Date.now() };
    room.players.set(playerId, { id: playerId, profile, connected: true, lastSeen: Date.now() }); this.rooms.set(code, room); return room;
  }

  join(code, playerId, profile = {}) {
    const room = this.rooms.get(String(code).toUpperCase());
    if (!room) return { ok: false, reason: 'ROOM_NOT_FOUND' };
    const existing = room.players.get(playerId);
    if (existing) { Object.assign(existing, { profile, connected: true, lastSeen: Date.now() }); return { ok: true, room, reconnect: true }; }
    if (room.players.size >= this.capacity) return { ok: false, reason: 'ROOM_FULL' };
    room.players.set(playerId, { id: playerId, profile, connected: true, lastSeen: Date.now() }); return { ok: true, room, reconnect: false };
  }

  disconnect(code, playerId, now = Date.now()) {
    const room = this.rooms.get(code); if (!room) return { closed: false };
    const player = room.players.get(playerId); if (player) Object.assign(player, { connected: false, lastSeen: now });
    return { closed: false, hostDisconnected: playerId === room.hostId, room };
  }

  sweep(now = Date.now()) {
    const closedRooms = [];
    for (const [code, room] of this.rooms) {
      const host = room.players.get(room.hostId);
      if (!host?.connected && now - (host?.lastSeen ?? room.createdAt) > this.reconnectMs) {
        this.rooms.delete(code); closedRooms.push(room); continue;
      }
      for (const [id, player] of room.players) if (!player.connected && now - player.lastSeen > this.reconnectMs) room.players.delete(id);
      if (!room.players.size) this.rooms.delete(code);
    }
    return closedRooms;
  }

  roster(room) { return [...room.players.values()].map(({ id, profile, connected }) => ({ id, profile, connected, host: id === room.hostId })); }
}
