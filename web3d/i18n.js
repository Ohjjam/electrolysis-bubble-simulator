/* Runtime Korean/English switch shared by the 2-D and 3-D views.
 *
 * The catalog is local: switching languages never sends simulation text to a
 * network service.  A MutationObserver covers controls and status labels that
 * are created or replaced after the initial page load. Canvas text is routed
 * through the same translator so chart labels follow the selected language.
 */
(function (g) {
  "use strict";

  const STORAGE_KEY = "bubblesim.language";
  const catalog = Object.assign({}, g.SIM_I18N_EN || {}, {
    "3D 전기화학 셀 시뮬레이터": "3D Electrochemical Cell Simulator",
    "3D 셀 시뮬레이터": "3D Cell Simulator",
    "① 국소 확대": "① Local zoom",
    "축약모델": "Reduced-order model",
    "🧪 mesh 실험": "🧪 Mesh experiment",
    "Mesh 계산 방식": "Mesh calculation mode",
    "Mesh 1 · 형상+소수성": "Mesh 1 · geometry + hydrophobicity",
    "Mesh 2 · 소수성만": "Mesh 2 · hydrophobicity only",
    "mesh (두께는 유로 계산에서 제외)": "mesh (thickness excluded from flow calculation)",
    "mesh 두께는 카탈로그 정보로만 남습니다.": "Mesh thickness remains catalog information only.",
    "유로 단면·유속·체류시간·압력손실은 pristine과 같고,": "Flow cross-section, velocity, residence time, and pressure drop remain pristine,",
    "그물코 접촉확률 × 입력한 접촉각의 Young 구동력": "mesh-contact probability × Young driving force from the entered contact angles",
    "그물코 접촉확률 × 실측 가스버블 접촉각의 Young 구동력": "mesh-contact probability × Young driving force from the measured gas-bubble contact angles",
    "만 전극 기포 덮임에 반영합니다.": "is the only effect applied to electrode bubble coverage.",
    "가스버블 각도는 물 접촉각으로 변환해 계산하며, PP의 더 작은 각도가 기체 선호 방향입니다.": "Gas-bubble angles are converted to water contact angles for the calculation; the smaller PP angle is the gas-preferred direction.",
    "수중 가스버블 접촉각 — 기포 내부 기준": "Submerged gas-bubble contact angle — measured through the gas",
    "촉매/NF θ": "Catalyst/NF θ",
    "실측 기본값(n=3)": "Measured defaults (n=3)",
    "촉매/NF 145.1±2.3° (142.5/146.3/146.6) · bare PP mesh 101.2±1.6° (99.7/101.2/102.8).": "Catalyst/NF 145.1±2.3° (142.5/146.3/146.6) · bare PP mesh 101.2±1.6° (99.7/101.2/102.8).",
    "가스버블 각도는 내부에서": "The gas-bubble angle is internally converted using",
    "로 변환합니다.": ".",
    "PP 쪽 기체 선호 구동력이 있는 조건": "positive gas-transfer driving force toward PP",
    "PP 가스버블 각도가 더 작지 않아 전달 구동력 0": "no transfer drive because the PP gas-bubble angle is not smaller",
    "가스버블각 NF 145.1° · PP 101.2°": "gas-bubble angles NF 145.1° · PP 101.2°",
    "소수성 기포 전달과 함께 mesh 고체 체적이": "Along with hydrophobic bubble transfer, the mesh solid volume",
    "유로 단면을 줄이는 효과를 유속·체류시간·압력손실에 반영합니다.": "reduces the flow cross-section and changes velocity, residence time, and pressure loss.",
    "Mesh 2에서는 위 두께를 유로 단면·유속·압력손실 계산에 사용하지 않습니다.": "Mesh 2 does not use the thickness above in flow cross-section, velocity, or pressure-loss calculations.",
    "Mesh 2 소수성 물리": "Mesh 2 hydrophobic physics",
    "Mesh 1 형상+소수성 물리": "Mesh 1 geometry + hydrophobic physics",
    "M2 소수성만": "M2 hydrophobic only",
    "M1 형상+소수성": "M1 geometry + hydrophobicity",
    "전압차 mesh − pristine (음수=개선)": "Voltage difference mesh − pristine (negative = improvement)",
    "최대전류 기액비": "Gas-to-liquid ratio at maximum current",
    "이탈기포": "Detached bubble diameter",
    "접촉확률 상한": "Contact-probability upper bound",
    "젖음성 구동": "Wettability driving force",
    "전달지수 상한": "Transfer-index upper bound",
    "유로 폐색": "Flow-path obstruction",
    "국소유속": "Local velocity",
    "층류 ΔP 추정": "Laminar ΔP estimate",
    "블라인드 예측 — 실측 mesh 곡선과 직접 비교해보세요.": "Blind prediction — compare it directly with the measured mesh curve.",
    "두께의 유체역학 효과 제외": "hydraulic thickness effects excluded",
    "⑥ PP mesh — Mesh 1 형상효과 / Mesh 2 소수성 분리": "⑥ PP mesh — separate Mesh 1 geometry from Mesh 2 hydrophobicity",
    "📐 수식": "📐 Equations",
    "📊 데이터": "📊 Data",
    "＋ 실험 저장": "＋ Save experiment",
    "🤖 AI 설계": "🤖 AI design",
    "🤖 자연어 설계 연결": "🤖 Natural-language design",
    "API 키 상태 확인 중…": "Checking API key status…",
    "AI 공급자": "AI provider",
    "OpenRouter · 무료/다중 모델": "OpenRouter · free / multi-model",
    "모델": "Model",
    "균형": "balanced",
    "빠름/저비용": "fast / lower cost",
    "저비용": "lower cost",
    "최저비용": "lowest cost",
    "무료": "free",
    "최고성능": "highest capability",
    "정밀": "high reasoning",
    "OpenRouter 모델 ID": "OpenRouter model ID",
    "예: qwen/qwen3.5-flash-02-23": "Example: qwen/qwen3.5-flash-02-23",
    "직접 모델 ID 입력": "Enter model ID",
    "이 서버 세션에만 보관": "kept for this server session only",
    "OpenAI API 키 · 이 서버 세션에만 보관": "OpenAI API key · kept for this server session only",
    "환경변수 OPENAI_API_KEY 권장": "OPENAI_API_KEY environment variable recommended",
    "세션 키 등록": "Register session key",
    "세션 키 지우기": "Clear session key",
    "임시 키 등록": "Register temporary key",
    "지금 삭제": "Delete now",
    "자동 삭제": "Automatic deletion",
    "15분": "15 minutes",
    "1시간": "1 hour",
    "2시간": "2 hours",
    "브라우저 임시 세션": "temporary browser session",
    "키는 이 브라우저 전용 서버 메모리에만 보관되고 선택한 시간이 지나면 자동 삭제됩니다. 공개 서버의 환경변수 키는 외부 사용자에게 공유되지 않습니다.": "The key is kept only in server memory for this browser and is deleted after the selected time. Environment keys on the public server are never shared with external users.",
    "임시 키를 등록했습니다. 선택한 시간이 지나면 자동 삭제됩니다.": "Temporary key registered. It will be deleted after the selected time.",
    "이 브라우저의 임시 키를 삭제했습니다.": "Deleted this browser's temporary key.",
    "키는 HTML·localStorage·파일·응답에 저장하지 않습니다. 로컬 브라우저에서만 AI 호출이 허용되며 서버를 끄면 세션 키가 사라집니다.": "The key is never stored in HTML, localStorage, files, or responses. AI calls are local-browser only, and the session key disappears when the server stops.",
    "자연어로 유로·설정 수정": "Edit flow field and settings with natural language",
    "예: 하단 입구에서 상단 출구까지 연결되는 지그재그 유로를 만들고, 1 A/cm²에서 기포 홀드업을 줄일 후보 2개도 비교해줘. 모델/피팅값은 건드리지 마.": "Example: Create a connected zigzag flow field from the bottom inlet to the top outlet and compare two candidates that may reduce bubble hold-up at 1 A/cm². Do not change model/fitted values.",
    "계획 만들고 자동 시험": "Create plan and test automatically",
    "AI는 허용된 설정과 유로 마스크만 제안합니다. 임의 코드는 실행하지 않습니다.": "AI may propose only allowed settings and flow masks. It cannot execute arbitrary code.",
    "변경 미리보기": "Change preview",
    "자동 시험 결과": "Automatic test results",
    "분극 비교는 1-D 축약 채널 모델입니다. 임의 유로 형상은 연결성과 3D 격자 빌드만 검사하며, 세부 형상별 성능은 직접 해석한 것으로 간주하지 않습니다.": "Polarization comparison uses the 1-D reduced-order channel model. A custom flow shape is checked for connectivity and 3D grid build only; its detailed performance is not treated as directly resolved.",
    "검증된 변경 적용": "Apply validated changes",
    "시각 프리셋": "Visual preset",
    "실물 전체": "Full assembly",
    "내부 보기": "Internal cutaway",
    "분석 보기": "Analysis view",
    "3D 셀 분석": "3D cell analysis",
    "3D 셀 분석 항목": "3D cell analysis field",
    "분석 색상 끄기": "Turn analysis colors off",
    "부드러운 스펙트럼": "Smooth spectrum",
    "색상만 보간 · 계산값은 원본 복셀": "Color interpolation only · calculations use original voxels",
    "색상만 보간하며 계산과 마우스 위치값은 원본 복셀을 사용합니다.": "Only the colors are interpolated; calculations and hovered values use the original voxels.",
    "가스 홀드업 ε": "Gas holdup ε",
    "액체 유속 |u|": "Liquid speed |u|",
    "음극 전류밀도 j": "Cathode current density j",
    "양극 전류밀도 j": "Anode current density j",
    "음극 기포 덮임 θ": "Cathode bubble coverage θ",
    "양극 기포 덮임 θ": "Anode bubble coverage θ",
    "셀에 표시할 계산 필드를 고르세요.": "Choose a computed field to paint on the cell.",
    "관통방향 최대 가스 체적분율입니다. 0은 액체, 1은 가스입니다.": "Maximum through-plane gas volume fraction. 0 is liquid and 1 is gas.",
    "관통방향 최대 액체 속도입니다.": "Maximum through-plane liquid speed.",
    "기포 덮임을 반영해 재분배된 음극면 전류밀도입니다.": "Cathode-face current density redistributed for bubble coverage.",
    "기포 덮임을 반영해 재분배된 양극면 전류밀도입니다.": "Anode-face current density redistributed for bubble coverage.",
    "음극면에서 기포가 가린 면적 비율입니다.": "Fraction of the cathode face covered by bubbles.",
    "양극면에서 기포가 가린 면적 비율입니다.": "Fraction of the anode face covered by bubbles.",
    "표시 중": "Showing",
    "대기": "Waiting",
    "셀 색상 위에 마우스를 올리면 위치별 값이 나옵니다.": "Hover over the colored cell to read the local value.",
    "리브 영역 · 계산값 없음": "Rib area · no field value",
    "실험·도구 ▾": "Experiments & tools ▾",
    "🧪 실험 뷰": "🧪 Experiment view",
    "현재 유로와 설정을 함께 저장합니다.": "Save the current flow field and settings together.",
    "회전 · 좌우 이동 · 휠/± 줌": "Rotate · pan · wheel/± zoom",
    "API 키 준비됨": "API key ready",
    "환경변수": "environment variable",
    "서버 세션": "server session",
    "없음": "none",
    "API 키가 없습니다. 환경변수 또는 세션 키를 등록하세요.": "No API key is configured. Set the environment variable or register a session key.",
    "등록할 API 키를 입력하세요.": "Enter an API key to register.",
    "사용할 모델 ID를 입력하세요.": "Enter the model ID to use.",
    "세션 키를 등록했습니다. 서버를 끄면 사라집니다.": "Session key registered. It disappears when the server stops.",
    "세션 키를 지웠습니다.": "Session key cleared.",
    "요약 없음": "No summary",
    "모델/피팅값": "Model / fitted value",
    "운전/형상값": "Operating / geometry value",
    "스칼라 설정 변경 없음": "No scalar setting changes",
    "임의 유로": "Custom flow field",
    "유로 템플릿": "Flow-field template",
    "현재 유로 유지": "Keep current flow field",
    "도달 불가": "Unreachable",
    "3D 빌드 통과": "3D build passed",
    "3D 빌드 실패": "3D build failed",
    "1 A/cm²": "1 A/cm²",
    "2 A/cm²": "2 A/cm²",
    "최대 도달 전류": "Maximum reachable current",
    "물 공급 한계": "Water-supply limit",
    "현재 대비 AI 계획의 1 A/cm² 전압 차이": "AI-plan voltage difference vs current at 1 A/cm²",
    "자연어 요청을 입력하세요.": "Enter a natural-language request.",
    "먼저 환경변수 또는 세션 API 키를 등록하세요.": "Configure the environment variable or a session API key first.",
    "AI 계획을 만들고 있습니다…": "Creating the AI plan…",
    "계획 생성 완료 · 로컬 모델 시험 중…": "Plan created · running local model tests…",
    "계획과 시험이 완료됐습니다.": "Plan and tests completed.",
    "검증된 변경을 적용하고 있습니다…": "Applying validated changes…",
    "변경을 적용했습니다. 3D와 설정 패널이 새 상태로 동기화됩니다.": "Changes applied. The 3D view and settings panel will synchronize to the new state.",
    "3D 자유": "Free 3D",
    "3D 보기": "3D view",
    "드래그 회전": "Drag to rotate",
    "모바일 3D 카메라 조작": "Mobile 3D camera controls",
    "시점 초기화": "Reset view",
    "설정 모두 접기": "Collapse all settings",
    "설정 모두 펼치기": "Expand all settings",
    "설정 접기 또는 펼치기": "Collapse or expand setting",
    "3개의 층이": "Three coupled layers",
    "양방향": "bidirectionally ",
    "으로 맞물려 돕니다.": "interact.",
    "커플링이 핵심": "The coupling is the key ",
    "이지, 각 식이 새로운 건 아닙니다.": "; the individual equations themselves are standard.",
    "② 전체 셀": "② Full cell",
    "운전 (전기)": "Operation (electrical)",
    "운전 모드": "Operating mode",
    "정전류 CP": "Galvanostatic CP",
    "정전압 CA": "Potentiostatic CA",
    "전류밀도 j": "Current density j",
    "셀 전압 (CA)": "Cell voltage (CA)",
    "전해질": "Electrolyte",
    "인산": "Phosphoric acid",
    "농도 (높을수록 합체 억제)": "Concentration (higher suppresses coalescence)",
    "유동 · 기포": "Flow and bubbles",
    "유량 (펌프)": "Flow velocity (pump)",
    "전극 물 접촉각 (기포 이탈)": "Electrode water contact angle (bubble detachment)",
    "셀 기울기": "Cell tilt",
    "시간 배속 (0.02=초고속카메라)": "Time scale (0.02 = high-speed camera)",
    "촉매 / 막": "Catalyst / membrane",
    "음극 j₀ (HER)": "Cathode j₀ (HER)",
    "양극 겉보기 j₀ (피팅값)": "Anode apparent j₀ (fitted)",
    "양극 α (Tafel 기울기)": "Anode α (Tafel slope)",
    "양극 이중층 C_dl (EIS 전용)": "Anode double-layer C_dl (EIS only)",
    "음극 이중층 C_dl (EIS 전용)": "Cathode double-layer C_dl (EIS only)",
    "PTL 두께 (3D 형상만)": "PTL thickness (3D geometry only)",
    "음극 건식 (물 투과)": "Dry cathode (water transport)",
    "음극 건식 (양극에만 전해질)": "Dry cathode (anolyte only)",
    "꺼짐 (양쪽 습윤)": "Off (both sides wetted)",
    "켜짐 (건식)": "On (dry cathode)",
    "전기삼투 끌림 n_drag (OH⁻ 1개가 끌고가는 물)": "Electro-osmotic drag n_drag (water per OH⁻)",
    "막 내 물 확산계수": "Water diffusivity in membrane",
    "환경": "Environment",
    "자기장 B (MHD 경험식)": "Magnetic field B (empirical MHD)",
    "DEP 기준 전기장 E": "Reference electric field E for DEP",
    "전기장 구배 길이 (모델)": "Electric-field gradient length (model)",
    "온도": "Temperature",
    "압력": "Pressure",
    "셀 형상 (격자 재생성)": "Cell geometry (rebuild grid)",
    "전극 폭": "Electrode width",
    "전극 높이": "Electrode height",
    "채널 수": "Number of channels",
    "채널 폭": "Channel width",
    "채널 깊이 (기포 크기 상한)": "Channel depth (bubble-size limit)",
    "리브 폭": "Rib width",
    "복셀 해상도 (작을수록 정밀↑ 속도↓)": "Voxel resolution (smaller = finer and slower)",
    "복셀 한 칸 크기": "Voxel cell size",
    "3D 계산 격자 한 칸의 실제 길이입니다. 작을수록 유로와 분포가 세밀하지만 계산량이 커집니다.": "Physical length of one 3D solver cell. Smaller values resolve the flow field and distributions more finely but cost more computation.",
    "포트 (입구 · 출구)": "Ports (inlet / outlet)",
    "입구 면": "Inlet face",
    "입구 폭 (0 = 형식 기본값)": "Inlet width (0 = preset default)",
    "입구 위치 (그 변을 따라)": "Inlet position along edge",
    "출구 면": "Outlet face",
    "출구 폭 (0=자동, 1=면 전체)": "Outlet width (0 = auto, 1 = full face)",
    "출구 위치 (그 변을 따라)": "Outlet position along edge",
    "아래": "Bottom",
    "왼쪽": "Left",
    "오른쪽": "Right",
    "위": "Top",
    "사행": "Serpentine",
    "세로 사행": "Vertical serpentine",
    "병렬": "Parallel",
    "교차": "Interdigitated",
    "직접": "Custom",
    "표시 (이 화면 전용)": "Display (this view only)",
    "3D 버블 표시": "3D bubble view",
    "이동 보기": "Movement",
    "분포 보기": "Distribution",
    "분포+경로": "Distribution + paths",
    "이동 보기는 부착 기포와 계속 흐르는 트레이서만 표시합니다. 분포 보기는 통계적 대표 표본을 표시합니다.": "Movement shows attached bubbles and continuously moving tracers. Distribution shows the statistical representative sample.",
    "전극면 전류맵": "Electrode-surface current map",
    "켜기": "On",
    "끄기": "Off",
    "버블 색": "Bubble color",
    "색상 기준": "Color by",
    "기체 종류": "Gas species",
    "상승속도": "Rise velocity",
    "기포 이동속도": "Bubble velocity",
    "기포 이동속도 |uᵦ|": "Bubble velocity |uᵦ|",
    "기포가 3D 공간에서 이동하는 전체 속도입니다. 액체 유동과 부력 미끄럼을 함께 포함합니다.": "Total bubble speed in 3D, including liquid advection and buoyant slip.",
    "버블 표시 크기 (물리 크기는 실제)": "Displayed bubble size (physics uses actual size)",
    "분포·부착 버블 표시 크기 (물리는 실제)": "Distribution/attached bubble size (physics uses actual size)",
    "이동 트레이서는 유로를 가리지 않도록 실제 크기 기준의 작은 경로 마커로 표시합니다.": "Moving tracers use small, near-physical-size path markers so they do not obscure the channels.",
    "버블 표시 배율": "Bubble display scale",
    "부착·분포·이동 버블에 같은 배율을 적용합니다. ×1이 계산된 실제 크기입니다.": "Applies the same scale to attached, distribution, and moving bubbles. ×1 is the calculated physical size.",
    "실제 ×1": "Actual ×1",
    "3D 표시 버블 수 상한 (0=전체)": "3D displayed bubble limit (0=all)",
    "흐름 궤적 트레이서 개수 (계산된 속도장)": "Flow tracers (computed velocity field)",
    "분포 표본 수 상한 (0=전체)": "Distribution marker limit (0=all)",
    "이동 트레이서 수": "Moving tracer count",
    "이동 트레이서 수 (0=끄기)": "Moving tracer count (0=off)",
    "이동 보기와 분포+경로에서 표시합니다. 계산된 액체 속도장과 크기별 부력 미끄럼을 사용합니다.": "Shown in Movement and Distribution + paths. Uses the solved liquid velocity field and radius-dependent buoyant slip.",
    "부착 기포가 이탈하면 같은 위치에서 이동 경로로 이어집니다. 계산된 액체 속도장과 크기별 부력 미끄럼을 사용하며, 전체 실제 기포를 1:1 추적하는 표시는 아닙니다.": "When an attached bubble detaches, its path continues from the same position. Paths use the solved liquid velocity and radius-dependent buoyant slip; they are representative, not one-to-one tracking of every real bubble.",
    "화면에 표시한 부착 대표 마커는 이탈 시 같은 위치에서 이동 경로로 이어집니다. 이동 슬롯 수 안에서 대표 경로만 표시합니다.": "Each displayed attached marker continues from the same position when it detaches. Only representative paths within the selected moving-marker capacity are shown.",
    "0~5,000개의 화면용 대표 경로를 선택합니다. 계산 기포 수는 바뀌지 않으며, 많은 수는 기기 성능에 따라 프레임 속도가 낮아질 수 있습니다.": "Select 0–5,000 representative on-screen paths. This does not change the simulated bubble population; high counts may reduce frame rate depending on the device.",
    "유로": "Flow field",
    "유로 형식": "Flow-field type",
    "유로 직접 그리기 — 크게 보기": "Draw flow field — expanded view",
    "유로 — 템플릿 & 직접 그리기": "Flow field — templates and custom drawing",
    "유로 설계": "Flow-field design",
    "선택 후 수정 가능": "Choose, then edit",
    "그리기 도구": "Drawing tools",
    "한 칸 = 계산 복셀": "One cell = one solver voxel",
    "✏ 큰 화면에서 유로 그리기": "✏ Draw flow field in large view",
    "유로 그리기": "Draw flow field",
    "적용 완료": "Apply and close",
    "요청값은 복셀 단위로 반올림됩니다.": "Requested sizes are rounded to voxel units.",
    "⚠ 입구–출구가 연결되지 않았습니다.": "⚠ Inlet and outlet are not connected.",
    "입구 폭 0: 전체 면 급수": "Inlet width 0: full-face feed",
    "유로 바꿔 비교": "Compare flow fields",
    "유로 벽(리브)": "Flow-field walls (ribs)",
    "다공층(PTL)": "Porous transport layer (PTL)",
    "유로 위치별": "Along the flow path",
    "유로단면_mm2": "flow_field_cross_section_mm2",
    "템플릿": "Template",
    "불러온 뒤 자유롭게 수정": "Load, then edit freely",
    "리브": "Rib",
    "채널": "Channel",
    "주기": "pitch",
    "패스": " passes",
    "한 칸": "one cell",
    "물리격자 그대로": "same as the physics grid",
    "그리면 적용됩니다": "applied as you draw",
    "눌린 채": "Attached",
    "부력 + 국소 유동": "Buoyancy + local flow",
    "위치마다 다릅니다": "varies with position",
    "가로": "horizontal",
    "턴 갭(양 끝)": "turn gaps (both ends)",
    "수직 상승": "vertical rise",
    "합(빨강 화살표)": "resultant (red arrow)",
    "가스": "Gas",
    "액체": "liquid",
    "비율": "ratio",
    "계산영역": "computed domain",
    "요청": "requested",
    "펌프 회로당": "Pump per circuit",
    "개 회로 셀 총량": " circuits, total cell flow",
    "복셀 입구에도 같은 총유량을 보존": "same total flow conserved at the voxel inlet",
    "유량 보존 오차 확인 필요": "flow-conservation error needs checking",
    "직접 그리기": "Custom drawing",
    "직선": "Line",
    "사각형": "Rectangle",
    "붓": "Brush",
    "지우개": "Eraser",
    "굵기": "Width",
    "좌우대칭": "Mirror left/right",
    "↶ 되돌리기": "↶ Undo",
    "↷ 다시": "↷ Redo",
    "⤢ 크게": "⤢ Expand",
    "현재 유로 불러오기": "Load current flow field",
    "비우기": "Clear",
    "반전": "Invert",
    "지그재그": "Zigzag",
    "핀 (엇갈림)": "Pins (staggered)",
    "핀 (정렬)": "Pins (aligned)",
    "나선": "Spiral",
    "빈 판": "Open plate",
    "기포": "Bubbles",
    "발생 (Faraday)": "Gas generation (Faraday)",
    "발생량은": "The generated gas amount is",
    "협상 불가": "fixed by Faraday's law",
    "발생 = 잔류 + 배출": "generation = retained + vented",
    "1개 소비": "1 molecule consumed",
    "활성화 과전압 (Butler–Volmer, 전극별)": "Activation overpotential (Butler–Volmer, each electrode)",
    "농도 과전압 · 옴 손실": "Concentration overpotential and ohmic loss",
    "벽면 수직 이동 (Tomiyama 양력 vs Antal 벽윤활)": "Wall-normal migration (Tomiyama lift vs Antal wall lubrication)",
    "양력계수가 양수": "lift coefficient is positive",
    "벽으로 밀려갑니다": "they migrate toward the wall",
    "물리적으로 설명": "physically explained",
    "합체 (Prince–Blanch)": "Coalescence (Prince–Blanch)",
    "기체 과충전 셀": "Gas-overfilled cells:",
    "개 (분산기포 모델 범위 초과)": " (dispersed-bubble model out of range)",
    "농전해질(KOH > 0.3 M)은": "Concentrated electrolyte (KOH > 0.3 M)",
    "으로 막배수를 막아 합체를 억제 — 그래서 6 M KOH에서는 기포가 잘 안 합쳐집니다.": "suppresses film drainage through salting-out, so bubbles coalesce less readily in 6 M KOH.",
    "기포 막힘 형상": "Bubble blockage pattern",
    "무유동 이탈직경 (실측 입력)": "Zero-flow departure diameter (measured input)",
    "펌프 유동이 없을 때 해당 전극에서 측정한 단일 기포 이탈직경입니다. 기존의 임의 Fritz 배율 대신 사용하며, 미측정 기본값 244 µm는 정량 예측값이 아닙니다.": "Single-bubble departure diameter measured on this electrode without pumped flow. It replaces the arbitrary Fritz multiplier; the unmeasured 244 µm default is not a quantitative prediction.",
    "이탈 크기 (힘 평형)": "Detachment size (force balance)",
    "반-Lagrangian 이류, red-black SOR": "Semi-Lagrangian advection, red-black SOR",
    "막 두께 (건식 음극 물수송·형상)": "Membrane thickness (dry-cathode water transport and geometry)",
    "막·접촉 면저항 (피팅값)": "Membrane/contact area resistance (fitted)",
    "전해질 갭 (모델 관례, r_mem과 짝)": "Electrolyte gap (model convention, paired with r_mem)",
    "영어": "English",
    "한국어": "한국어",
    "슬라이더": "slider",
    "개": "",
    "실제": "actual",
    "단면": "section",
    "슬랩 내": "in slab",
    "패널 접기 또는 펼치기": "Collapse or expand panel",
    "접기": "Collapse",
    "펼치기": "Expand",
    "1개≈": "1 marker ≈ ",
    "개 실제": " actual bubbles",
    "연결됨 · 라이브": "Connected · Live",
    "서버 연결 끊김": "Server disconnected",
    "서버": "Server",
    "작동점 V · j": "Operating point V · j",
    "sim 시간": "Simulation time",
    "격자": "Grid",
    "모델 유효성": "Model validity",
    "버블 수 (표시/실제)": "Bubble count (displayed/actual)",
    "부착 대표 마커": "Attached representative markers",
    "자유 분포 표본": "Free-bubble distribution sample",
    "이동 트레이서": "Moving tracers",
    "실제 기포 추정": "Estimated real bubbles",
    "전극 부착·성장": "Attached/growing on electrode",
    "이탈·이동": "Detached/moving",
    "이탈 반경 r_dep": "Detachment radius r_dep",
    "전류 불균일 (음/양극)": "Current nonuniformity (cathode/anode)",
    "속도 (×실시간)": "Speed (× real time)",
    "범위 내 · 표면반응 모델": "Within range · surface-reaction model",
    "휠 줌": "Wheel zoom",
    "좌우 이동": "Horizontal pan",
    "축소": "Zoom out",
    "확대": "Zoom in",
    "⏸ 정지": "⏸ Pause",
    "⌖ 시점": "⌖ Reset view",
    "🧹 패널 정렬": "🧹 Arrange panels",
  });

  const hasKorean = s => /[\uac00-\ud7a3]/.test(s);
  const norm = s => String(s == null ? "" : s).replace(/\s+/g, " ").trim();
  const fragments = Object.entries(catalog)
    .filter(([ko]) => hasKorean(ko) && ko.length >= 2 && ko.length <= 180)
    .sort((a, b) => b[0].length - a[0].length);

  let language = "ko";
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "ko") language = saved;
  } catch (_) {}

  function polish(source, translated) {
    let out = translated;
    if (/유로/.test(source)) {
      out = out
        .replace(/\bEuropath\b/gi, "flow path")
        .replace(/\bEuros\b/g, "flow fields")
        .replace(/\beuros\b/g, "flow fields")
        .replace(/\bEuro\b/g, "Flow field")
        .replace(/\beuro\b/g, "flow field");
    }
    if (/기포/.test(source))
      out = out.replace(/\bair bubbles?\b/gi, m => /s$/i.test(m) ? "bubbles" : "bubble");
    if (/이탈/.test(source))
      out = out.replace(/\bescape(d)? bubble(s)?\b/gi, (_, ed, plural) =>
        `detach${ed ? "ed" : "ment"} bubble${plural || ""}`);
    if (/막/.test(source))
      out = out.replace(/\bfilm\b/gi, "membrane");
    return out;
  }

  function translate(source) {
    const key = norm(source);
    if (!key || language !== "en") return key;
    if (Object.prototype.hasOwnProperty.call(catalog, key))
      return polish(key, catalog[key]);
    if (!hasKorean(key)) return key;

    let out = key;
    for (const [ko, en] of fragments)
      if (out.includes(ko)) out = out.split(ko).join(en);
    return polish(key, out);
  }

  const originalText = new WeakMap();
  const writtenText = new WeakMap();
  const originalAttrs = new WeakMap();
  const writtenAttrs = new WeakMap();
  const ATTRS = ["title", "placeholder", "aria-label"];

  function splitWhitespace(raw) {
    const lead = (raw.match(/^\s*/) || [""])[0];
    const trail = (raw.match(/\s*$/) || [""])[0];
    return [lead, raw.slice(lead.length, raw.length - trail.length), trail];
  }

  function writeText(node, value) {
    if (node.nodeValue === value) return;
    writtenText.set(node, value);
    node.nodeValue = value;
  }

  function translateTextNode(node, refreshSource) {
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const parent = node.parentElement;
    if (!parent || parent.closest("[data-i18n-skip],script,style")) return;
    if (refreshSource || !originalText.has(node)) originalText.set(node, node.nodeValue || "");
    const raw = originalText.get(node);
    if (language === "ko") {
      writeText(node, raw);
      return;
    }
    const [lead, core, trail] = splitWhitespace(raw);
    const clean = norm(core);
    writeText(node, clean ? lead + translate(clean) + trail : raw);
  }

  function attrStore(el) {
    if (!originalAttrs.has(el)) originalAttrs.set(el, {});
    if (!writtenAttrs.has(el)) writtenAttrs.set(el, {});
    return [originalAttrs.get(el), writtenAttrs.get(el)];
  }

  function writeAttr(el, name, value, written) {
    if (el.getAttribute(name) === value) return;
    written[name] = value;
    el.setAttribute(name, value);
  }

  function translateAttrs(el, refreshName) {
    if (!(el instanceof Element) || el.closest("[data-i18n-skip]")) return;
    const [original, written] = attrStore(el);
    for (const name of ATTRS) {
      if (!el.hasAttribute(name)) continue;
      if (!Object.prototype.hasOwnProperty.call(original, name) || refreshName === name)
        original[name] = el.getAttribute(name);
      const source = original[name];
      writeAttr(el, name, language === "en" ? translate(source) : source, written);
    }
  }

  function apply(root) {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) {
      translateTextNode(root, false);
      return;
    }
    if (!(root instanceof Element) && root !== document) return;
    if (root instanceof Element) translateAttrs(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === Node.TEXT_NODE) translateTextNode(node, false);
      else translateAttrs(node);
    }
  }

  function updateToggle() {
    document.querySelectorAll("[data-language]").forEach(button => {
      const on = button.dataset.language === language;
      button.classList.toggle("on", on);
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function setLanguage(next) {
    if (next !== "ko" && next !== "en") return;
    language = next;
    try { localStorage.setItem(STORAGE_KEY, language); } catch (_) {}
    document.documentElement.lang = language;
    apply(document);
    updateToggle();
    document.dispatchEvent(new CustomEvent("sim-language-change", { detail:{ language } }));
  }

  function installCanvasTranslation() {
    const p = g.CanvasRenderingContext2D && g.CanvasRenderingContext2D.prototype;
    if (!p || p.__simI18nPatched) return;
    p.__simI18nPatched = true;
    for (const name of ["fillText", "strokeText", "measureText"]) {
      const native = p[name];
      if (typeof native !== "function") continue;
      p[name] = function (text, ...args) {
        const value = language === "en" ? translate(String(text)) : text;
        return native.call(this, value, ...args);
      };
    }
  }

  function installDialogs() {
    if (g.__simI18nDialogs) return;
    g.__simI18nDialogs = true;
    if (typeof g.alert === "function") {
      const native = g.alert.bind(g);
      g.alert = message => native(language === "en" ? translate(String(message)) : message);
    }
    if (typeof g.confirm === "function") {
      const native = g.confirm.bind(g);
      g.confirm = message => native(language === "en" ? translate(String(message)) : message);
    }
  }

  function start() {
    document.documentElement.lang = language;
    installCanvasTranslation();
    installDialogs();
    document.querySelectorAll("[data-language]").forEach(button => {
      button.addEventListener("click", () => setLanguage(button.dataset.language));
    });
    apply(document);
    updateToggle();

    const observer = new MutationObserver(records => {
      for (const record of records) {
        if (record.type === "childList") {
          record.addedNodes.forEach(node => apply(node));
        } else if (record.type === "characterData") {
          const node = record.target;
          if (writtenText.get(node) === node.nodeValue) {
            writtenText.delete(node);
          } else {
            translateTextNode(node, true);
          }
        } else if (record.type === "attributes") {
          const el = record.target, name = record.attributeName;
          const [, written] = attrStore(el);
          if (written[name] === el.getAttribute(name)) {
            delete written[name];
          } else {
            translateAttrs(el, name);
          }
        }
      }
    });
    observer.observe(document.documentElement, {
      subtree:true, childList:true, characterData:true,
      attributes:true, attributeFilter:ATTRS,
    });
  }

  g.SimI18n = {
    getLanguage: () => language,
    setLanguage,
    translate: source => language === "en" ? translate(source) : norm(source),
    apply,
    catalog,
  };

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", start, { once:true });
  else
    start();
})(window);
