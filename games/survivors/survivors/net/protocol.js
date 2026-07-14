// Survivors 멀티 프로토콜 — 방장 권위(host-authoritative).
//
// 방장의 브라우저가 기존 싱글 시뮬(몹·전투·보스·드랍)을 그대로 돌리는 유일한 권위다.
// 게스트는 ①입력을 올리고 ②스냅샷을 받아 렌더만 한다. 서버는 방 관리 + 중계만 하는 얇은 층이라
// 게임 로직이 서버에 전혀 없다 — 밸런스를 고쳐도 서버는 재배포할 필요가 없다.
//
// 대역폭: 몹 100+를 15Hz로 보내야 하므로 좌표는 전부 정수 양자화(×10, 즉 10cm 단위)하고
// 키를 1글자로 줄인다. JSON 그대로 두면 4인전 후반에 호스트 업로드가 수 Mbps로 뛴다.

export const PROTOCOL_VERSION = 1;

export const MAX_PLAYERS = 4;
export const SNAPSHOT_HZ = 15;   // 15Hz + 클라 보간 — 60Hz 송신은 대역폭만 먹고 체감 차이가 없다
export const INPUT_HZ = 30;      // 입력은 더 자주 (반응성이 곧 손맛)
export const MAX_SNAPSHOT_MOBS = 220;

/** 클라 → 서버 */
export const C2S = ['create', 'join', 'lobby', 'start', 'input', 'snapshot', 'pick', 'interact', 'event', 'chat'];
/** 방장만 보낼 수 있는 것 — 게스트가 보내면 거부 (권위 위조 방지) */
export const HOST_ONLY = ['start', 'snapshot', 'event'];

// ---------- 양자화 ----------
const Q = 10;
export const q = (v) => Math.round(v * Q);
export const dq = (v) => v / Q;
const QA = 1000; // 각도는 밀리라디안
export const qa = (v) => Math.round(v * QA);
export const dqa = (v) => v / QA;

// ---------- 입력 ----------
// 키는 비트마스크 — 매 33ms마다 문자열 배열을 올리면 그것만으로도 수십 KB/s가 된다
export const KEYBIT = { KeyW: 1, KeyA: 2, KeyS: 4, KeyD: 8, ShiftLeft: 16, ShiftRight: 32 };
const KEYBIT_ENTRIES = Object.entries(KEYBIT);

export function packKeys(keySet) {
  let m = 0;
  for (const [code, bit] of KEYBIT_ENTRIES) if (keySet.has(code)) m |= bit;
  return m;
}
export function unpackKeys(mask, into = new Set()) {
  into.clear();
  for (const [code, bit] of KEYBIT_ENTRIES) if (mask & bit) into.add(code);
  return into;
}

/**
 * 게스트가 올리는 입력 한 프레임.
 * k=키마스크, y=카메라 yaw(그 사람 화면 기준 — 호스트 카메라로 풀면 남의 캐릭터가 엉뚱하게 걷는다),
 * a=조준 방향, p=조준 지점, atk/rol=이번 틱의 단발 입력, cs=시전 슬롯(-1=없음)
 */
export function encodeInput({ keys, yaw, aim, aimPt, attack, roll, castSlot }) {
  return {
    k: packKeys(keys),
    y: qa(yaw),
    a: aim ? [q(aim.x), q(aim.z)] : null,
    p: aimPt ? [q(aimPt.x), q(aimPt.z)] : null,
    atk: attack ? 1 : 0,
    rol: roll ? 1 : 0,
    cs: castSlot ?? -1,
  };
}

// ---------- 스냅샷 ----------
// pl: 플레이어, mb: 몹, gm: 젬, pr: 투사체, zn: 예고 장판
// 젬/투사체/장판까지 보내는 이유: 게스트에게 "주울 것"과 "피할 것"이 안 보이면 게임이 성립하지 않는다.
export function encodeSnapshot(ctx) {
  const players = ctx.players.map((p) => {
    const o = p.object3d.position;
    return [p.index, q(o.x), q(o.y), q(o.z), qa(p.facing), Math.round(p.hp), Math.round(p.stats.maxHp), STATE_ID[p.state] ?? 0];
  });

  const mobs = [];
  for (const m of ctx.mobs) {
    if (mobs.length >= MAX_SNAPSHOT_MOBS) break;
    if (!m.alive) continue;
    const o = m.object3d.position;
    mobs.push([
      m.netId, m.kind, q(o.x), q(o.y), q(o.z), qa(m.object3d.rotation.y),
      Math.round(m.hp), Math.round(m.maxHp),
      (m.elite ? 1 : 0) | (m.isBoss ? 2 : 0),
    ]);
  }

  const gems = [];
  for (const g of ctx.gems.items) {
    if (!g.active) continue;
    const o = g.mesh.position;
    gems.push([q(o.x), q(o.y), q(o.z), g.kind === 'heart' ? 1 : 0, Math.round(g.mesh.scale.x * 100)]);
  }

  const projs = [];
  for (const pr of ctx.projectiles.items) {
    if (!pr.active) continue;
    projs.push([q(pr.pos.x), q(pr.pos.y), q(pr.pos.z), qa(Math.atan2(pr.vel.x, pr.vel.z)), pr.source === 'mob' ? 1 : 0, SHAPE_ID[pr.shape] ?? 0, Math.round(pr.size * 100), pr.mat.color.getHex()]);
  }

  return {
    t: Math.round(ctx.time * 10),
    kl: ctx.kills,
    st: ctx.state,
    xp: Math.round(ctx.party.xp),
    lv: ctx.party.level,
    pl: players,
    mb: mobs,
    gm: gems,
    pr: projs,
    bs: ctx.boss?.alive ? [Math.round(ctx.boss.hp), Math.round(ctx.boss.maxHp)] : null,
  };
}

export const STATE_ID = { idle: 0, run: 1, attack: 2, roll: 3, hit: 4, dead: 5 };
export const ID_STATE = Object.fromEntries(Object.entries(STATE_ID).map(([k, v]) => [v, k]));
export const SHAPE_ID = { orb: 0, blade: 1, spike: 2, arrow: 3, crescent: 4 };
export const ID_SHAPE = Object.fromEntries(Object.entries(SHAPE_ID).map(([k, v]) => [v, k]));

// ---------- 서버측 검증 ----------
// 서버는 게임 규칙을 모른다. 그래도 "형태가 말이 되는가"는 봐야 한다 —
// 악의적 패킷 하나가 다른 3명의 클라이언트를 크래시시키는 걸 막는 최소한의 방벽.
const finite = (v) => Number.isFinite(Number(v));

export function validInput(s) {
  if (!s || typeof s !== 'object') return false;
  if (!Number.isInteger(s.k) || s.k < 0 || s.k > 63) return false;
  if (!finite(s.y)) return false;
  if (s.a !== null && !(Array.isArray(s.a) && s.a.length === 2 && s.a.every(finite))) return false;
  if (s.p !== null && !(Array.isArray(s.p) && s.p.length === 2 && s.p.every(finite))) return false;
  if (!Number.isInteger(s.cs) || s.cs < -1 || s.cs > 3) return false;
  return true;
}

export function validSnapshot(s) {
  if (!s || typeof s !== 'object') return false;
  if (!Array.isArray(s.pl) || s.pl.length > MAX_PLAYERS) return false;
  if (!Array.isArray(s.mb) || s.mb.length > MAX_SNAPSHOT_MOBS) return false;
  if (!Array.isArray(s.gm) || !Array.isArray(s.pr)) return false;
  return true;
}
