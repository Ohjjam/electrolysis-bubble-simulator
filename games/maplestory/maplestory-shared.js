/* =========================================================
   메이플 클론 스토리 — 공용 모듈 (클라이언트 + 서버)
   맵 데이터 / 몬스터 정의 / 시뮬레이션(Sim) / 게임호스트(GameHost)
   순수 로직만 포함 (브라우저 API 사용 금지)
   ========================================================= */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.SHARED = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ---------- 물리/게임 상수 ----------
  const CONST = {
    GRAV: 2200,    // 중력 px/s^2
    MOVE: 262,     // 이동속도 px/s
    JUMP: 780,     // 점프 초기속도
    CLIMB: 165,    // 사다리 속도
    MAXLV: 80,
  };

  const JOB_NAMES = {
    beginner: "초보자", warrior: "전사", magician: "마법사", bowman: "궁수", thief: "도적",
  };

  // ---------- 몬스터 정의 (올드 메이플 수치 기반) ----------
  const MOB_TYPES = {
    snail:        { name: "달팽이",      hp: 8,     exp: 3,    touch: 5,   speed: 22, w: 40,  h: 30,  meso: [1, 10],     lvl: 1 },
    blueSnail:    { name: "파란 달팽이",  hp: 15,    exp: 4,    touch: 9,   speed: 30, w: 42,  h: 32,  meso: [2, 14],     lvl: 2 },
    redSnail:     { name: "빨간 달팽이",  hp: 40,    exp: 8,    touch: 14,  speed: 36, w: 44,  h: 34,  meso: [5, 22],     lvl: 4 },
    slime:        { name: "슬라임",      hp: 50,    exp: 10,   touch: 14,  speed: 40, w: 44,  h: 34,  meso: [8, 28],     lvl: 6, hop: true },
    pig:          { name: "돼지",        hp: 75,    exp: 15,   touch: 21,  speed: 60, w: 52,  h: 38,  meso: [10, 32],    lvl: 7 },
    shroom:       { name: "주황버섯",    hp: 80,    exp: 15,   touch: 26,  speed: 48, w: 46,  h: 48,  meso: [12, 36],    lvl: 8, hop: true },
    ribbonPig:    { name: "리본돼지",    hp: 100,   exp: 19,   touch: 26,  speed: 66, w: 52,  h: 40,  meso: [14, 40],    lvl: 10 },
    octopus:      { name: "옥토퍼스",    hp: 120,   exp: 22,   touch: 28,  speed: 34, w: 46,  h: 42,  meso: [16, 48],    lvl: 12 },
    stump:        { name: "스텀프",      hp: 110,   exp: 20,   touch: 26,  speed: 26, w: 52,  h: 48,  meso: [16, 46],    lvl: 12 },
    greenShroom:  { name: "초록버섯",    hp: 150,   exp: 26,   touch: 23,  speed: 46, w: 44,  h: 46,  meso: [20, 60],    lvl: 15, hop: true },
    bubbling:     { name: "버블링",      hp: 180,   exp: 30,   touch: 36,  speed: 42, w: 44,  h: 36,  meso: [20, 62],    lvl: 15, hop: true },
    darkStump:    { name: "다크 스텀프", hp: 200,   exp: 32,   touch: 34,  speed: 28, w: 52,  h: 48,  meso: [22, 66],    lvl: 16 },
    boar:         { name: "멧돼지",      hp: 250,   exp: 40,   touch: 45,  speed: 84, w: 58,  h: 42,  meso: [26, 75],    lvl: 18, aggro: true },
    evilEye:      { name: "이블아이",    hp: 270,   exp: 43,   touch: 43,  speed: 50, w: 54,  h: 36,  meso: [28, 78],    lvl: 19, aggro: true },
    stirge:       { name: "스티지",      hp: 300,   exp: 45,   touch: 42,  speed: 74, w: 46,  h: 48,  meso: [30, 80],    lvl: 20 },
    jrNecki:      { name: "주니어 네키", hp: 320,   exp: 47,   touch: 44,  speed: 58, w: 50,  h: 42,  meso: [30, 84],    lvl: 21, aggro: true },
    hornyShroom:  { name: "뿔버섯",      hp: 300,   exp: 42,   touch: 45,  speed: 52, w: 50,  h: 52,  meso: [30, 80],    lvl: 22, aggro: true },
    axeStump:     { name: "액스 스텀프", hp: 380,   exp: 52,   touch: 48,  speed: 30, w: 54,  h: 50,  meso: [34, 92],    lvl: 22 },
    zombieShroom: { name: "좀비버섯",    hp: 400,   exp: 55,   touch: 48,  speed: 44, w: 48,  h: 50,  meso: [36, 95],    lvl: 24, aggro: true },
    ligator:      { name: "리게이터",    hp: 420,   exp: 58,   touch: 50,  speed: 62, w: 64,  h: 36,  meso: [36, 98],    lvl: 24, aggro: true },
    curseEye:     { name: "커즈아이",    hp: 470,   exp: 62,   touch: 52,  speed: 54, w: 54,  h: 38,  meso: [38, 105],   lvl: 25, aggro: true },
    ironHog:      { name: "아이언 호그", hp: 550,   exp: 70,   touch: 60,  speed: 78, w: 56,  h: 42,  meso: [42, 115],   lvl: 26, aggro: true },
    fireBoar:     { name: "파이어보어",  hp: 600,   exp: 75,   touch: 62,  speed: 88, w: 58,  h: 44,  meso: [45, 120],   lvl: 28, aggro: true },
    coldEye:      { name: "콜드아이",    hp: 650,   exp: 78,   touch: 58,  speed: 50, w: 54,  h: 36,  meso: [46, 125],   lvl: 28 },
    croco:        { name: "크로코",      hp: 800,   exp: 95,   touch: 65,  speed: 70, w: 70,  h: 40,  meso: [52, 140],   lvl: 30, aggro: true },
    drake:        { name: "드레이크",    hp: 2600,  exp: 220,  touch: 75,  speed: 60, w: 62,  h: 56,  meso: [70, 180],   lvl: 36, aggro: true },
    tauromacis:   { name: "타우로마시스", hp: 6500, exp: 560,  touch: 95,  speed: 64, w: 64,  h: 70,  meso: [110, 280],  lvl: 38, aggro: true },
    kingSlime:    { name: "킹슬라임",    hp: 2600,  exp: 380,  touch: 50,  speed: 40, w: 110, h: 78,  meso: [200, 600],  lvl: 23, aggro: true, boss: true, respawnMs: 60000, hop: true, pattern: { kind: "press", every: 12 } },
    mushmom:      { name: "머쉬맘",      hp: 12000, exp: 1500, touch: 90,  speed: 55, w: 150, h: 130, meso: [400, 1200], lvl: 38, aggro: true, boss: true, respawnMs: 90000, pattern: { kind: "spore", every: 13 } },
    jrBalrog:     { name: "주니어 발록", hp: 45000, exp: 4200, touch: 120, speed: 70, w: 130, h: 110, meso: [1000, 3000], lvl: 50, aggro: true, boss: true, respawnMs: 180000, pattern: { kind: "breath", every: 12 } },
    zakumArm:     { name: "자쿰의 팔",   hp: 9000,  exp: 1000, touch: 70,  speed: 0,  w: 60,  h: 95,  meso: [200, 500],  lvl: 50, respawnMs: 300000 },
    zakumBody:    { name: "자쿰",        hp: 60000, exp: 9000, touch: 100, speed: 0,  w: 150, h: 175, meso: [2500, 6000], lvl: 60, boss: true, respawnMs: 300000, enrage: { type: "hornyShroom", n: 2 } },
    cloudBoss:    { name: "구름 거인 니브스", hp: 35000, exp: 5200, touch: 85, speed: 40, w: 130, h: 145, meso: [1500, 4000], lvl: 45, aggro: true, boss: true, respawnMs: 240000, enrage: { type: "windSpirit", n: 2 }, pattern: { kind: "gust", every: 13 } },
    clockBoss:    { name: "태엽 마왕 틱톡", hp: 50000, exp: 7500, touch: 105, speed: 55, w: 140, h: 155, meso: [2000, 5000], lvl: 55, aggro: true, boss: true, respawnMs: 240000, enrage: { type: "gearBot", n: 2 }, pattern: { kind: "tick", every: 14 } },
    // ----- 오르비스 지역 몬스터 -----
    puffBird:     { name: "솜뭉치새 푸푸", hp: 700,  exp: 85,   touch: 56,  speed: 46, w: 48,  h: 44,  meso: [46, 128],   lvl: 29, hop: true },
    windSpirit:   { name: "바람 정령",    hp: 950,   exp: 110,  touch: 62,  speed: 58, w: 46,  h: 50,  meso: [52, 140],   lvl: 32, aggro: true },
    iceSheep:     { name: "눈송이 양",    hp: 1300,  exp: 145,  touch: 68,  speed: 50, w: 56,  h: 46,  meso: [60, 158],   lvl: 35 },
    // ----- 루디브리엄 지역 몬스터 -----
    gearBot:      { name: "태엽 병정",    hp: 2900,  exp: 250,  touch: 78,  speed: 55, w: 50,  h: 58,  meso: [72, 185],   lvl: 38, aggro: true },
    blockGolem:   { name: "블록 골렘",    hp: 4400,  exp: 370,  touch: 88,  speed: 40, w: 64,  h: 66,  meso: [95, 240],   lvl: 42 },
    clownDoll:    { name: "삐에로 인형",  hp: 6200,  exp: 520,  touch: 96,  speed: 68, w: 52,  h: 62,  meso: [115, 300],  lvl: 46, aggro: true },
    // ----- 콜라보 맵 (닌텐도 월드) 보스 -----
    kirbyBoss:    { name: "커비",   hp: 42000, exp: 6000, touch: 90, speed: 60, w: 110, h: 100, meso: [1800, 4500], lvl: 52, aggro: true, boss: true, respawnMs: 240000, hop: true, pattern: { kind: "pull", every: 13 } },
    pikaBoss:     { name: "피카츄", hp: 38000, exp: 5600, touch: 88, speed: 75, w: 100, h: 95,  meso: [1600, 4200], lvl: 50, aggro: true, boss: true, respawnMs: 240000, pattern: { kind: "bolt", every: 11 } },
    marioBoss:    { name: "마리오", hp: 46000, exp: 6600, touch: 95, speed: 65, w: 95,  h: 105, meso: [2000, 5000], lvl: 54, aggro: true, boss: true, respawnMs: 240000, enrage: { type: "shroom", n: 3 }, pattern: { kind: "press", every: 14 } },
  };

  // ---------- 스탯 공식 (올드 메이플 기반) ----------
  // 클래식 경험치 테이블 (lv → lv+1 필요 경험치)
  const EXP_TABLE = [15, 34, 57, 92, 135, 372, 560, 840, 1242, 1716,
    2360, 3216, 4200, 5460, 6900, 8620, 10620, 12940, 15600, 18600,
    21960, 25710, 29860, 34430, 39430, 44880, 50800, 57190, 64080];
  // Lv.30 이후 ~80까지 연장 (레벨당 +8%)
  while (EXP_TABLE.length < 79) {
    EXP_TABLE.push(Math.round(EXP_TABLE[EXP_TABLE.length - 1] * 1.08 / 10) * 10);
  }
  function expNeed(lv) {
    return EXP_TABLE[Math.min(Math.max(lv - 1, 0), EXP_TABLE.length - 1)];
  }
  // 1차 전직 가능 레벨 (전 직업 10 — SP 수지를 정확히 맞추기 위해 통일)
  const JOB_REQ = { warrior: 10, magician: 10, bowman: 10, thief: 10 };
  // HP/MP: 공통 성장 → 전직 후 직업별 성장 + 전직 보너스
  function maxHp(lv, job) {
    if (job === "beginner" || !JOB_REQ[job]) return 50 + 12 * (lv - 1);
    const adv = JOB_REQ[job];
    const pre = Math.min(lv, adv);
    const post = Math.max(0, lv - adv);
    const rate = { warrior: 26, magician: 12, bowman: 20, thief: 20 }[job];
    const bonus = { warrior: 200, magician: 50, bowman: 100, thief: 100 }[job];
    return 50 + 12 * (pre - 1) + rate * post + bonus;
  }
  function maxMp(lv, job) {
    if (job === "beginner" || !JOB_REQ[job]) return 5 + 8 * (lv - 1);
    const adv = JOB_REQ[job];
    const pre = Math.min(lv, adv);
    const post = Math.max(0, lv - adv);
    const rate = { warrior: 5, magician: 24, bowman: 12, thief: 12 }[job];
    const bonus = { warrior: 20, magician: 150, bowman: 50, thief: 50 }[job];
    return 5 + 8 * (pre - 1) + rate * post + bonus;
  }
  // 데미지: 실제 스탯 × 무기공격력 (st: {str,dex,int,luk}, watk: 맨손 10 + 무기, mastery: 패시브 숙련 레벨)
  function dmgRange(lv, job, st, watk, mastery) {
    st = st || { str: 12 + 5 * (lv - 1), dex: 5, int: 4, luk: 4 };
    if (watk == null) watk = 15 + lv * 1.1;
    let max;
    if (job === "bowman") max = (3.4 * st.dex + st.str) * watk / 100;
    else if (job === "thief") max = (3.6 * st.luk + st.dex) * watk / 100;
    else if (job === "magician") max = (3.3 * st.int + st.luk) * watk / 100;
    else max = (4.0 * st.str + st.dex) * watk / 100; // 전사/초보자
    let minR = { warrior: 0.62, bowman: 0.66, thief: 0.55, magician: 0.72 }[job] || 0.6;
    minR = Math.min(0.92, minR + 0.012 * (mastery || 0)); // 마스터리: 최소 데미지 상승
    return { min: Math.max(1, max * minR), max: Math.max(2, max) };
  }

  // ---------- 장비 (요구 스탯 / 보너스 / 방어력) ----------
  const EQUIP = {
    // 무기
    w_dagger1: { slot: "weapon", name: "낡은 단검",   lv: 1,  watk: 9,  price: 500 },
    tw_sword:  { slot: "weapon", name: "견습 전사의 검",     lv: 10, watk: 20, price: 1500 },
    tw_bow:    { slot: "weapon", name: "견습 궁수의 활",     lv: 10, watk: 18, price: 1500 },
    tw_wand:   { slot: "weapon", name: "견습 마법사의 완드", lv: 8,  watk: 16, price: 1500 },
    tw_claw:   { slot: "weapon", name: "견습 도적의 아대",   lv: 10, watk: 17, price: 1500 },
    w_sword1:  { slot: "weapon", name: "글라디우스",  lv: 10, watk: 23, req: { str: 35 },  price: 4000 },
    w_axe1:    { slot: "weapon", name: "전투 도끼",   lv: 20, watk: 34, req: { str: 70 },  price: 25000 },
    w_sword2:  { slot: "weapon", name: "용사의 대검", lv: 30, watk: 46, req: { str: 110 }, price: 90000 },
    w_bow1:    { slot: "weapon", name: "수련용 활",   lv: 10, watk: 20, req: { dex: 35 },  price: 4000 },
    w_bow2:    { slot: "weapon", name: "전투 활",     lv: 20, watk: 31, req: { dex: 70 },  price: 25000 },
    w_wand1:   { slot: "weapon", name: "수련 완드",   lv: 8,  watk: 18, req: { int: 30 },  price: 3500 },
    w_staff1:  { slot: "weapon", name: "마법 지팡이", lv: 20, watk: 29, req: { int: 65 },  price: 24000 },
    w_claw1:   { slot: "weapon", name: "수련용 아대", lv: 10, watk: 19, req: { luk: 35 },  price: 4000 },
    w_claw2:   { slot: "weapon", name: "강철 아대",   lv: 20, watk: 30, req: { luk: 70 },  price: 25000 },
    // 방어구
    h_leather: { slot: "hat",    name: "가죽 모자",   lv: 5,  def: 3,  price: 800 },
    h_iron:    { slot: "hat",    name: "철 투구",     lv: 15, def: 8,  req: { str: 40 }, price: 9000 },
    h_wizard:  { slot: "hat",    name: "견습 마법모", lv: 15, def: 5,  bonus: { int: 1 }, price: 9000 },
    t_shirt:   { slot: "top",    name: "천 셔츠",     lv: 5,  def: 4,  price: 1000 },
    t_chain:   { slot: "top",    name: "사슬 갑옷",   lv: 18, def: 12, req: { str: 50 }, price: 14000 },
    t_robe:    { slot: "top",    name: "마법 로브",   lv: 18, def: 8,  bonus: { int: 2 }, price: 14000 },
    b_pants:   { slot: "bottom", name: "무명 바지",   lv: 5,  def: 3,  price: 900 },
    b_plate:   { slot: "bottom", name: "판금 각반",   lv: 18, def: 10, req: { str: 50 }, price: 13000 },
    s_straw:   { slot: "shoes",  name: "짚신",        lv: 5,  def: 2,  price: 600 },
    s_boots:   { slot: "shoes",  name: "가죽 부츠",   lv: 15, def: 6,  bonus: { dex: 1 }, price: 8000 },
    // 상위 무기 (Lv.38 / 48 / 58)
    w_sword3:  { slot: "weapon", name: "기사단 장검",   lv: 38, watk: 58, req: { str: 130 }, price: 160000 },
    w_sword4:  { slot: "weapon", name: "용맹의 대검",   lv: 48, watk: 70, req: { str: 170 }, price: 380000 },
    w_sword5:  { slot: "weapon", name: "영웅의 참격검", lv: 58, watk: 83, req: { str: 210 }, price: 800000 },
    w_bow3:    { slot: "weapon", name: "전쟁 활",       lv: 38, watk: 54, req: { dex: 130 }, price: 160000 },
    w_bow4:    { slot: "weapon", name: "폭풍 활",       lv: 48, watk: 66, req: { dex: 170 }, price: 380000 },
    w_bow5:    { slot: "weapon", name: "신궁의 활",     lv: 58, watk: 78, req: { dex: 210 }, price: 800000 },
    w_wand3:   { slot: "weapon", name: "현자의 지팡이", lv: 38, watk: 52, req: { int: 130 }, price: 160000 },
    w_wand4:   { slot: "weapon", name: "대현자의 지팡이", lv: 48, watk: 63, req: { int: 170 }, price: 380000 },
    w_wand5:   { slot: "weapon", name: "룬 스태프",     lv: 58, watk: 75, req: { int: 210 }, price: 800000 },
    w_claw3:   { slot: "weapon", name: "맹독 아대",     lv: 38, watk: 53, req: { luk: 130 }, price: 160000 },
    w_claw4:   { slot: "weapon", name: "그림자 아대",   lv: 48, watk: 65, req: { luk: 170 }, price: 380000 },
    w_claw5:   { slot: "weapon", name: "야차 아대",     lv: 58, watk: 77, req: { luk: 210 }, price: 800000 },
    // 상위 방어구 (Lv.30 / 45 / 60)
    h_steel:   { slot: "hat",    name: "강철 투구",     lv: 30, def: 14, price: 45000 },
    h_mythril: { slot: "hat",    name: "미스릴 투구",   lv: 45, def: 20, bonus: { str: 1 }, price: 150000 },
    h_dragon:  { slot: "hat",    name: "용비늘 투구",   lv: 60, def: 28, bonus: { str: 2 }, price: 450000 },
    t_steel:   { slot: "top",    name: "강철 갑옷",     lv: 30, def: 18, price: 55000 },
    t_mythril: { slot: "top",    name: "미스릴 갑옷",   lv: 45, def: 26, bonus: { hp: 30 }, price: 180000 },
    t_dragon:  { slot: "top",    name: "용비늘 갑옷",   lv: 60, def: 36, bonus: { hp: 60 }, price: 520000 },
    b_steel:   { slot: "bottom", name: "강철 각반",     lv: 30, def: 15, price: 50000 },
    b_mythril: { slot: "bottom", name: "미스릴 각반",   lv: 45, def: 22, price: 160000 },
    b_dragon:  { slot: "bottom", name: "용비늘 각반",   lv: 60, def: 30, bonus: { hp: 40 }, price: 480000 },
    s_wind:    { slot: "shoes",  name: "바람 부츠",     lv: 30, def: 8,  bonus: { jump: 4 }, price: 40000 },
    s_storm:   { slot: "shoes",  name: "폭풍 부츠",     lv: 45, def: 12, bonus: { jump: 6, dex: 1 }, price: 140000 },
    s_gale:    { slot: "shoes",  name: "질풍 부츠",     lv: 60, def: 16, bonus: { jump: 8, dex: 2 }, price: 420000 },
    // 보스 전용 장비 (드랍 한정)
    bz_helm:   { slot: "hat",    name: "자쿰의 화염 투구", lv: 50, def: 32, bonus: { str: 2, dex: 2, int: 2, luk: 2, hp: 60 }, price: 500000, boss: "zakumBody" },
    bz_sword:  { slot: "weapon", name: "자쿰의 용암검",   lv: 50, watk: 78, req: { str: 180 }, price: 500000, boss: "zakumBody" },
    bb_sword:  { slot: "weapon", name: "발록의 어둠 대검", lv: 45, watk: 72, req: { str: 160 }, price: 400000, boss: "jrBalrog" },
    bb_chest:  { slot: "top",    name: "발록의 흉갑",     lv: 45, def: 30, bonus: { str: 3 }, price: 350000, boss: "jrBalrog" },
    bm_hat:    { slot: "hat",    name: "머쉬맘의 포자 모자", lv: 30, def: 16, bonus: { hp: 80 }, price: 120000, boss: "mushmom" },
    bk_crown:  { slot: "hat",    name: "왕슬라임의 왕관", lv: 20, def: 10, bonus: { luk: 2, dex: 2 }, price: 80000, boss: "kingSlime" },
    bc_robe:   { slot: "top",    name: "니브스의 구름 로브", lv: 42, def: 24, bonus: { int: 4 }, price: 300000, boss: "cloudBoss" },
    bc_shoes:  { slot: "shoes",  name: "니브스의 바람 신발", lv: 42, def: 10, bonus: { jump: 8, dex: 2 }, price: 300000, boss: "cloudBoss" },
    bt_bow:    { slot: "weapon", name: "틱톡의 태엽 활",  lv: 55, watk: 80, req: { dex: 190 }, price: 600000, boss: "clockBoss" },
    bt_armor:  { slot: "top",    name: "틱톡의 태엽 갑주", lv: 55, def: 36, bonus: { str: 2, dex: 2 }, price: 550000, boss: "clockBoss" },
  };
  const EQUIP_SLOTS = ["weapon", "hat", "top", "bottom", "shoes"];

  // ---------- 기타 아이템 (몬스터별 고유 드랍 / 판매가) ----------
  const ETC = {
    e_snailshell: { name: "달팽이 껍질",      sell: 3 },
    e_blueshell:  { name: "파란 달팽이 껍질",  sell: 6 },
    e_redshell:   { name: "빨간 달팽이 껍질",  sell: 14 },
    e_slimegel:   { name: "슬라임의 젤리",     sell: 12 },
    e_pighide:    { name: "돼지 가죽",        sell: 16 },
    e_mushcap:    { name: "주황버섯 갓",       sell: 18 },
    e_ribbon:     { name: "분홍 리본",        sell: 26 },
    e_octoleg:    { name: "옥토퍼스 다리",     sell: 30 },
    e_wood:       { name: "나뭇조각",         sell: 26 },
    e_greencap:   { name: "초록버섯 갓",       sell: 32 },
    e_bubble:     { name: "탱탱한 물방울",     sell: 36 },
    e_darkwood:   { name: "단단한 나뭇조각",   sell: 40 },
    e_boartusk:   { name: "멧돼지 엄니",       sell: 52 },
    e_eyetail:    { name: "이블아이 꼬리",     sell: 55 },
    e_wing:       { name: "스티지 날개",       sell: 54 },
    e_snakeskin:  { name: "네키 가죽",        sell: 58 },
    e_horn:       { name: "뾰족한 뿔",        sell: 56 },
    e_oldaxe:     { name: "낡은 도끼날",       sell: 62 },
    e_spore:      { name: "좀비 포자",        sell: 66 },
    e_gatorskin:  { name: "리게이터 가죽",     sell: 70 },
    e_cursegem:   { name: "저주의 보석",       sell: 78 },
    e_ironpiece:  { name: "강철 조각",        sell: 85 },
    e_firetusk:   { name: "불꽃 엄니",        sell: 92 },
    e_iceshard:   { name: "얼음 조각",        sell: 90 },
    e_crocskin:   { name: "크로코 가죽",       sell: 110 },
    e_drakescale: { name: "드레이크 비늘",     sell: 180 },
    e_taurohorn:  { name: "타우로의 뿔",       sell: 350 },
    e_crowngel:   { name: "왕의 젤리",        sell: 500 },
    e_giantspore: { name: "거대 버섯 포자",    sell: 800 },
    e_darkhorn:   { name: "암흑의 뿔",        sell: 2000 },
    e_zakrock:    { name: "불타는 암석",       sell: 1500 },
    e_cloudcore:  { name: "구름의 핵",         sell: 1800 },
    e_gear:       { name: "마력 태엽",         sell: 2200 },
    e_scr10:      { name: "공격 주문서 10%",   sell: 500,  use: 1 },
    e_scr60:      { name: "공격 주문서 60%",   sell: 200,  use: 1 },
    e_scr100:     { name: "공격 주문서 100%",  sell: 100,  use: 1 },
    e_shp10:      { name: "HP 주문서 10%",     sell: 550,  use: 1 },
    e_shp60:      { name: "HP 주문서 60%",     sell: 220,  use: 1 },
    e_sstr10:     { name: "힘 주문서 10%",     sell: 600,  use: 1 },
    e_sstr60:     { name: "힘 주문서 60%",     sell: 240,  use: 1 },
    e_sdex10:     { name: "민첩 주문서 10%",   sell: 600,  use: 1 },
    e_sdex60:     { name: "민첩 주문서 60%",   sell: 240,  use: 1 },
    e_sint10:     { name: "지력 주문서 10%",   sell: 600,  use: 1 },
    e_sint60:     { name: "지력 주문서 60%",   sell: 240,  use: 1 },
    e_sluk10:     { name: "운 주문서 10%",     sell: 600,  use: 1 },
    e_sluk60:     { name: "운 주문서 60%",     sell: 240,  use: 1 },
    e_sjmp10:     { name: "점프 주문서 10%",   sell: 700,  use: 1 },
    e_sjmp60:     { name: "점프 주문서 60%",   sell: 280,  use: 1 },
    e_cube:       { name: "미라클 큐브 [레어]",     sell: 800,  use: 1 },
    e_cube2:      { name: "상급 미라클 큐브 [에픽]", sell: 2500, use: 1 },
    e_cube3:      { name: "최상급 미라클 큐브 [유니크]", sell: 8000, use: 1 },
  };
  // 마을 귀환 주문서 (모든 마을 상점 판매)
  const RET_TOWNS = { lith: "리스항구", henesys: "헤네시스", ellinia: "엘리니아", perion: "페리온", kerning: "커닝시티", sleepywood: "슬리피우드", orbis: "오르비스", ludi: "루디브리엄" };
  for (const tid in RET_TOWNS) ETC["e_ret_" + tid] = { name: RET_TOWNS[tid] + " 귀환 주문서", sell: 50, use: 1, ret: tid };
  // 강화 주문서 정의 (rate: 성공률 / main: 무기=공격력·방어구=방어 / 그 외: 해당 능력치)
  const SCROLLS = {
    e_scr10: { rate: 0.1, main: 5 }, e_scr60: { rate: 0.6, main: 2 }, e_scr100: { rate: 1, main: 1 },
    e_shp10: { rate: 0.1, hp: 40 }, e_shp60: { rate: 0.6, hp: 15 },
    e_sstr10: { rate: 0.1, str: 3 }, e_sstr60: { rate: 0.6, str: 1 },
    e_sdex10: { rate: 0.1, dex: 3 }, e_sdex60: { rate: 0.6, dex: 1 },
    e_sint10: { rate: 0.1, int: 3 }, e_sint60: { rate: 0.6, int: 1 },
    e_sluk10: { rate: 0.1, luk: 3 }, e_sluk60: { rate: 0.6, luk: 1 },
    e_sjmp10: { rate: 0.1, jump: 5 }, e_sjmp60: { rate: 0.6, jump: 2 },
  };
  const SCROLL_IDS = Object.keys(SCROLLS);
  const MOB_ETC = {
    snail: "e_snailshell", blueSnail: "e_blueshell", redSnail: "e_redshell",
    slime: "e_slimegel", pig: "e_pighide", shroom: "e_mushcap", ribbonPig: "e_ribbon",
    octopus: "e_octoleg", stump: "e_wood", greenShroom: "e_greencap", bubbling: "e_bubble",
    darkStump: "e_darkwood", boar: "e_boartusk", evilEye: "e_eyetail", stirge: "e_wing",
    jrNecki: "e_snakeskin", hornyShroom: "e_horn", axeStump: "e_oldaxe", zombieShroom: "e_spore",
    ligator: "e_gatorskin", curseEye: "e_cursegem", ironHog: "e_ironpiece", fireBoar: "e_firetusk",
    coldEye: "e_iceshard", croco: "e_crocskin", drake: "e_drakescale", tauromacis: "e_taurohorn",
    kingSlime: "e_crowngel", mushmom: "e_giantspore", jrBalrog: "e_darkhorn",
    zakumArm: "e_zakrock", zakumBody: "e_zakrock",
    cloudBoss: "e_cloudcore", clockBoss: "e_gear",
  };

  // ---------- 수집 퀘스트 (마을 NPC / 1회성) ----------
  const QUESTS = {
    q_shell: { npc: "안내원 리나", name: "반짝이는 껍질", lv: 2, need: { e_snailshell: 10 }, reward: { exp: 60, meso: 300 },
      offer: "공예 재료로 달팽이 껍질이 필요해요. 동쪽 달팽이 동산에서 10개만 모아다 주실래요?",
      done: "우와, 반짝반짝하네요! 약속한 보상이에요. 고마워요!" },
    q_gel: { npc: "주민 콩이", name: "말랑말랑 젤리", lv: 6, need: { e_slimegel: 15 }, reward: { exp: 500, meso: 1200, potR: 10 },
      offer: "슬라임의 젤리 15개만 구해줘! 세상에서 제일 탱탱한 공을 만들 거야!",
      done: "최고야!! 이건 내 보답이야. 포션은 서비스!" },
    q_cap: { npc: "요정 릴리", name: "묘약의 재료", lv: 12, need: { e_greencap: 12, e_mushcap: 10 }, reward: { exp: 2500, meso: 3000 },
      offer: "묘약을 만들려면 초록버섯 갓 12개와 주황버섯 갓 10개가 필요해요. 부탁할게요!",
      done: "완벽한 재료네요! 묘약이 잘 만들어질 거예요. 고마워요!" },
    q_tusk: { npc: "주민 단단", name: "용맹의 증표", lv: 18, need: { e_boartusk: 10 }, reward: { exp: 6000, meso: 6000 },
      offer: "전사라면 힘을 증명해라! 멧돼지 엄니 10개를 가져와 봐라.",
      done: "훌륭한 사냥꾼이군! 이 보상을 받을 자격이 있다." },
    q_gator: { npc: "주민 삐에로", name: "최고급 가죽 가방", lv: 22, need: { e_gatorskin: 8 }, reward: { exp: 12000, meso: 10000 },
      offer: "리게이터 가죽 8장이 필요해. 하수도나 늪지대에 가면 잡을 수 있을 거야~",
      done: "이야~ 질 좋은 가죽이야! 가방이 완성되면 제일 먼저 보여줄게!" },
    q_scale: { npc: "은둔자 노아", name: "용비늘 연구", lv: 30, need: { e_drakescale: 5 }, reward: { exp: 40000, meso: 30000 },
      offer: "...드레이크의 비늘 5장이 필요하네. 개미굴 너머 동굴에 사는 녀석들이지.",
      done: "...훌륭하군. 자네 덕에 연구가 큰 진전을 보겠어. 받게나." },
  };
  // 접촉 데미지: 몬스터 고유 공격력 (±15% 랜덤)
  function touchDmg(info, lv) {
    return Math.max(1, Math.round(info.touch * (0.85 + Math.random() * 0.15)));
  }
  function rnd(a, b) { return a + Math.floor(Math.random() * (b - a + 1)); }

  // ---------- 맵 데이터 ----------
  // plats: {x1,y,x2,noDrop}  ladders: {x,y1,y2}  portals: {type:"side"|"door",x,y,to,tx,ty}
  // npcs: {kind:"shop"|"job"|"talk", job?, name, x, y, lines[]}  spawns: {type,x,y}
  function fh(x, y, w, noDrop) { return { x1: x, y: y, x2: x + w, noDrop: !!noDrop }; }
  function ld(x, y1, y2) { return { x: x, y1: y1, y2: y2 }; }

  const MAPS = {};
  function addMap(d) { MAPS[d.id] = d; }

  // ----- 리스 항구 (마을) -----
  addMap({
    id: "lith", name: "리스 항구", w: 2200, h: 760, floor: 700, theme: "port", returnMap: "lith", town: true,
    plats: [fh(0, 700, 2200, true), fh(150, 585, 300), fh(950, 585, 260), fh(1500, 585, 300)],
    ladders: [ld(1080, 585, 700)],
    portals: [
      { type: "side", x: 26, y: 700, to: "f5b", tx: 2890, ty: 840 },
      { type: "side", x: 2174, y: 700, to: "f1", tx: 110, ty: 700 },
    ],
    npcs: [
      { kind: "shop", name: "상인 도로시", x: 760, y: 700 },
      { kind: "talk", name: "안내원 리나", x: 1240, y: 700, lines: [
        "빅토리아 아일랜드에 오신 걸 환영해요!",
        "오른쪽으로 가면 달팽이 동산이 나와요. 사냥으로 레벨을 올려보세요.",
        "전사·궁수·도적은 Lv.10, 마법사는 Lv.8이 되면 마을 교관에게 전직할 수 있어요.",
        "전사는 페리온, 마법사는 엘리니아, 궁수는 헤네시스, 도적은 커닝시티!",
        "M 키를 누르면 월드맵을 볼 수 있답니다.",
      ] },
    ],
    spawns: [],
  });

  // ----- 달팽이 동산 -----
  addMap({
    id: "f1", name: "달팽이 동산", w: 3200, h: 760, floor: 700, theme: "meadow", returnMap: "lith",
    plats: [fh(0, 700, 3200, true),
      fh(300, 585, 420), fh(900, 585, 380), fh(1500, 585, 420), fh(2200, 585, 440),
      fh(600, 470, 300), fh(1750, 470, 340), fh(2500, 470, 300)],
    ladders: [ld(1100, 585, 700), ld(1850, 470, 585)],
    portals: [
      { type: "side", x: 26, y: 700, to: "lith", tx: 2090, ty: 700 },
      { type: "side", x: 3174, y: 700, to: "f1b", tx: 110, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "snail", x: 500, y: 700 }, { type: "snail", x: 900, y: 700 }, { type: "snail", x: 1400, y: 700 },
      { type: "snail", x: 2000, y: 700 }, { type: "snail", x: 2600, y: 700 },
      { type: "blueSnail", x: 450, y: 585 }, { type: "blueSnail", x: 1650, y: 585 }, { type: "blueSnail", x: 2350, y: 585 },
      { type: "redSnail", x: 700, y: 470 }, { type: "redSnail", x: 2600, y: 470 },
    ],
  });

  // ----- 헤네시스 (마을) -----
  addMap({
    id: "henesys", name: "헤네시스", w: 2400, h: 760, floor: 700, theme: "henesys", returnMap: "henesys", town: true,
    plats: [fh(0, 700, 2400, true), fh(350, 585, 260), fh(1050, 585, 280), fh(1750, 585, 300)],
    ladders: [ld(1150, 585, 700)],
    portals: [
      { type: "side", x: 26, y: 700, to: "f1b", tx: 2890, ty: 840 },
      { type: "side", x: 2374, y: 700, to: "f2", tx: 110, ty: 840 },
    ],
    npcs: [
      { kind: "job", job: "bowman", name: "궁수 교관 헬레나", x: 1520, y: 700 },
      { kind: "shop", name: "상인 민지", x: 820, y: 700 },
      { kind: "talk", name: "주민 콩이", x: 1900, y: 700, lines: [
        "여긴 궁수의 마을 헤네시스야~",
        "동쪽 사냥터엔 주황버섯이랑 슬라임이 살아.",
        "사냥터 동쪽 끝의 포탈로 가면 잠든 숲으로 갈 수 있대. 무서운 곳이야...",
      ] },
    ],
    spawns: [],
  });

  // ----- 헤네시스 사냥터 -----
  addMap({
    id: "f2", name: "헤네시스 사냥터", w: 3400, h: 900, floor: 840, theme: "forest", returnMap: "henesys",
    plats: [fh(0, 840, 3400, true),
      fh(250, 725, 400), fh(850, 725, 420), fh(1500, 725, 460), fh(2150, 725, 420), fh(2750, 725, 400),
      fh(550, 610, 360), fh(1200, 610, 420), fh(1900, 610, 420), fh(2550, 610, 360),
      fh(900, 495, 500), fh(2000, 495, 460)],
    ladders: [ld(400, 725, 840), ld(2850, 725, 840), ld(1230, 610, 725), ld(1920, 610, 725), ld(1300, 495, 610), ld(2150, 495, 610)],
    portals: [
      { type: "side", x: 26, y: 840, to: "henesys", tx: 2290, ty: 700 },
      { type: "side", x: 3374, y: 840, to: "f2b", tx: 110, ty: 840 },
      { type: "door", x: 3150, y: 840, to: "f6", tx: 250, ty: 840 },
      { type: "door", x: 700, y: 840, to: "slimeTree", tx: 320, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "shroom", x: 600, y: 840 }, { type: "shroom", x: 1500, y: 840 }, { type: "shroom", x: 2400, y: 840 }, { type: "shroom", x: 3000, y: 840 },
      { type: "slime", x: 1000, y: 725 }, { type: "slime", x: 1700, y: 725 }, { type: "slime", x: 2900, y: 725 }, { type: "slime", x: 1400, y: 610 },
      { type: "redSnail", x: 2100, y: 610 }, { type: "redSnail", x: 1100, y: 495 }, { type: "redSnail", x: 2200, y: 495 },
      { type: "slime", x: 900, y: 725 }, { type: "shroom", x: 2600, y: 610 },
    ],
  });

  // ----- 엘리니아 (마을, 수직맵) -----
  addMap({
    id: "ellinia", name: "엘리니아", w: 2200, h: 1500, floor: 1440, theme: "ellinia", returnMap: "ellinia", town: true,
    plats: [fh(0, 1440, 2200, true),
      fh(200, 1325, 300), fh(700, 1325, 340), fh(1300, 1325, 360), fh(1800, 1325, 300),
      fh(450, 1210, 320), fh(1000, 1210, 360), fh(1550, 1210, 320),
      fh(250, 1095, 300), fh(800, 1095, 320), fh(1350, 1095, 340), fh(1850, 1095, 250),
      fh(550, 980, 340), fh(1150, 980, 380), fh(1700, 980, 300),
      fh(350, 865, 320), fh(900, 865, 300), fh(1450, 865, 320),
      fh(600, 750, 360), fh(1200, 750, 340),
      fh(850, 635, 500)],
    ladders: [ld(900, 1325, 1440), ld(1500, 1325, 1440), ld(1180, 980, 1210), ld(450, 1095, 1210), ld(1160, 865, 980), ld(1480, 750, 865), ld(1000, 635, 750)],
    portals: [
      { type: "side", x: 26, y: 1440, to: "f2b", tx: 2890, ty: 840 },
      { type: "side", x: 2174, y: 1440, to: "f3", tx: 110, ty: 840 },
      { type: "door", x: 1900, y: 1440, to: "sleepywood", tx: 1250, ty: 700 },
    ],
    npcs: [
      { kind: "job", job: "magician", name: "마법사 장로 그웬", x: 1100, y: 635 },
      { kind: "boat", name: "선착장 안내원 마리", x: 300, y: 1440 },
      { kind: "shop", name: "상인 프루", x: 560, y: 1440 },
      { kind: "talk", name: "요정 릴리", x: 1620, y: 1440, lines: [
        "여긴 마법사의 마을 엘리니아예요.",
        "장로님은 나무 꼭대기에 계세요. 사다리를 타고 올라가 보세요!",
        "↑ 키로 사다리를 잡을 수 있어요.",
      ] },
    ],
    spawns: [],
  });

  // ----- 엘리니아 깊은 숲 -----
  addMap({
    id: "f3", name: "엘리니아 깊은 숲", w: 3200, h: 900, floor: 840, theme: "deepforest", returnMap: "ellinia",
    plats: [fh(0, 840, 3200, true),
      fh(300, 725, 420), fh(1000, 725, 460), fh(1700, 725, 460), fh(2400, 725, 420),
      fh(650, 610, 380), fh(1350, 610, 420), fh(2050, 610, 380)],
    ladders: [ld(1100, 725, 840), ld(2500, 725, 840), ld(1400, 610, 725), ld(2100, 610, 725)],
    portals: [
      { type: "side", x: 26, y: 840, to: "ellinia", tx: 2090, ty: 1440 },
      { type: "side", x: 3174, y: 840, to: "f3b", tx: 110, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "greenShroom", x: 700, y: 840 }, { type: "greenShroom", x: 1900, y: 840 }, { type: "greenShroom", x: 2800, y: 840 },
      { type: "stump", x: 1200, y: 840 }, { type: "stump", x: 2300, y: 840 },
      { type: "stump", x: 500, y: 725 }, { type: "stump", x: 1850, y: 725 }, { type: "stump", x: 2550, y: 725 },
      { type: "greenShroom", x: 1500, y: 840 }, { type: "darkStump", x: 1500, y: 610 }, { type: "darkStump", x: 2200, y: 610 },
    ],
  });

  // ----- 페리온 (마을) -----
  addMap({
    id: "perion", name: "페리온", w: 2200, h: 900, floor: 840, theme: "perion", returnMap: "perion", town: true,
    plats: [fh(0, 840, 2200, true),
      fh(300, 725, 400), fh(880, 725, 420), fh(1500, 725, 400),
      fh(650, 610, 340), fh(1150, 610, 380),
      fh(900, 495, 400)],
    ladders: [ld(1000, 725, 840), ld(1270, 610, 725), ld(1200, 495, 610)],
    portals: [
      { type: "side", x: 26, y: 840, to: "f3b", tx: 2890, ty: 840 },
      { type: "side", x: 2174, y: 840, to: "f4", tx: 110, ty: 840 },
      { type: "door", x: 300, y: 840, to: "sleepywood", tx: 950, ty: 700 },
    ],
    npcs: [
      { kind: "job", job: "warrior", name: "전사 교관 바우", x: 1100, y: 495 },
      { kind: "shop", name: "상인 톡토", x: 520, y: 840 },
      { kind: "talk", name: "주민 단단", x: 1760, y: 840, lines: [
        "바위산의 마을 페리온에 온 걸 환영한다!",
        "전사 교관님은 제일 높은 바위 위에 계시지.",
        "동쪽 바위산엔 돼지와 멧돼지가 산다. 멧돼지는 성질이 사나우니 조심해!",
        "바위산 한가운데 동굴은 불꽃 멧돼지 굴이다. 파이어보어와 아이언 호그가 날뛰지. Lv.26은 넘기고 가라!",
      ] },
    ],
    spawns: [],
  });

  // ----- 페리온 바위산 -----
  addMap({
    id: "f4", name: "페리온 바위산", w: 3400, h: 900, floor: 840, theme: "rocky", returnMap: "perion",
    plats: [fh(0, 840, 3400, true),
      fh(400, 725, 500), fh(1300, 725, 540), fh(2200, 725, 500),
      fh(800, 610, 400), fh(1800, 610, 420), fh(2700, 610, 400)],
    ladders: [ld(600, 725, 840), ld(2400, 725, 840), ld(850, 610, 725), ld(1820, 610, 725)],
    portals: [
      { type: "side", x: 26, y: 840, to: "perion", tx: 2090, ty: 840 },
      { type: "side", x: 3374, y: 840, to: "f4b", tx: 110, ty: 840 },
      { type: "door", x: 1700, y: 840, to: "fireField", tx: 320, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "pig", x: 600, y: 840 }, { type: "pig", x: 1600, y: 840 }, { type: "pig", x: 2600, y: 840 },
      { type: "pig", x: 1500, y: 725 }, { type: "pig", x: 2400, y: 725 },
      { type: "stump", x: 2000, y: 840 }, { type: "stump", x: 2900, y: 610 }, { type: "boar", x: 1000, y: 840 },
    ],
  });

  // ----- 커닝시티 (마을) -----
  addMap({
    id: "kerning", name: "커닝시티", w: 2400, h: 900, floor: 840, theme: "city", returnMap: "kerning", town: true,
    plats: [fh(0, 840, 2400, true),
      fh(200, 725, 360), fh(800, 725, 400), fh(1400, 725, 380), fh(2000, 725, 300),
      fh(500, 610, 300), fh(1100, 610, 360), fh(1700, 610, 320),
      fh(900, 495, 300)],
    ladders: [ld(950, 725, 840), ld(1180, 610, 725), ld(1150, 495, 610)],
    portals: [
      { type: "side", x: 26, y: 840, to: "f4b", tx: 2890, ty: 840 },
      { type: "side", x: 2374, y: 840, to: "f5", tx: 110, ty: 840 },
      { type: "door", x: 300, y: 840, to: "sewer", tx: 320, ty: 840 },
      { type: "door", x: 2100, y: 840, to: "sleepywood", tx: 260, ty: 700 },
    ],
    npcs: [
      { kind: "job", job: "thief", name: "도적 두목 카일", x: 1040, y: 495 },
      { kind: "shop", name: "상인 제니", x: 620, y: 840 },
      { kind: "pq", name: "PQ 안내원 로지", x: 1500, y: 840 },
      { kind: "talk", name: "주민 삐에로", x: 1880, y: 840, lines: [
        "어둠의 도시 커닝시티에 잘 왔어.",
        "두목님은 옥상 아지트에 계셔. 사다리로 올라가 봐.",
        "동쪽 늪지대엔 옥토퍼스랑 리본돼지가 우글거리지.",
        "마을 서쪽 끝 맨홀은 하수도로 통해. 스티지, 버블링, 리게이터 천지야.",
      ] },
    ],
    spawns: [],
  });

  // ----- 커닝 늪지대 -----
  addMap({
    id: "f5", name: "커닝 늪지대", w: 3200, h: 900, floor: 840, theme: "swamp", returnMap: "kerning",
    plats: [fh(0, 840, 3200, true),
      fh(350, 725, 440), fh(1100, 725, 460), fh(1850, 725, 460), fh(2600, 725, 400),
      fh(700, 610, 380), fh(1500, 610, 400), fh(2250, 610, 380)],
    ladders: [ld(1200, 725, 840), ld(2700, 725, 840), ld(750, 610, 725), ld(2290, 610, 725)],
    portals: [
      { type: "side", x: 26, y: 840, to: "kerning", tx: 2290, ty: 840 },
      { type: "side", x: 3174, y: 840, to: "f5b", tx: 110, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "octopus", x: 700, y: 840 }, { type: "octopus", x: 1700, y: 840 }, { type: "octopus", x: 2700, y: 840 }, { type: "octopus", x: 900, y: 610 },
      { type: "ribbonPig", x: 600, y: 725 }, { type: "ribbonPig", x: 1300, y: 725 }, { type: "ribbonPig", x: 2050, y: 725 }, { type: "ribbonPig", x: 2750, y: 725 },
      { type: "octopus", x: 1200, y: 840 }, { type: "ribbonPig", x: 2200, y: 840 },
    ],
  });

  // ----- 잠든 숲길 -----
  addMap({
    id: "f6", name: "잠든 숲길", w: 2800, h: 900, floor: 840, theme: "duskforest", returnMap: "sleepywood",
    plats: [fh(0, 840, 2800, true),
      fh(400, 725, 460), fh(1200, 725, 500), fh(2000, 725, 460),
      fh(800, 610, 400), fh(1600, 610, 420)],
    ladders: [ld(1300, 725, 840), ld(830, 610, 725), ld(1650, 610, 725)],
    portals: [
      { type: "door", x: 150, y: 840, to: "f2", tx: 3050, ty: 840 },
      { type: "side", x: 2774, y: 840, to: "sleepywood", tx: 110, ty: 700 },
    ],
    npcs: [],
    spawns: [
      { type: "darkStump", x: 600, y: 840 }, { type: "darkStump", x: 1500, y: 840 }, { type: "darkStump", x: 2300, y: 840 },
      { type: "evilEye", x: 700, y: 725 }, { type: "evilEye", x: 1400, y: 725 }, { type: "evilEye", x: 2200, y: 725 },
      { type: "evilEye", x: 1000, y: 610 }, { type: "evilEye", x: 1800, y: 610 },
      { type: "axeStump", x: 900, y: 610 }, { type: "axeStump", x: 1700, y: 610 },
    ],
  });

  // ----- 슬리피우드 (마을) -----
  addMap({
    id: "sleepywood", name: "슬리피우드", w: 2000, h: 760, floor: 700, theme: "sleepywood", returnMap: "sleepywood", town: true,
    plats: [fh(0, 700, 2000, true), fh(400, 585, 300), fh(1300, 585, 300)],
    ladders: [ld(500, 585, 700)],
    portals: [
      { type: "side", x: 26, y: 700, to: "f6", tx: 2690, ty: 840 },
      { type: "door", x: 1700, y: 700, to: "ant", tx: 250, ty: 840 },
      { type: "door", x: 260, y: 700, to: "kerning", tx: 2100, ty: 840 },
      { type: "door", x: 950, y: 700, to: "perion", tx: 300, ty: 840 },
      { type: "door", x: 1250, y: 700, to: "ellinia", tx: 1900, ty: 1440 },
      { type: "door", x: 600, y: 700, to: "zakum", tx: 200, ty: 840 },
    ],
    npcs: [
      { kind: "shop", name: "수상한 상인 그림자", x: 720, y: 700 },
      { kind: "talk", name: "은둔자 노아", x: 1460, y: 700, lines: [
        "...깊은 숲의 마을 슬리피우드에 온 것을 환영하네.",
        "동쪽 포탈 아래는 개미굴이야. 좀비버섯과 뿔버섯이 들끓지.",
        "굴 깊은 곳엔 거대한 버섯, 머쉬맘(Lv.38)이 잠들어 있다네... Lv.30은 넘기고 도전하게.",
        "개미굴 끝에는 드레이크 동굴이 이어져 있어. 콜드아이와 크로코, 드레이크가 산다네.",
        "그리고 그 너머... 어둠의 신전엔 주니어 발록(Lv.50)이 봉인되어 있지. Lv.40 아래라면 목숨을 장담 못 하네.",
      ] },
    ],
    spawns: [],
  });

  // ----- 개미굴 -----
  addMap({
    id: "ant", name: "개미굴", w: 3000, h: 900, floor: 840, theme: "cave", returnMap: "sleepywood",
    plats: [fh(0, 840, 3000, true),
      fh(300, 725, 400), fh(1000, 725, 500), fh(1800, 725, 500), fh(2500, 725, 300),
      fh(600, 610, 400), fh(1400, 610, 460), fh(2200, 610, 400),
      fh(1000, 495, 500), fh(1900, 495, 400)],
    ladders: [ld(1100, 725, 840), ld(2050, 725, 840), ld(650, 610, 725), ld(2250, 610, 725), ld(1450, 495, 610)],
    portals: [
      { type: "door", x: 120, y: 840, to: "sleepywood", tx: 1700, ty: 700 },
      { type: "door", x: 2880, y: 840, to: "drakeCave", tx: 320, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "zombieShroom", x: 500, y: 840 }, { type: "zombieShroom", x: 1200, y: 840 }, { type: "zombieShroom", x: 2000, y: 840 },
      { type: "zombieShroom", x: 2700, y: 840 }, { type: "zombieShroom", x: 800, y: 610 },
      { type: "hornyShroom", x: 1200, y: 725 }, { type: "hornyShroom", x: 2000, y: 725 },
      { type: "hornyShroom", x: 1200, y: 495 }, { type: "hornyShroom", x: 2100, y: 495 },
      { type: "mushmom", x: 1550, y: 840 },
    ],
  });

  // ----- 슬라임 나무 (미니보스: 킹슬라임) -----
  addMap({
    id: "slimeTree", name: "슬라임 나무", w: 2400, h: 900, floor: 840, theme: "forest", returnMap: "henesys",
    plats: [fh(0, 840, 2400, true),
      fh(400, 725, 500), fh(1100, 725, 500), fh(1800, 725, 400),
      fh(700, 610, 400), fh(1500, 610, 400)],
    ladders: [ld(500, 725, 840), ld(1900, 725, 840), ld(830, 610, 725), ld(1550, 610, 725)],
    portals: [
      { type: "door", x: 200, y: 840, to: "f2", tx: 700, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "slime", x: 600, y: 840 }, { type: "slime", x: 1700, y: 840 }, { type: "slime", x: 900, y: 725 }, { type: "slime", x: 1300, y: 725 },
      { type: "shroom", x: 1100, y: 840 }, { type: "shroom", x: 2100, y: 840 }, { type: "shroom", x: 800, y: 610 },
      { type: "kingSlime", x: 1250, y: 840 },
    ],
  });

  // ----- 커닝 하수도 -----
  addMap({
    id: "sewer", name: "커닝 하수도", w: 2800, h: 900, floor: 840, theme: "sewer", returnMap: "kerning",
    plats: [fh(0, 840, 2800, true),
      fh(350, 725, 450), fh(1100, 725, 500), fh(1900, 725, 450),
      fh(700, 610, 400), fh(1500, 610, 450)],
    ladders: [ld(1200, 725, 840), ld(2050, 725, 840), ld(760, 610, 725), ld(1560, 610, 725)],
    portals: [
      { type: "door", x: 200, y: 840, to: "kerning", tx: 300, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "bubbling", x: 500, y: 840 }, { type: "bubbling", x: 1500, y: 840 }, { type: "bubbling", x: 2500, y: 840 },
      { type: "ligator", x: 900, y: 840 }, { type: "ligator", x: 1800, y: 840 }, { type: "ligator", x: 2200, y: 840 },
      { type: "stirge", x: 500, y: 725 }, { type: "stirge", x: 1300, y: 725 }, { type: "stirge", x: 2100, y: 725 },
      { type: "jrNecki", x: 900, y: 610 }, { type: "jrNecki", x: 1700, y: 610 },
    ],
  });

  // ----- 불꽃 멧돼지 굴 -----
  addMap({
    id: "fireField", name: "불꽃 멧돼지 굴", w: 3000, h: 900, floor: 840, theme: "ember", returnMap: "perion",
    plats: [fh(0, 840, 3000, true),
      fh(400, 725, 500), fh(1300, 725, 500), fh(2200, 725, 500),
      fh(850, 610, 400), fh(1750, 610, 420)],
    ladders: [ld(500, 725, 840), ld(2300, 725, 840), ld(900, 610, 725), ld(1800, 610, 725)],
    portals: [
      { type: "door", x: 150, y: 840, to: "f4", tx: 1700, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "fireBoar", x: 600, y: 840 }, { type: "fireBoar", x: 1500, y: 840 }, { type: "fireBoar", x: 2400, y: 840 }, { type: "fireBoar", x: 1600, y: 725 },
      { type: "ironHog", x: 1000, y: 840 }, { type: "ironHog", x: 2000, y: 840 }, { type: "ironHog", x: 2700, y: 840 },
    ],
  });

  // ----- 드레이크 동굴 -----
  addMap({
    id: "drakeCave", name: "드레이크 동굴", w: 2800, h: 900, floor: 840, theme: "cave", returnMap: "sleepywood",
    plats: [fh(0, 840, 2800, true),
      fh(350, 725, 450), fh(1150, 725, 500), fh(1950, 725, 450),
      fh(750, 610, 400), fh(1550, 610, 420)],
    ladders: [ld(450, 725, 840), ld(2050, 725, 840), ld(800, 610, 725), ld(1600, 610, 725)],
    portals: [
      { type: "door", x: 150, y: 840, to: "ant", tx: 2880, ty: 840 },
      { type: "door", x: 2650, y: 840, to: "balrogTemple", tx: 320, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "drake", x: 700, y: 840 }, { type: "drake", x: 1500, y: 840 }, { type: "drake", x: 2300, y: 840 },
      { type: "croco", x: 1100, y: 840 }, { type: "croco", x: 2000, y: 840 },
      { type: "coldEye", x: 600, y: 725 }, { type: "coldEye", x: 1400, y: 725 }, { type: "coldEye", x: 900, y: 610 },
    ],
  });

  // ----- 어둠의 신전 (최종 보스: 주니어 발록) -----
  addMap({
    id: "balrogTemple", name: "어둠의 신전", w: 2600, h: 900, floor: 840, theme: "temple", returnMap: "sleepywood",
    plats: [fh(0, 840, 2600, true),
      fh(350, 725, 450), fh(1100, 725, 500), fh(1850, 725, 450),
      fh(700, 610, 400), fh(1500, 610, 400)],
    ladders: [ld(450, 725, 840), ld(1950, 725, 840), ld(760, 610, 725), ld(1550, 610, 725)],
    portals: [
      { type: "door", x: 150, y: 840, to: "drakeCave", tx: 2650, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "tauromacis", x: 700, y: 840 }, { type: "tauromacis", x: 1800, y: 840 }, { type: "tauromacis", x: 1300, y: 725 },
      { type: "curseEye", x: 600, y: 725 }, { type: "curseEye", x: 1900, y: 725 },
      { type: "jrBalrog", x: 1300, y: 840 },
    ],
  });

  // ----- 길목 필드 5종 (마을 사이 2번째 필드) -----
  function midField(id, name, theme, returnMap, leftTo, leftTx, leftTy, rightTo, rightTx, rightTy, spawns) {
    // 상층부(495/380/265)까지 수직 확장 — 사다리로 오르는 고지대 사냥터
    [[700, 495], [1600, 495], [1050, 380], [1250, 265]].forEach((p, i) => {
      spawns.push({ type: spawns[i % spawns.length].type, x: p[0], y: p[1] });
    });
    addMap({
      id: id, name: name, w: 3000, h: 900, floor: 840, theme: theme, returnMap: returnMap,
      plats: [fh(0, 840, 3000, true),
        fh(350, 725, 450), fh(1150, 725, 500), fh(1950, 725, 450),
        fh(750, 610, 400), fh(1550, 610, 420),
        fh(550, 495, 400), fh(1450, 495, 420),
        fh(900, 380, 500),
        fh(1100, 265, 420)],
      ladders: [ld(450, 725, 840), ld(2050, 725, 840), ld(800, 610, 725), ld(1600, 610, 725),
        ld(820, 495, 610), ld(1650, 495, 610), ld(930, 380, 495), ld(1150, 265, 380)],
      portals: [
        { type: "side", x: 26, y: 840, to: leftTo, tx: leftTx, ty: leftTy },
        { type: "side", x: 2974, y: 840, to: rightTo, tx: rightTx, ty: rightTy },
      ],
      npcs: [],
      spawns: spawns,
    });
  }
  midField("f1b", "달팽이 숲길", "meadow", "henesys", "f1", 3090, 700, "henesys", 110, 700, [
    { type: "blueSnail", x: 600, y: 840 }, { type: "blueSnail", x: 1400, y: 840 }, { type: "blueSnail", x: 2200, y: 840 },
    { type: "slime", x: 2700, y: 840 }, { type: "slime", x: 600, y: 725 }, { type: "slime", x: 1300, y: 725 },
    { type: "redSnail", x: 2100, y: 725 }, { type: "redSnail", x: 900, y: 610 },
  ]);
  midField("f2b", "동쪽 초원", "forest", "ellinia", "f2", 3290, 840, "ellinia", 110, 1440, [
    { type: "shroom", x: 500, y: 840 }, { type: "shroom", x: 1300, y: 840 }, { type: "shroom", x: 2100, y: 840 },
    { type: "ribbonPig", x: 2800, y: 840 }, { type: "ribbonPig", x: 600, y: 725 }, { type: "ribbonPig", x: 1400, y: 725 },
    { type: "octopus", x: 2100, y: 725 }, { type: "octopus", x: 900, y: 610 },
  ]);
  midField("f3b", "바람의 언덕", "deepforest", "perion", "f3", 3090, 840, "perion", 110, 840, [
    { type: "greenShroom", x: 500, y: 840 }, { type: "greenShroom", x: 1400, y: 840 }, { type: "greenShroom", x: 2300, y: 840 },
    { type: "darkStump", x: 2800, y: 840 }, { type: "darkStump", x: 700, y: 725 }, { type: "darkStump", x: 1500, y: 725 },
    { type: "boar", x: 2200, y: 725 }, { type: "boar", x: 900, y: 610 },
  ]);
  midField("f4b", "황혼의 바위길", "rocky", "kerning", "f4", 3290, 840, "kerning", 110, 840, [
    { type: "stump", x: 500, y: 840 }, { type: "stump", x: 1500, y: 840 },
    { type: "evilEye", x: 1000, y: 840 }, { type: "evilEye", x: 2200, y: 840 }, { type: "evilEye", x: 700, y: 725 },
    { type: "boar", x: 2700, y: 840 }, { type: "boar", x: 1400, y: 725 }, { type: "stirge", x: 900, y: 610 },
  ]);
  midField("f5b", "갈대 늪", "swamp", "lith", "f5", 3090, 840, "lith", 110, 700, [
    { type: "octopus", x: 600, y: 840 }, { type: "octopus", x: 1600, y: 840 }, { type: "octopus", x: 2500, y: 840 },
    { type: "bubbling", x: 1100, y: 840 }, { type: "bubbling", x: 800, y: 725 }, { type: "bubbling", x: 1600, y: 725 },
    { type: "ligator", x: 2200, y: 725 },
  ]);

  // ----- 커닝시티 파티퀘스트 (3단계) -----
  addMap({
    id: "pq1", name: "PQ 1단계 — 통행증", w: 2400, h: 900, floor: 840, theme: "sewer", returnMap: "kerning",
    pqDrop: { kind: "pass", rate: 0.55 },
    plats: [fh(0, 840, 2400, true),
      fh(350, 725, 450), fh(1100, 725, 500), fh(1850, 725, 400),
      fh(700, 610, 400), fh(1450, 610, 400)],
    ladders: [ld(1200, 725, 840), ld(760, 610, 725), ld(1500, 610, 725)],
    portals: [
      { type: "door", x: 150, y: 840, to: "kerning", tx: 1500, ty: 840 },
      { type: "door", x: 2280, y: 840, to: "pq2", tx: 320, ty: 840, need: { kind: "pass", n: 10 } },
    ],
    npcs: [],
    spawns: [
      { type: "ligator", x: 500, y: 840 }, { type: "ligator", x: 900, y: 840 }, { type: "ligator", x: 1400, y: 840 },
      { type: "ligator", x: 2000, y: 840 }, { type: "ligator", x: 600, y: 725 }, { type: "ligator", x: 1300, y: 725 },
    ],
  });
  addMap({
    id: "pq2", name: "PQ 2단계 — 열쇠", w: 2400, h: 900, floor: 840, theme: "sewer", returnMap: "kerning",
    pqDrop: { kind: "key", rate: 0.45 },
    plats: [fh(0, 840, 2400, true),
      fh(350, 725, 450), fh(1100, 725, 500), fh(1850, 725, 400),
      fh(700, 610, 400), fh(1450, 610, 400)],
    ladders: [ld(1200, 725, 840), ld(760, 610, 725), ld(1500, 610, 725)],
    portals: [
      { type: "door", x: 150, y: 840, to: "kerning", tx: 1500, ty: 840 },
      { type: "door", x: 2280, y: 840, to: "pq3", tx: 320, ty: 840, need: { kind: "key", n: 5 } },
    ],
    npcs: [],
    spawns: [
      { type: "bubbling", x: 500, y: 840 }, { type: "bubbling", x: 1000, y: 840 }, { type: "bubbling", x: 1600, y: 840 },
      { type: "bubbling", x: 2100, y: 840 }, { type: "bubbling", x: 600, y: 725 }, { type: "bubbling", x: 1350, y: 725 },
      { type: "stirge", x: 900, y: 610 }, { type: "stirge", x: 1600, y: 610 },
    ],
  });
  addMap({
    id: "pq3", name: "PQ 최종 — 킹슬라임", w: 2000, h: 900, floor: 840, theme: "sewer", returnMap: "kerning",
    plats: [fh(0, 840, 2000, true), fh(400, 725, 400), fh(1200, 725, 400)],
    ladders: [ld(500, 725, 840), ld(1300, 725, 840)],
    portals: [
      { type: "door", x: 150, y: 840, to: "kerning", tx: 1500, ty: 840 },
    ],
    npcs: [
      { kind: "pqreward", name: "운영자 빌", x: 420, y: 840 },
    ],
    spawns: [
      { type: "kingSlime", x: 1200, y: 840 },
      { type: "slime", x: 700, y: 840 }, { type: "slime", x: 1600, y: 840 },
      { type: "slime", x: 600, y: 725 }, { type: "slime", x: 1350, y: 725 },
    ],
  });

  // ----- 자쿰의 제단 (레이드) -----
  addMap({
    id: "zakum", name: "자쿰의 제단", w: 2000, h: 900, floor: 840, theme: "ember", returnMap: "sleepywood",
    plats: [fh(0, 840, 2000, true), fh(220, 725, 320), fh(1460, 725, 320)],
    ladders: [ld(300, 725, 840), ld(1550, 725, 840)],
    portals: [
      { type: "door", x: 150, y: 840, to: "sleepywood", tx: 600, ty: 700 },
    ],
    npcs: [],
    spawns: [
      { type: "zakumArm", x: 700, y: 840 }, { type: "zakumArm", x: 860, y: 840 },
      { type: "zakumArm", x: 1140, y: 840 }, { type: "zakumArm", x: 1300, y: 840 },
      { type: "zakumBody", x: 1000, y: 840 },
    ],
  });

  // ----- 오르비스 / 루디브리엄 (배 항로) -----
  addMap({
    id: "orbis", name: "오르비스", w: 2200, h: 760, floor: 700, theme: "sky", returnMap: "orbis", town: true,
    plats: [fh(0, 700, 2200, true), fh(400, 585, 300), fh(1400, 585, 300)],
    ladders: [ld(500, 585, 700)],
    portals: [
      { type: "side", x: 2174, y: 700, to: "orbisField", tx: 110, ty: 840 },
    ],
    npcs: [
      { kind: "boat", name: "선착장 안내원 셀린", x: 500, y: 700 },
      { kind: "shop", name: "상인 루나", x: 1100, y: 700 },
      { kind: "talk", name: "수습 신관 노엘", x: 1700, y: 700, lines: [
        "구름 위의 도시 오르비스에 오신 걸 환영해요!",
        "동쪽 구름 정원엔 차가운 눈의 마물들이 살아요.",
        "선착장에서 배를 타면 장난감의 도시 루디브리엄으로 갈 수 있어요.",
      ] },
    ],
    spawns: [],
  });
  addMap({
    id: "orbisField", name: "구름 정원", w: 3000, h: 900, floor: 840, theme: "sky", returnMap: "orbis",
    plats: [fh(0, 840, 3000, true),
      fh(350, 725, 450), fh(1150, 725, 500), fh(1950, 725, 450),
      fh(750, 610, 400), fh(1550, 610, 420),
      fh(550, 495, 400), fh(1450, 495, 420),
      fh(900, 380, 500), fh(1100, 265, 420)],
    ladders: [ld(450, 725, 840), ld(2050, 725, 840), ld(800, 610, 725), ld(1600, 610, 725),
      ld(820, 495, 610), ld(1650, 495, 610), ld(930, 380, 495), ld(1150, 265, 380)],
    portals: [
      { type: "side", x: 26, y: 840, to: "orbis", tx: 2090, ty: 700 },
      { type: "door", x: 2880, y: 840, to: "orbisBoss", tx: 150, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "coldEye", x: 600, y: 840 }, { type: "coldEye", x: 1500, y: 840 }, { type: "coldEye", x: 2400, y: 840 },
      { type: "curseEye", x: 1000, y: 840 }, { type: "curseEye", x: 600, y: 725 }, { type: "curseEye", x: 1400, y: 725 },
      { type: "croco", x: 2100, y: 725 }, { type: "croco", x: 900, y: 610 },
      { type: "coldEye", x: 700, y: 495 }, { type: "curseEye", x: 1600, y: 495 }, { type: "croco", x: 1100, y: 380 },
    ],
  });
  addMap({
    id: "orbisBoss", name: "구름 신전", w: 1800, h: 900, floor: 840, theme: "sky", returnMap: "orbis",
    plats: [fh(0, 840, 1800, true), fh(300, 725, 320), fh(1180, 725, 320)],
    ladders: [ld(380, 725, 840), ld(1280, 725, 840)],
    portals: [
      { type: "door", x: 150, y: 840, to: "orbisField", tx: 2780, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "cloudBoss", x: 1000, y: 840 },
      { type: "coldEye", x: 500, y: 840 }, { type: "coldEye", x: 1500, y: 840 },
    ],
  });
  addMap({
    id: "ludi", name: "루디브리엄", w: 2200, h: 760, floor: 700, theme: "toy", returnMap: "ludi", town: true,
    plats: [fh(0, 700, 2200, true), fh(400, 585, 300), fh(1400, 585, 300)],
    ladders: [ld(1500, 585, 700)],
    portals: [
      { type: "side", x: 2174, y: 700, to: "ludiField", tx: 110, ty: 840 },
    ],
    npcs: [
      { kind: "boat", name: "차장 토토", x: 500, y: 700 },
      { kind: "shop", name: "상인 삐삐", x: 1100, y: 700 },
      { kind: "talk", name: "장난감 병정 나무", x: 1700, y: 700, lines: [
        "장난감의 도시 루디브리엄에 온 것을 환영한다, 삐빅!",
        "동쪽 시계탑 입구엔 강력한 드레이크와 타우로마시스가 출몰한다, 삐빅!",
        "Lv.36은 넘기고 가는 게 좋을 거다, 삐빅!",
      ] },
    ],
    spawns: [],
  });
  addMap({
    id: "ludiField", name: "시계탑 입구", w: 3000, h: 900, floor: 840, theme: "toy", returnMap: "ludi",
    plats: [fh(0, 840, 3000, true),
      fh(350, 725, 450), fh(1150, 725, 500), fh(1950, 725, 450),
      fh(750, 610, 400), fh(1550, 610, 420),
      fh(550, 495, 400), fh(1450, 495, 420),
      fh(900, 380, 500), fh(1100, 265, 420)],
    ladders: [ld(450, 725, 840), ld(2050, 725, 840), ld(800, 610, 725), ld(1600, 610, 725),
      ld(820, 495, 610), ld(1650, 495, 610), ld(930, 380, 495), ld(1150, 265, 380)],
    portals: [
      { type: "side", x: 26, y: 840, to: "ludi", tx: 2090, ty: 700 },
      { type: "door", x: 2880, y: 840, to: "ludiBoss", tx: 150, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "drake", x: 600, y: 840 }, { type: "drake", x: 1500, y: 840 }, { type: "drake", x: 2400, y: 840 },
      { type: "tauromacis", x: 1000, y: 840 }, { type: "tauromacis", x: 2000, y: 840 },
      { type: "drake", x: 700, y: 725 }, { type: "tauromacis", x: 1500, y: 725 },
      { type: "drake", x: 700, y: 495 }, { type: "drake", x: 1600, y: 495 }, { type: "tauromacis", x: 1100, y: 380 },
    ],
  });
  addMap({
    id: "ludiBoss", name: "시계탑 꼭대기", w: 1800, h: 900, floor: 840, theme: "toy", returnMap: "ludi",
    plats: [fh(0, 840, 1800, true), fh(300, 725, 320), fh(1180, 725, 320)],
    ladders: [ld(380, 725, 840), ld(1280, 725, 840)],
    portals: [
      { type: "door", x: 150, y: 840, to: "ludiField", tx: 2780, ty: 840 },
    ],
    npcs: [],
    spawns: [
      { type: "clockBoss", x: 1000, y: 840 },
      { type: "drake", x: 500, y: 840 }, { type: "drake", x: 1500, y: 840 },
    ],
  });
  // 여객선 갑판 (항해 대기) / 결투장 (PVP)
  addMap({
    id: "ship", name: "여객선 갑판", w: 1400, h: 760, floor: 700, theme: "port", returnMap: "ellinia",
    plats: [fh(0, 700, 1400, true), fh(480, 585, 380)],
    ladders: [ld(560, 585, 700)],
    portals: [],
    npcs: [
      { kind: "talk", name: "선원 톰", x: 1000, y: 700, lines: [
        "어서 오세요! 편히 쉬다 보면 금방 도착합니다.",
        "하늘길은 5분 정도 걸려요. 상단의 항해 시계를 봐 주세요.",
        "갑판에서 떨어지면... 아휴, 생각도 하기 싫네요.",
      ] },
    ],
    spawns: [],
  });
  addMap({
    id: "arena", name: "결투장", w: 1800, h: 900, floor: 840, theme: "rocky", returnMap: "lith",
    plats: [fh(0, 840, 1800, true), fh(350, 725, 320), fh(1130, 725, 320), fh(740, 610, 320)],
    ladders: [ld(430, 725, 840), ld(1230, 725, 840), ld(800, 610, 725)],
    portals: [
      { type: "door", x: 900, y: 840, to: "lith", tx: 1100, ty: 700 },
    ],
    npcs: [],
    spawns: [],
  });

  // ---------- 월드맵 ----------
  const WORLD = {
    nodes: [
      { id: "lith", x: 150, y: 235 }, { id: "f1", x: 265, y: 300, lv: "Lv.1-4" },
      { id: "henesys", x: 385, y: 330 }, { id: "f2", x: 505, y: 300, lv: "Lv.5-9" },
      { id: "ellinia", x: 625, y: 235 }, { id: "f3", x: 585, y: 130, lv: "Lv.12-16" },
      { id: "perion", x: 470, y: 75 }, { id: "f4", x: 340, y: 75, lv: "Lv.7-18" },
      { id: "kerning", x: 215, y: 115 }, { id: "f5", x: 150, y: 170, lv: "Lv.10-13" },
      { id: "f6", x: 505, y: 215, lv: "Lv.16-22" }, { id: "sleepywood", x: 462, y: 168 },
      { id: "ant", x: 408, y: 208, lv: "Lv.22-25" },
      { id: "slimeTree", x: 560, y: 372, lv: "Lv.6-10" },
      { id: "sewer", x: 150, y: 62, lv: "Lv.15-24" },
      { id: "fireField", x: 258, y: 35, lv: "Lv.26-28" },
      { id: "drakeCave", x: 432, y: 252, lv: "Lv.28-36" },
      { id: "balrogTemple", x: 355, y: 273, lv: "Lv.38+" },
      { id: "f1b", x: 325, y: 320, lv: "Lv.2-6" },
      { id: "f2b", x: 572, y: 272, lv: "Lv.8-12" },
      { id: "f3b", x: 528, y: 99, lv: "Lv.15-18" },
      { id: "f4b", x: 275, y: 91, lv: "Lv.12-19" },
      { id: "f5b", x: 138, y: 203, lv: "Lv.12-16" },
      { id: "zakum", x: 516, y: 186, lv: "☠Lv.60 레이드" },
      { id: "orbis", x: 702, y: 70 },
      { id: "orbisField", x: 702, y: 140, lv: "Lv.28-32" },
      { id: "orbisBoss", x: 762, y: 105, lv: "☁Lv.45 보스" },
      { id: "ludi", x: 702, y: 385 },
      { id: "ludiField", x: 702, y: 315, lv: "Lv.36-50" },
      { id: "ludiBoss", x: 762, y: 350, lv: "⏰Lv.55 보스" },
    ],
    edges: [["lith", "f1"], ["f1", "f1b"], ["f1b", "henesys"], ["henesys", "f2"], ["f2", "f2b"], ["f2b", "ellinia"],
      ["ellinia", "f3"], ["f3", "f3b"], ["f3b", "perion"], ["perion", "f4"], ["f4", "f4b"], ["f4b", "kerning"],
      ["kerning", "f5"], ["f5", "f5b"], ["f5b", "lith"],
      ["f2", "f6"], ["f6", "sleepywood"], ["sleepywood", "ant"],
      ["f2", "slimeTree"], ["kerning", "sewer"], ["f4", "fireField"], ["ant", "drakeCave"], ["drakeCave", "balrogTemple"],
      ["sleepywood", "kerning"], ["sleepywood", "perion"], ["sleepywood", "ellinia"],
      ["sleepywood", "zakum"], ["ellinia", "orbis"], ["orbis", "orbisField"], ["orbisField", "orbisBoss"],
      ["orbis", "ludi"], ["ludi", "ludiField"], ["ludiField", "ludiBoss"]],
  };

  // ---------- 몬스터 시뮬레이션 (맵 1개 단위) ----------
  class Sim {
    constructor(mapId) {
      this.id = mapId;
      this.map = MAPS[mapId];
      this.mobs = [];
      this.drops = [];
      this.events = [];
      this.seq = 1;
      this.dropSeq = 1;
      this.lastNow = 0;
      (this.map.spawns || []).forEach((s) => this.mobs.push(this.makeMob(s)));
    }
    platAt(x, y) {
      return this.map.plats.find((p) => Math.abs(p.y - y) < 8 && x >= p.x1 - 4 && x <= p.x2 + 4);
    }
    makeMob(slot) {
      const info = MOB_TYPES[slot.type];
      const plat = this.platAt(slot.x, slot.y) || this.map.plats[0];
      return {
        id: this.seq++, type: slot.type, slot: slot, plat: plat,
        x: slot.x, y: plat.y, vx: (Math.random() < 0.5 ? -1 : 1) * info.speed,
        face: 1, hp: info.hp, maxHp: info.hp, target: null, lastHurt: 0,
        deadUntil: 0, alive: true, kb: 0,
      };
    }
    mobPub(m) {
      return { id: m.id, type: m.type, x: Math.round(m.x), y: m.y, vx: Math.round(m.vx), face: m.face, hp: m.hp, maxHp: m.maxHp };
    }
    snapshot() { return this.mobs.filter((m) => m.alive).map((m) => this.mobPub(m)); }
    deltaList() { return this.mobs.filter((m) => m.alive).map((m) => [m.id, Math.round(m.x), Math.round(m.vx), m.face, m.hp]); }
    dropPub(d) { return { id: d.id, kind: d.kind, amount: d.amount, item: d.item || null, x: d.x, y: d.y }; }
    idle(now) { this.lastNow = now; }
    tick(now, ppl) {
      const dt = Math.min(0.3, (now - (this.lastNow || now)) / 1000);
      this.lastNow = now;
      for (const m of this.mobs) {
        const info = MOB_TYPES[m.type];
        if (!m.alive) {
          if (m.deadUntil && now >= m.deadUntil && !(m.slot && m.slot.once)) {
            Object.assign(m, this.makeMob(m.slot));
            this.events.push({ t: "mobspawn", mob: this.mobPub(m) });
            if (info.boss) this.events.push({ t: "chat", sys: 1, global: 1, text: "💀 " + info.name + "이(가) 깨어났습니다!" });
          }
          continue;
        }
        // 자쿰 2페이즈: 팔이 모두 파괴되면 머리가 제단에서 떨어져 나와 추격
        let spBase = info.speed;
        if (m.type === "zakumBody" && !this.mobs.some((a) => a.alive && a.type === "zakumArm")) {
          spBase = 85;
          if (!m.phase2) {
            m.phase2 = true;
            this.events.push({ t: "chat", sys: 1, global: 1, text: "👁 자쿰의 머리가 제단에서 떨어져 나와 떠다니기 시작합니다!" });
          }
          if (!m.target || !ppl[m.target]) { for (const pid2 in ppl) { m.target = pid2; break; } }
          m.lastHurt = now; // 추적 지속
        }
        // 추적 대상 결정
        let chase = null;
        if (m.target && ppl[m.target]) {
          const tgt = ppl[m.target];
          if (Math.abs(tgt.x - m.x) < 520 && now - m.lastHurt < 8000) chase = tgt;
          else m.target = null;
        } else m.target = null;
        if (!chase && info.aggro) {
          let best = null, bd = 240;
          for (const pid in ppl) {
            const t = ppl[pid];
            const d = Math.abs(t.x - m.x);
            if (d < bd && Math.abs(t.y - m.y) < 140) { bd = d; best = t; }
          }
          if (best) chase = best;
        }
        const sp = spBase * (chase ? 1.3 : 1);
        if (chase) {
          const dx = chase.x - m.x;
          m.vx = Math.abs(dx) < 14 ? 0 : Math.sign(dx) * sp;
        } else {
          if (Math.abs(m.vx) < 1) m.vx = (Math.random() < 0.5 ? -1 : 1) * sp;
          if (Math.random() < dt * 0.15) m.vx = -m.vx;
          m.vx = Math.sign(m.vx) * sp;
        }
        m.x += m.vx * dt + (m.kb || 0) * dt;
        if (m.kb) { m.kb *= Math.pow(0.0001, dt); if (Math.abs(m.kb) < 5) m.kb = 0; }
        const pad = info.w / 2 + 6;
        if (m.x < m.plat.x1 + pad) { m.x = m.plat.x1 + pad; m.vx = Math.abs(m.vx); }
        if (m.x > m.plat.x2 - pad) { m.x = m.plat.x2 - pad; m.vx = -Math.abs(m.vx); }
        if (m.vx !== 0) m.face = m.vx > 0 ? 1 : -1;
      }
      // 자쿰 레이드: 주기적 충격파 (점프로 회피)
      if (this.id === "zakum") {
        const body = this.mobs.find((mm) => mm.alive && mm.type === "zakumBody");
        if (body) {
          if (!body.waveT) body.waveT = now + 9000;
          if (now >= body.waveT) {
            body.waveT = now + 12000;
            this.events.push({ t: "zkwave" });
          }
        }
      }
      // 드랍 만료
      const keep = [];
      for (const d of this.drops) {
        if (now - d.born < 60000) keep.push(d);
        else this.events.push({ t: "lootgone", id: d.id });
      }
      this.drops = keep;
    }
    applyHits(pid, hits) {
      const now = this.lastNow || 0;
      for (const h of (hits || []).slice(0, 8)) {
        const m = this.mobs.find((mm) => mm.alive && mm.id === h.id);
        if (!m) continue;
        const info = MOB_TYPES[m.type];
        // 자쿰 본체: 팔이 모두 파괴되기 전까지 무적
        if (m.type === "zakumBody" && this.mobs.some((a) => a.alive && a.type === "zakumArm")) {
          this.events.push({ t: "mobhit", id: m.id, hp: m.hp, d: 0, by: pid, crit: false, inv: 1 });
          continue;
        }
        const d = Math.max(1, Math.min(5000, Math.round(h.d || 1)));
        m.hp = Math.max(0, m.hp - d);
        m.target = pid;
        m.lastHurt = now;
        m.kb = info.speed === 0 ? 0 : (h.dir || 1) * (info.boss ? 30 : 130);
        this.events.push({ t: "mobhit", id: m.id, hp: m.hp, d: d, by: pid, crit: !!h.c });
        // 보스 분노 페이즈 (50% 이하 — 수하 소환)
        if (info.enrage && !m.enraged && m.hp > 0 && m.hp < m.maxHp * 0.5) {
          m.enraged = true;
          this.events.push({ t: "chat", sys: 1, global: 1, text: "🔥 " + info.name + "이(가) 분노하여 수하를 소환합니다!" });
          for (let zi = 0; zi < info.enrage.n; zi++) {
            const add = this.makeMob({ type: info.enrage.type, x: m.x + (zi % 2 ? 280 : -280), y: m.plat.y, once: true });
            this.mobs.push(add);
            this.events.push({ t: "mobspawn", mob: this.mobPub(add) });
          }
        }
        if (m.hp <= 0) {
          m.alive = false;
          m.deadUntil = now + (info.respawnMs || 6000);
          this.events.push({ t: "mobdie", id: m.id, by: pid, exp: info.exp * 10, type: m.type });
          if (info.boss) this.events.push({ t: "chat", sys: 1, global: 1, text: "🏆 누군가 " + info.name + "을(를) 처치했습니다!" });
          this.rollDrops(m, info, now);
        }
      }
    }
    rollDrops(m, info, now) {
      let i = 0;
      const mk = (kind, amount, item) => {
        const d = { id: "d" + (this.dropSeq++), kind: kind, amount: amount || 0, item: item || null, x: Math.round(m.x + i * 34 - 34), y: m.plat.y, born: now };
        i++;
        this.drops.push(d);
        this.events.push({ t: "drop", d: this.dropPub(d) });
      };
      // 파티퀘스트 아이템 (맵 지정 드랍)
      if (this.map.pqDrop && Math.random() < this.map.pqDrop.rate) mk(this.map.pqDrop.kind);
      // 몬스터별 고유 기타 아이템 (40%, 보스 100%)
      const eid = MOB_ETC[m.type];
      if (eid && Math.random() < (info.boss ? 1 : 0.4)) mk("etc", 0, eid);
      if (Math.random() < 0.78 || info.boss) mk("meso", rnd(info.meso[0], info.meso[1]));
      if (info.boss) { mk("red"); mk("red"); mk("blue"); mk("blue"); }
      else {
        const r = Math.random();
        if (r < 0.16) mk("red");
        else if (r < 0.27) mk("blue");
      }
      // 장비 드랍: 그 레벨대 몬스터는 그 레벨대 장비 (몹 레벨 -8 ~ +5, 보스 전용은 제외)
      const pool = Object.keys(EQUIP).filter((k) => !EQUIP[k].boss && EQUIP[k].lv >= info.lvl - 8 && EQUIP[k].lv <= info.lvl + 5);
      if (info.boss) {
        // 보스 전용 장비 45%
        const bg = Object.keys(EQUIP).filter((k) => EQUIP[k].boss === m.type);
        if (bg.length && Math.random() < 0.45) mk("equip", 0, bg[Math.floor(Math.random() * bg.length)]);
        if (pool.length) {
          mk("equip", 0, pool[Math.floor(Math.random() * pool.length)]);
          if (Math.random() < 0.25) mk("equip", 0, pool[Math.floor(Math.random() * pool.length)]);
        }
      } else if (pool.length && Math.random() < 0.04) {
        mk("equip", 0, pool[Math.floor(Math.random() * pool.length)]);
      }
      // 강화 주문서 (종류 랜덤) / 미라클 큐브 (등급)
      if (info.boss) {
        mk("etc", 0, SCROLL_IDS[Math.floor(Math.random() * SCROLL_IDS.length)]);
        if (Math.random() < 0.6) mk("etc", 0, SCROLL_IDS[Math.floor(Math.random() * SCROLL_IDS.length)]);
        if (Math.random() < 0.6) mk("etc", 0, "e_cube2");
        if (Math.random() < 0.25) mk("etc", 0, "e_cube3");
      } else if (info.lvl >= 8) {
        if (Math.random() < 0.06) mk("etc", 0, SCROLL_IDS[Math.floor(Math.random() * SCROLL_IDS.length)]);
        if (Math.random() < 0.01) mk("etc", 0, "e_cube");
        if (info.lvl >= 20 && Math.random() < 0.003) mk("etc", 0, "e_cube2");
      }
    }
    loot(pid, id, px, py) {
      const di = this.drops.findIndex((d) => d.id === id);
      if (di < 0) return;
      const d = this.drops[di];
      if (Math.abs(d.x - px) > 140 || Math.abs(d.y - py) > 180) return;
      this.drops.splice(di, 1);
      this.events.push({ t: "lootgone", id: d.id, by: pid, kind: d.kind, amount: d.amount, item: d.item || null });
    }
  }

  // ---------- 게임 호스트 (서버/솔로 공용 두뇌) ----------
  function num(v, dflt) { return typeof v === "number" && isFinite(v) ? v : dflt; }

  class GameHost {
    constructor() {
      this.players = new Map();
      this.sims = new Map();
      this.onSend = null;
      this.persist = null;       // 서버 저장소 훅 {load(name), save(name,data)}
      this.parties = new Map();  // partyId -> {id, leader, members:Set}
      this.partySeq = 1;
    }
    send(id, msg) { if (this.onSend) this.onSend(id, msg); }
    countJoined() { let n = 0; this.players.forEach((p) => { if (p.joined) n++; }); return n; }
    addPlayer(id) {
      this.players.set(id, {
        id: id, joined: false, map: null, x: 0, y: 0, name: "?", look: null,
        level: 1, job: "beginner", face: 1, anim: "idle", hp: 1, party: null,
      });
      this.send(id, { t: "hello", id: id, online: this.countJoined() });
    }
    sendPupdate(party) {
      const members = [];
      party.members.forEach((mid) => {
        const m = this.players.get(mid);
        if (m) members.push({ id: m.id, name: m.name, level: m.level, job: m.job });
      });
      party.members.forEach((mid) => this.send(mid, { t: "pupdate", members: members, leader: party.leader }));
    }
    leaveParty(id, silent) {
      const p = this.players.get(id);
      if (!p || !p.party) return;
      const party = this.parties.get(p.party);
      p.party = null;
      this.send(id, { t: "pupdate", members: [], leader: null });
      if (!party) return;
      party.members.delete(id);
      if (party.members.size === 0) { this.parties.delete(party.id); return; }
      if (party.leader === id) party.leader = party.members.values().next().value;
      this.sendPupdate(party);
      if (!silent) party.members.forEach((mid) => this.send(mid, { t: "chat", sys: 1, text: (p.name || "?") + "님이 파티에서 나갔습니다." }));
    }
    removePlayer(id) {
      const p = this.players.get(id);
      if (!p) return;
      this.leaveParty(id, false);
      this.players.delete(id);
      if (p.joined) {
        this.bmap(p.map, { t: "pleave", id: id }, id);
        this.ball({ t: "chat", sys: 1, text: p.name + "님이 게임을 떠났습니다." });
      }
    }
    ball(msg, except) { this.players.forEach((p) => { if (p.joined && p.id !== except) this.send(p.id, msg); }); }
    bmap(map, msg, except) { this.players.forEach((p) => { if (p.joined && p.map === map && p.id !== except) this.send(p.id, msg); }); }
    ensureSim(map) {
      if (!this.sims.has(map)) this.sims.set(map, new Sim(map));
      return this.sims.get(map);
    }
    pubState(p) {
      return { id: p.id, name: p.name, look: p.look, level: p.level, job: p.job, x: p.x, y: p.y, face: p.face, anim: p.anim, hp: p.hp };
    }
    sendSnap(p) {
      const sim = this.ensureSim(p.map);
      const players = [];
      this.players.forEach((o) => { if (o.joined && o.map === p.map && o.id !== p.id) players.push(this.pubState(o)); });
      this.send(p.id, { t: "snap", map: p.map, players: players, mobs: sim.snapshot(), drops: sim.drops.map((d) => sim.dropPub(d)) });
    }
    flushSim(map, sim) {
      const evs = sim.events;
      sim.events = [];
      for (const e of evs) {
        if (e.global) { const g = Object.assign({}, e); delete g.global; this.ball(g); }
        else this.bmap(map, e);
        // 파티 경험치 분배 (막타 60% / 나머지 40% 균등 + 인원당 5% 보너스)
        if (e.t === "mobdie" && e.by) {
          const killer = this.players.get(e.by);
          if (killer && killer.party) {
            const party = this.parties.get(killer.party);
            if (party) {
              const inMap = [];
              party.members.forEach((mid) => {
                const m = this.players.get(mid);
                if (m && m.joined && m.map === map) inMap.push(m);
              });
              const total = e.exp * (1 + 0.05 * Math.max(0, inMap.length - 1));
              if (inMap.length <= 1) {
                this.send(e.by, { t: "pexp", amount: Math.round(total) });
              } else {
                inMap.forEach((m) => {
                  const share = m.id === e.by ? 0.6 : 0.4 / (inMap.length - 1);
                  this.send(m.id, { t: "pexp", amount: Math.max(1, Math.round(total * share)) });
                });
              }
            }
          }
        }
      }
    }
    handle(id, msg) {
      const p = this.players.get(id);
      if (!p || !msg || typeof msg.t !== "string") return;
      switch (msg.t) {
        case "join": {
          if (p.joined) return;
          p.joined = true;
          p.name = String(msg.name || "무명").slice(0, 10);
          p.look = msg.look || {};
          p.level = Math.max(1, Math.min(CONST.MAXLV, num(msg.level, 1)));
          p.job = JOB_NAMES[msg.job] ? msg.job : "beginner";
          p.map = MAPS[msg.map] ? msg.map : "lith";
          p.x = num(msg.x, 1100); p.y = num(msg.y, 700);
          p.hp = num(msg.hp, 1);
          this.sendSnap(p);
          this.bmap(p.map, { t: "pjoin", p: this.pubState(p) }, id);
          this.ball({ t: "chat", sys: 1, text: "🍁 " + p.name + "님이 접속했습니다. (현재 " + this.countJoined() + "명)" });
          if (this.persist) {
            const saved = this.persist.load(p.name);
            if (saved) this.send(id, { t: "charload", data: saved });
          }
          break;
        }
        case "charsave": {
          if (!p.joined || !this.persist || !msg.data || typeof msg.data !== "object") return;
          this.persist.save(p.name, msg.data);
          break;
        }
        case "trade": {
          // 거래 메시지 릴레이 (로직은 클라이언트 간 신뢰 기반)
          if (!p.joined) return;
          const tgt = this.players.get(msg.target);
          if (!tgt || !tgt.joined) return;
          this.send(tgt.id, { t: "ptrade", from: id, name: p.name, op: String(msg.op || "").slice(0, 12), data: msg.data || null });
          break;
        }
        case "pvp": {
          // PVP 결투 메시지 릴레이 (신청/수락/데미지/종료 — 로직은 클라이언트 간)
          if (!p.joined) return;
          const tgt = this.players.get(msg.target);
          if (!tgt || !tgt.joined) return;
          this.send(tgt.id, { t: "ppvp", from: id, name: p.name, op: String(msg.op || "").slice(0, 12), data: msg.data || null });
          break;
        }
        case "party": {
          if (!p.joined) return;
          const op = msg.op;
          if (op === "create") {
            if (p.party) return;
            const ptid = "pt" + (this.partySeq++);
            this.parties.set(ptid, { id: ptid, leader: id, members: new Set([id]) });
            p.party = ptid;
            this.sendPupdate(this.parties.get(ptid));
            this.send(id, { t: "chat", sys: 1, text: "파티를 만들었습니다. P키 창에서 근처 유저를 초대하세요!" });
          } else if (op === "invite") {
            if (!p.party) return;
            const tgt = this.players.get(msg.target);
            if (!tgt || !tgt.joined) return;
            if (tgt.party) { this.send(id, { t: "chat", sys: 1, text: tgt.name + "님은 이미 파티에 속해 있습니다." }); return; }
            const party = this.parties.get(p.party);
            if (!party || party.members.size >= 6) return;
            this.send(tgt.id, { t: "pinvite", from: id, name: p.name });
            this.send(id, { t: "chat", sys: 1, text: tgt.name + "님에게 파티 초대를 보냈습니다." });
          } else if (op === "accept") {
            if (p.party) return;
            const inviter = this.players.get(msg.from);
            if (!inviter || !inviter.party) return;
            const party = this.parties.get(inviter.party);
            if (!party || party.members.size >= 6) return;
            party.members.add(id);
            p.party = party.id;
            this.sendPupdate(party);
            party.members.forEach((mid) => this.send(mid, { t: "chat", sys: 1, text: "🤝 " + p.name + "님이 파티에 합류했습니다!" }));
          } else if (op === "decline") {
            const inviter = this.players.get(msg.from);
            if (inviter) this.send(inviter.id, { t: "chat", sys: 1, text: p.name + "님이 초대를 거절했습니다." });
          } else if (op === "leave") {
            this.leaveParty(id, false);
          }
          break;
        }
        case "state": {
          if (!p.joined) return;
          const newLv = Math.max(1, Math.min(CONST.MAXLV, num(msg.level, p.level)));
          if (newLv > p.level) this.ball({ t: "chat", sys: 1, text: "🎉 " + p.name + "님이 Lv." + newLv + "을(를) 달성했습니다!" });
          p.level = newLv;
          p.x = num(msg.x, p.x); p.y = num(msg.y, p.y);
          p.face = msg.face === -1 ? -1 : 1;
          p.anim = String(msg.anim || "idle").slice(0, 12);
          p.hp = num(msg.hp, p.hp);
          if (JOB_NAMES[msg.job]) p.job = msg.job;
          this.bmap(p.map, Object.assign({ t: "pstate" }, this.pubState(p)), id);
          break;
        }
        case "map": {
          if (!p.joined || !MAPS[msg.map]) return;
          this.bmap(p.map, { t: "pleave", id: id }, id);
          p.map = msg.map;
          p.x = num(msg.x, 100); p.y = num(msg.y, MAPS[msg.map].floor);
          this.sendSnap(p);
          this.bmap(p.map, { t: "pjoin", p: this.pubState(p) }, id);
          break;
        }
        case "chat": {
          if (!p.joined) return;
          const text = String(msg.text || "").slice(0, 80);
          if (!text.trim()) return;
          this.ball({ t: "chat", from: id, name: p.name, text: text });
          break;
        }
        case "action": {
          if (!p.joined) return;
          this.bmap(p.map, { t: "paction", id: id, kind: String(msg.kind || "").slice(0, 16), x: p.x, y: p.y, face: p.face, job: p.job }, id);
          break;
        }
        case "job": {
          if (!p.joined || !JOB_NAMES[msg.job] || msg.job === "beginner") return;
          p.job = msg.job;
          const disp = typeof msg.title === "string" && msg.title.trim() ? msg.title.slice(0, 12) : JOB_NAMES[msg.job];
          this.ball({ t: "chat", sys: 1, text: "⚔️ " + p.name + "님이 " + disp + "(으)로 전직했습니다!" });
          break;
        }
        case "hit": {
          if (!p.joined) return;
          const sim = this.ensureSim(p.map);
          sim.applyHits(id, Array.isArray(msg.hits) ? msg.hits : []);
          this.flushSim(p.map, sim);
          break;
        }
        case "loot": {
          if (!p.joined) return;
          const sim = this.ensureSim(p.map);
          sim.loot(id, msg.id, p.x, p.y);
          this.flushSim(p.map, sim);
          break;
        }
      }
    }
    tick(now) {
      this.sims.forEach((sim, map) => {
        let has = false;
        const ppl = {};
        this.players.forEach((p) => { if (p.joined && p.map === map) { has = true; ppl[p.id] = { x: p.x, y: p.y }; } });
        if (!has) { sim.idle(now); return; }
        sim.tick(now, ppl);
        this.flushSim(map, sim);
        this.bmap(map, { t: "mobs", list: sim.deltaList() });
      });
    }
  }

  return {
    CONST: CONST, JOB_NAMES: JOB_NAMES, JOB_REQ: JOB_REQ, MOB_TYPES: MOB_TYPES, MAPS: MAPS, WORLD: WORLD,
    EQUIP: EQUIP, EQUIP_SLOTS: EQUIP_SLOTS, ETC: ETC, MOB_ETC: MOB_ETC, QUESTS: QUESTS, SCROLLS: SCROLLS,
    expNeed: expNeed, maxHp: maxHp, maxMp: maxMp, dmgRange: dmgRange, touchDmg: touchDmg,
    Sim: Sim, GameHost: GameHost,
  };
});
