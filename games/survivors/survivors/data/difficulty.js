// 난이도는 로비/딥링크/멀티 패킷이 같은 id를 공유한다.
// 수치는 세 축만 건드린다: 받는 피해, 동시 물량, 적 체력.
export const DIFFICULTIES = {
  story: {
    id: 'story', name: '이야기', icon: '🌱',
    desc: '성장과 보스 패턴을 편하게 익히는 모드',
    taken: 0.65, cap: 0.8, hp: 0.9,
  },
  normal: {
    id: 'normal', name: '보통', icon: '⚔️',
    desc: '권장 난이도 · 원래 의도한 15분 전투',
    taken: 1, cap: 1, hp: 1,
  },
  veteran: {
    id: 'veteran', name: '숙련', icon: '🔥',
    desc: '더 빽빽하고 단단한 적을 상대하는 도전',
    taken: 1.15, cap: 1.12, hp: 1.15,
  },
};

export const DIFFICULTY_IDS = Object.freeze(Object.keys(DIFFICULTIES));

export function normalizeDifficulty(id, fallback = 'normal') {
  return DIFFICULTIES[id] ? id : fallback;
}

export function difficultyConfig(id) {
  return DIFFICULTIES[normalizeDifficulty(id)];
}
