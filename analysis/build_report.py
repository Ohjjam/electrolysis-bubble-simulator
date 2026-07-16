# -*- coding: utf-8 -*-
"""Legacy v1 report source retained for traceability.

Direct execution now builds the canonical v2 report artifact instead.  The old
body below is not used by the v2 workflow because it contains the retired
``wick/L_ref/C_*`` formulation.
"""
import json
import html
from pathlib import Path

if __name__ == "__main__":
    from build_mesh_v2_artifact import main as _build_v2
    _build_v2()
    raise SystemExit

OUT = Path(__file__).resolve().parent / "out"
FIG = OUT / "figs"
S = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
NAR = {}
p = OUT / "narrative.json"
if p.exists():
    NAR = json.loads(p.read_text(encoding="utf-8"))

SYN = NAR.get("synth", {})
CRIT = NAR.get("critic", {})
ANA = {a["ax"]: a for a in NAR.get("analyses", [])}

DEC = {}
pd = OUT / "decomp.json"
if pd.exists():
    DEC = json.loads(pd.read_text(encoding="utf-8"))
M2D = json.loads((OUT / "mesh_2d.json").read_text(encoding="utf-8")) if (OUT / "mesh_2d.json").exists() else {}
LEXT = json.loads((OUT / "lambda_ext.json").read_text(encoding="utf-8")) if (OUT / "lambda_ext.json").exists() else {}
FOAM = json.loads((OUT / "foam_model.json").read_text(encoding="utf-8")) if (OUT / "foam_model.json").exists() else {}


def esc(x):
    return html.escape(str(x))


def paras(txt):
    if not txt:
        return ""
    return "".join(f"<p>{esc(t.strip())}</p>" for t in str(txt).split("\n") if t.strip())


def svg(name):
    f = FIG / name
    if not f.exists():
        return f"<em>[missing {name}]</em>"
    s = f.read_text(encoding="utf-8")
    i = s.find("<svg")
    return s[i:] if i >= 0 else s


def figure(name, num, cap, note=""):
    note_html = f'<div class="fig-note">{esc(note)}</div>' if note else ""
    return (f'<figure class="fig"><div class="fig-body">{svg(name)}</div>'
            f'<figcaption><span class="fig-n">그림 {num}</span> {esc(cap)}{note_html}'
            f'</figcaption></figure>')


def table(headers, rows, highlight=None, aligns=None, foot=None):
    aligns = aligns or ["left"] * len(headers)
    th = "".join(f'<th class="a-{a}">{esc(h)}</th>' for h, a in zip(headers, aligns))
    trs = []
    for i, r in enumerate(rows):
        cls = ' class="hi"' if highlight is not None and highlight(r, i) else ""
        tds = "".join(f'<td class="a-{a}">{c}</td>' for c, a in zip(r, aligns))
        trs.append(f"<tr{cls}>{tds}</tr>")
    footh = f"<tfoot><tr>{foot}</tr></tfoot>" if foot else ""
    return (f'<div class="tw"><table><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(trs)}</tbody>{footh}</table></div>')


def chip(txt, kind="n"):
    return f'<span class="chip c-{kind}">{esc(txt)}</span>'


def dv_chip(v):
    if v is None or v == "":
        return "—"
    v = float(v)
    k = "good" if v > 0 else ("bad" if v < 0 else "n")
    return f'<span class="chip c-{k}">{("+" if v>0 else "")}{v:g} mV</span>'


def analysis_block(ax):
    a = ANA.get(ax)
    if not a:
        return ""
    parts = [f'<p class="lead">{esc(a["headline"])}</p>']
    if a.get("mechanism"):
        parts.append(f'<p><span class="ilabel">메커니즘</span>{esc(a["mechanism"])}</p>')
    if a.get("practical"):
        parts.append(f'<p><span class="ilabel">실용 함의</span>{esc(a["practical"])}</p>')
    if a.get("caveats"):
        lis = "".join(f"<li>{esc(c)}</li>" for c in a["caveats"])
        parts.append(f'<div class="cav"><div class="cav-h">주의 / 한계</div><ul>{lis}</ul></div>')
    return "".join(parts)


# ------------------------------------------------------------------- tables
def tbl_catalog():
    t = sorted(S["axes"]["catalog"]["table"],
               key=lambda r: (not r["fits"], -(r["dV@1000_mV"] or -1e9)))
    best = max((r for r in t if r["fits"]), key=lambda r: (r["dV@1000_mV"] or -1e9))
    rows = []
    for r in t:
        fit = chip("장착가능", "good") if r["fits"] else chip("장착불가 t≥d_ch", "muted")
        warn = ' <span class="warn">⚠ dP</span>' if (r.get("mesh_warn") or "") else ""
        rows.append([
            f'<code>{esc(r["id"].replace("pp_",""))}</code>',
            fit,
            f'{r["hole_mm"]:.2f}', f'{int(r["open"]*100)}%', f'{r["t_mm"]:.2f}',
            f'{r["V@1000mV"]:.0f}' + warn,
            dv_chip(r["dV@1000_mV"]),
        ])
    return table(
        ["메시", "장착", "개구 mm", "φ", "두께 mm", "V@1000 mV", "ΔV@1000"],
        rows, highlight=lambda r, i: r[0].find(best["id"].replace("pp_", "")) >= 0,
        aligns=["left", "left", "right", "right", "right", "right", "right"])


def tbl_coverage():
    t = S["axes"]["coverage"]["table"]
    rows = []
    for r in t:
        if r["cover"] == 0:
            continue
        rows.append([
            chip(r["pos"], {"outlet": "good", "middle": "n", "inlet": "bad"}[r["pos"]]),
            f'{int(r["cover"]*100)}%',
            f'{r["V@1000mV"]:.0f}',
            dv_chip(r["dV@1000_mV"]),
            f'{r["theta_out@jmax"]:.3f}',
        ])
    return table(["위치", "피복률", "V@1000 mV", "ΔV@1000", "θ_out(2250)"],
                 rows, aligns=["left", "right", "right", "right", "right"],
                 highlight=lambda r, i: "outlet" in r[0] and "50%" in r[1])


def tbl_flow():
    t = sorted(S["axes"]["flow"]["table"], key=lambda r: r["mL_min"])
    rows = []
    for r in t:
        rows.append([
            f'{r["mL_min"]:.1f}' + (' <span class="warn">◀ 실측</span>' if abs(r["mL_min"]-4.0) < 0.3 else ""),
            f'{r["u_flow_ms"]:.3f}',
            f'{r["pris_V@1000"]:.0f}', f'{r["mesh_V@1000"]:.0f}',
            dv_chip(r["dV@1000_mV"]),
        ])
    return table(["펌프 mL/min", "u m/s", "pristine V@1000", "+메시 V@1000", "ΔV@1000"],
                 rows, aligns=["right", "right", "right", "right", "right"],
                 highlight=lambda r, i: "실측" in r[0])


def tbl_eis():
    t = S["axes"]["eis"]["table"]
    rows = [[esc(r["variant"]), f'{r["Rs"]:.3f}', f'{r["Rct_tot"]:.3f}', f'{r["theta_mean"]:.3f}'] for r in t]
    return table(["케이스", "R_s Ω·cm²", "R_ct(합) Ω·cm²", "θ̄(500)"],
                 rows, aligns=["left", "right", "right", "right"],
                 highlight=lambda r, i: i == 0)


def tbl_generic(axkey, xlabel, xfmt):
    t = S["axes"][axkey]["table"]
    rows = []
    for r in t:
        xv = xfmt(r)
        rows.append([xv, f'{r["V@500mV"]:.0f}', f'{r["V@1000mV"]:.0f}',
                     dv_chip(r["dV@1000_mV"]),
                     f'{r.get("theta_mean@jmax",0):.3f}',
                     (esc(r.get("mesh_warn")) if r.get("mesh_warn") else "")])
    return table([xlabel, "V@500 mV", "V@1000 mV", "ΔV@1000", "θ̄(2250)", "경고"],
                 rows, aligns=["right", "right", "right", "right", "right", "left"])


# ------------------------------------------------------------------- sections
def kf_list():
    items = SYN.get("key_findings") or []
    if not items:
        return ""
    lis = "".join(f"<li>{esc(x)}</li>" for x in items)
    return f'<ol class="kf">{lis}</ol>'


def overclaim_block():
    ocs = CRIT.get("overclaims") or []
    if not ocs:
        return ""
    rows = "".join(
        f'<div class="oc"><div class="oc-claim">✕ {esc(o["claim"])}</div>'
        f'<div class="oc-fix"><b>바로잡음:</b> {esc(o["fix"])}</div></div>'
        for o in ocs)
    return f'<div class="ocs"><div class="ocs-h">우리가 피한 과대해석</div>{rows}</div>'


def limitations_list():
    lims = CRIT.get("limitations") or []
    return "".join(f"<li>{esc(x)}</li>" for x in lims)


D0 = S["baseline"]
meta_bits = [
    ("셀", f'{D0["W_cm"]}×{D0["H_cm"]} cm · {D0["n_ch"]}ch 사행'),
    ("유로", f'{D0["w_ch_mm"]}/{D0["d_ch_mm"]} mm (폭/깊이)'),
    ("전해질", f'{D0["c_mol"]} M KOH · {D0["T"]}°C'),
    ("운전", f'{S["axes"]["flow"]["table"][2]["mL_min"]:.0f} mL/min · dry-cathode AEM'),
    ("모델", 'channel + meshlayer (블라인드)'),
    ("캘리브", f'pristine RMSE {S["pristine"]["calib_RMSE_mV"]} mV'),
]
meta_html = "".join(
    f'<div class="mrow"><span class="mk">{esc(k)}</span><span class="mv">{esc(v)}</span></div>'
    for k, v in meta_bits)

TITLE = SYN.get("title") or "기포 관리 메시 파라미터 스터디 — AEM 수전해 셀"

# fallbacks so a dry build still renders
ABSTRACT = SYN.get("abstract") or (
    "캘리브레이션된 1-D 채널 병목 모델로 소수성 PP 기포관리 메시의 두께·개구율·기공·"
    "가린면적·유속을 스윕하여 LSV·EIS·효율을 비교했다. 블라인드 프로토콜(메시 실측 무보정).")

# ================= WHY it improves (mechanism decomposition) ==============
_d1 = (DEC.get("decomp") or {}).get("1000", {})
_steps = _d1.get("steps_mV", {})
_fac = DEC.get("factors", {})
_peel = _steps.get("떼어냄 (촉매 피복 완화)", 0.0)
_drain = _steps.get("밀어냄 · 그물 배수", 0.0)
_flowc = _steps.get("밀어냄 · 유속 부스트", 0.0)
_push = _drain + _flowc
_block = _steps.get("차단 (액 접근 막힘, 손해)", 0.0)
_net = _d1.get("net_mV", 0.0)
_thp, _thm = _d1.get("theta_pristine"), _d1.get("theta_mesh")
_epp, _epm = _d1.get("eps_out_pristine"), _d1.get("eps_out_mesh")

# ---- worked-calculation boxes (the numbers, plugged in, step by step) ----
import math as _math
_Lh = _fac.get("hole_mm", 1.181); _phi = _fac.get("open", 0.5); _tm = _fac.get("t_mm", 0.483)
_dch = _fac.get("d_ch_mm", 0.9); _wick = _fac.get("wick", 0.5); _ub = _fac.get("u_boost", 2.16)
_thf = _fac.get("theta_factor", 0.7); _rw = _fac.get("R_wick", 0.75); _rs = _fac.get("R_sweep", 0.681)
_tadd = _fac.get("theta_add", 0.08)
_v0 = _d1.get("V_pristine", 2033.3); _v1 = _v0 - _peel; _v2 = _v1 - _drain
_v3 = _v2 - _flowc; _v4 = _v3 - _block

calc1_html = (
    '<div class="calc"><div class="calc-h">계산 상세 · 그림 1 — 기준 메시 pp_040x053 @ 1000 mA/cm²</div>'
    f'<div class="calc-in"><b>넣은 값 (왜 이 값?):</b> 개구 L<sub>h</sub>={_Lh} mm · 개구율 φ={_phi} · '
    f'두께 t<sub>m</sub>={_tm} mm — <b>실측에 실제로 쓴 메시(pp_040x053)의 치수 그대로</b>. '
    f'유로 깊이 d<sub>ch</sub>={_dch} mm, L<sub>ref</sub>=2.0 mm(실험 전 고정 상수).</div>'
    '<ul class="calc-steps">'
    f'<li><b>① 떼어냄</b> — <span class="eq">wick=(1−φ)·min(1, L<sub>ref</sub>/L<sub>h</sub>)=(1−{_phi})·min(1, 2.0/{_Lh})={_wick}</span> '
    f'→ <span class="eq">θ<sub>factor</sub>=1−0.6·{_wick}={_thf}</span> (피복 진폭을 {round(0.6*_wick*100)}% 깎음) '
    f'<span class="cv">V {_v0:.1f}→{_v1:.1f} ({_peel:+.0f})</span></li>'
    f'<li><b>② 밀어냄 · 그물배수</b> — <span class="eq">R<sub>wick</sub>=1−0.5·{_wick}={_rw}</span> '
    f'(피복 구간 홀드업을 {round(_rw*100)}%로) <span class="cv">V {_v1:.1f}→{_v2:.1f} ({_drain:+.0f})</span></li>'
    f'<li><b>② 밀어냄 · 유속부스트</b> — <span class="eq">u<sub>boost</sub>=d<sub>ch</sub>/(d<sub>ch</sub>−t<sub>m</sub>)={_dch}/({_dch}−{_tm})={_ub}</span>, '
    f'<span class="eq">R<sub>sweep</sub>=1/√{_ub}={_rs}</span> (물살 {_ub}배 빨라짐) <span class="cv">V {_v2:.1f}→{_v3:.1f} ({_flowc:+.0f})</span></li>'
    f'<li><b>③ 차단</b> — <span class="eq">θ<sub>add</sub>=0.3·(1−φ)·(t<sub>m</sub>/d<sub>ch</sub>)=0.3·{round(1-_phi,2)}·({_tm}/{_dch})={_tadd}</span> '
    f'(피복 바닥값 +{_tadd} 추가 = 손해) <span class="cv">V {_v3:.1f}→{_v4:.1f} ({_block:+.0f})</span></li>'
    '</ul>'
    f'<div class="calc-out">→ 합계: {_v0:.1f} − {_v4:.1f} = 순 <b>{_net:.0f} mV 절감</b> · 피복률 θ {_thp}→{_thm} '
    f'(이 θ가 어떻게 나오는지는 §3·그림 4)</div></div>')

_pf = DEC.get("profiles_1000", {})
_epP = ((_pf.get("pristine") or {}).get("eps") or [0.85])[-1]
_thP = ((_pf.get("pristine") or {}).get("theta") or [0.83])[-1]
_epM = ((_pf.get("mesh") or {}).get("eps") or [0.44])[-1]
_thM = ((_pf.get("mesh") or {}).get("theta") or [0.54])[-1]
_xP = 1 - _math.exp(-3 * _epP)
_xM = 0.9 * _thf * (1 - _math.exp(-3 * _epM))

calc4_html = (
    '<div class="calc"><div class="calc-h">계산 상세 · 그림 4 — 피복 프로파일 θ(s) @ 1000 mA/cm²</div>'
    '<div class="calc-in"><b>왜 출구가 병목?</b> 가스는 하류로 누적한다: '
    '<span class="eq">V<sub>gas</sub>/Q = K·∫<sub>0</sub><sup>s</sup> j ds′, &nbsp;K=(RT/P)/(zF·u·d<sub>ch</sub>)</span> '
    '— 입구(∫ 작음)→출구(∫ 큼)라 홀드업 ε이 단조 증가. '
    '넣은 값: T=338 K · P=1 bar · z=4(O₂) · u=0.0842 m/s · d<sub>ch</sub>=0.9 mm.</div>'
    '<ul class="calc-steps">'
    '<li><b>ε→θ 변환식</b> (Vogt–Balzer): <span class="eq">θ(s)=θ<sub>max</sub>·(1−e<sup>−k·ε</sup>)+θ<sub>add</sub></span> '
    '(θ<sub>max</sub>=0.9, k=3; 메시가 있으면 θ<sub>max</sub>→0.9·θ<sub>factor</sub>=0.63)</li>'
    f'<li><b>출구 · pristine</b> (ε={_epP:.3f}): '
    f'<span class="eq">θ=0.9·(1−e<sup>−3·{_epP:.3f}</sup>)=0.9·{_xP:.3f}={_thP:.3f}</span> → 출구 {round(_thP*100)}% 덮임</li>'
    f'<li><b>출구 · 메시</b> (ε={_epM:.3f}): '
    f'<span class="eq">θ=0.63·(1−e<sup>−3·{_epM:.3f}</sup>)+{_tadd}={_xM:.3f}+{_tadd}={_thM:.3f}</span> → 출구 {round(_thM*100)}%</li>'
    '</ul>'
    f'<div class="calc-out">→ 메시가 출구 병목을 θ {round(_thP*100)}%→{round(_thM*100)}%로 완화(그림 4 초록 음영). '
    f'식이 그림의 출구 값과 정확히 일치.</div></div>')


def mech_cards():
    if not _d1:
        return ""
    return (
        '<div class="mech">'
        f'<div class="mech-card good"><div class="mc-h">① 떼어냄 <span>peel-off</span></div>'
        f'<div class="mc-v">{_peel:+.0f} mV</div>'
        f'<div class="mc-d">소수성 그물 가닥이 기포를 <b>촉매 벽에서 걷어냄</b> → 촉매를 덮는 피복률 θ의 진폭이 30% 낮아짐. '
        f'<span class="mc-t">모델 항: theta_factor {_fac.get("theta_factor")}</span></div></div>'
        f'<div class="mech-card good"><div class="mc-h">② 밀어냄 <span>sweep-out</span></div>'
        f'<div class="mc-v">{_push:+.0f} mV</div>'
        f'<div class="mc-d">가닥 배수 + 좁아진 유로의 <b>빠른 물살(×{_fac.get("u_boost")})</b>이 기포를 하류로 쓸어냄 → '
        f'유로 속 기포 홀드업 ε 절감. <span class="mc-t">그물배수 {_drain:+.0f} · 유속부스트 {_flowc:+.0f}</span></div></div>'
        f'<div class="mech-card bad"><div class="mc-h">③ 차단 <span>blocking</span></div>'
        f'<div class="mc-v">{_block:+.0f} mV</div>'
        f'<div class="mc-d">가닥이 촉매면의 절반을 가리고 전해질을 밀어내 <b>액이 촉매에 닿는 길을 조금 막음</b>(손해). '
        f'<span class="mc-t">피복 바닥값 +{_fac.get("theta_add")}</span></div></div>'
        '</div>'
        f'<div class="mech-net">순이득 = ①{_peel:+.0f} + ②{_push:+.0f} − ③{abs(_block):.0f} = '
        f'<b>{_net:.0f} mV 절감</b> (1000 mA/cm²) · 피복률 θ {_thp}→{_thm}, 홀드업 ε {_epp}→{_epm}</div>')


why_body = (
    f'<p class="lead">메시를 넣으면 왜 전압이 내려가나? 모델이 계산하는 세 가지 물리 작용으로 정확히 쪼개면, '
    f'1000 mA/cm²에서 순 {_net:.0f} mV 절감은 <b>[떼어냄 {_peel:+.0f}] + [밀어냄 {_push:+.0f}] − [차단 {abs(_block):.0f}]</b>으로 나온다.</p>'
    f'{mech_cards()}'
    f'<p>세 작용은 서로 다른 물리다. <b>떼어냄</b>은 소수성 그물이 기포를 촉매 표면에서 떼어내 반응할 자리를 되찾는 것이고'
    f'(피복률 θ↓), <b>밀어냄</b>은 기포를 유로 밖으로 배출해 전해질 이온이 지나갈 길을 되찾는 것이다(홀드업 ε↓). '
    f'<b>차단</b>은 그물 자체가 액 접근을 막는 손해다. 이득(①+②)이 손해(③)를 크게 이겨서 순 {_net:.0f} mV가 절감된다.</p>'
    f'<p>중요한 것은 <b>전류가 높을수록 밀어냄이 폭발적으로 커진다</b>는 점이다(그림 2). 기포가 많이 쌓이는 고전류에서는 '
    f'유로가 심하게 막히므로, 기포를 쓸어내는 효과가 압도적이 된다 — 2000 mA/cm²에서 밀어냄만 약 287 mV.</p>'
    + figure("fig_mechanism.svg", 1,
             "전압 워터폴 — pristine에서 시작해 세 작용을 하나씩 켜며 전압이 어떻게 내려가는지(초록=절감, 빨강=손해).",
             "기준 메시 pp_040x053(개구 L_h 1.18 mm · 개구율 φ 50% · 두께 t_m 0.48 mm, 유로 100% 출구 피복), "
             "전류밀도 1000 mA/cm². 누적 귀속이라 순서에 따라 ②의 두 갈래 배분은 달라질 수 있으나 합계는 불변.")
    + figure("fig_mechanism_j.svg", 2,
             "전류밀도별 세 작용의 기여(기준 메시 pp_040x053). 고전류로 갈수록 '밀어냄(홀드업 배출)'이 지배적.")
    + calc1_html
)

overpot_body = (
    f'<p class="lead">같은 이야기를 "셀 전압이 어디로 새는가"로 봐도 똑같이 나온다 — 메시는 딱 <b>두 곳의 손실만</b> 깎는다.</p>'
    f'<p>1000 mA/cm²에서 pristine 셀전압 2033 mV는 열역학 최소(E_rev 1187) 위에 여러 과전압(손실 전압)이 쌓인 것이다. '
    f'메시가 줄이는 것은 정확히: <b>음극 기포 피복 손실</b> 89→39 mV(−47, = 떼어냄에 대응)와 '
    f'<b>옴 기포-공극 손실</b> 53→0 mV(−53, = 밀어냄에 대응). 두 개를 합치면 그대로 순 99 mV다. '
    f'나머지 손실(열역학·양극 반응·막·물 공급)은 <b>메시가 손대지 못한다</b> — 메시는 기포 문제만 푸는 도구지, '
    f'촉매나 막을 바꾸는 게 아니다.</p>'
    + figure("fig_overpot.svg", 3,
             "셀 전압 분해(기준 메시 pp_040x053, 1000 mA/cm²) pristine vs 메시. 줄어드는 건 음극 기포피복·옴 기포공극 두 항뿐.",
             "각 막대 길이의 합 = 실제 셀전압. η_bub_cov는 음극활성화 안에, η_bub_void는 옴저항 안에 포함된 성분.")
)

profile_body = (
    f'<p class="lead">완화가 유로의 <b>어디에서</b> 일어나나 — 기포는 입구→출구로 쌓이므로 출구가 병목이고, 메시는 그 병목을 집중적으로 푼다.</p>'
    f'<p>pristine은 입구(기포 적음)에서 출구(기포 많음)로 갈수록 피복률 θ와 홀드업 ε이 단조 증가한다(출구가 가장 막힘). '
    f'메시는 경로 전체에서 θ·ε을 끌어내리되, 절대 완화폭은 병목인 출구쪽에서 가장 크다. '
    f'이것이 부분 피복이라면 <b>출구를 덮는 게 유리한 이유</b>다(§10).</p>'
    + figure("fig_profile.svg", 4,
             "유로 경로를 따른 피복률 θ(좌)·홀드업 ε(우), pristine vs 메시(기준 pp_040x053, 1000 mA/cm²). 초록 음영 = 메시가 완화한 양.")
    + calc4_html
)

SECTIONS = [
    dict(n=1, id="why", t="왜 좋아지는가 — 세 가지 작용", body=why_body, fig=""),
    dict(n=2, id="overpot", t="어느 손실이 줄었나 — 전압 분해", body=overpot_body, fig=""),
    dict(n=3, id="profile", t="유로 어디에서 완화되나", body=profile_body, fig=""),
    dict(n=4, id="calib", t="캘리브레이션 & 방법 (모델을 어떻게 믿나)",
         fig=figure("fig_calib.svg", 5,
                    "측정된 pristine 분극곡선(점)과 캘리브레이션된 모델(선). 16점 RMSE "
                    f'{S["pristine"]["calib_RMSE_mV"]} mV.',
                    "메시 곡선은 이 pristine 보정만으로 기하구조에서 예측한다 — 메시 실측은 모델에 넣지 않음(블라인드)."),
         body=(f'<p>모든 스윕은 실험탭이 쓰는 것과 동일한 채널 병목 솔버'
               f'(<code>bubblesim.solvers.channel</code> + <code>kernel.meshlayer</code>)를 '
               f'기준 셀에서 한 축씩 돌린 것이다. 기준 셀은 {D0["n_ch"]}채널 사행, '
               f'{D0["w_ch_mm"]}/{D0["d_ch_mm"]} mm 유로, {D0["c_mol"]} M KOH {D0["T"]}°C, '
               f'4 mL/min, dry-cathode AEM. 효율 지표는 고정 전류에서의 셀전압 V@500·V@1000 '
               f'(낮을수록 좋음)과 pristine 대비 절감폭 ΔV(+면 메시 이득)이다.</p>'
               + (f'<p class="mut">{esc(CRIT.get("blind_ok"))}</p>' if CRIT.get("blind_ok") else ""))),
    dict(n=5, id="catalog", t="어떤 메시가 가장 효율이 좋은가",
         fig=figure("fig_catalog_lsv.svg", 6, "장착 가능한 실제 PP 메시들의 분극곡선(pristine 파선 대비).") +
             figure("fig_catalog_bar.svg", 7, "메시별 ΔV@1000 (초록=장착가능). 상위권은 촘촘·얇은 메시.",
                    "0.9 mm 유로에는 t≥0.9 mm 메시 4종이 아예 장착 불가."),
         body=analysis_block("catalog") + tbl_catalog()),
    dict(n=6, id="thickness", t="메시 두께 (mesh thickness, t_m)",
         fig=figure("fig_thickness.svg", 8,
                    "두께에 따른 전기적 이득(초록)과 압력강하 프록시 u_boost(빨강).",
                    "얇을수록 dP가 낮다. 이득은 t≈0.6–0.75 mm에서 완만한 정점 후 정체·역전."),
         body=analysis_block("thickness") + tbl_generic("thickness", "두께 mm", lambda r: f'{r["t_mm"]:.2f}')),
    dict(n=7, id="open", t="개구율 (open-area fraction, φ) — 그물의 촘촘함",
         fig=figure("fig_open_pore.svg", 9,
                    "왼쪽: 개구율 φ에 따른 ΔV@1000 (촘촘할수록 위킹↑). 오른쪽: 기공 크기 — 2 mm 이하 등가.",
                    "u_boost는 φ에 무관(두께/깊이에만 의존)."),
         body=analysis_block("open_area") + tbl_generic("open_area", "개구율 φ", lambda r: f'{int(r["open_frac"]*100)}%')),
    dict(n=8, id="pore", t="개구 크기 (opening size, L_h)",
         fig="", body=analysis_block("pore_size") + tbl_generic("pore_size", "개구 L_h mm", lambda r: f'{r["hole_mm"]:.2f}')),
    dict(n=9, id="coverage", t="가린 면적 × 위치 — 사용자의 핵심 질문",
         fig=figure("fig_coverage.svg", 10,
                    "피복률·위치별 ΔV@1000. 부분 피복에서 outlet ≫ middle ≫ inlet.",
                    "이 기본 모델은 100% 전면 피복이 최적 — 실측의 'outlet 50%>100%'는 재현 안 됨(§12). "
                    "니켈폼 λ(x)를 실제 물리로 넣어도 재현 안 됨(§13) — 다른 메커니즘이 필요."),
         body=analysis_block("coverage") + tbl_coverage()),
    dict(n=10, id="flow", t="유속 (펌프 유량)",
         fig=figure("fig_flow.svg", 11,
                    "왼쪽: 유량별 pristine vs 메시 V@1000. 오른쪽: 메시 이득 ΔV — 저유속 질식영역에서 폭발적.",
                    "운전점 4 mL/min에서 ΔV@1000 ≈ 99 mV, 1 mL/min에서는 ≈ 374 mV."),
         body=analysis_block("flow") + tbl_flow()),
    dict(n=11, id="eis", t="EIS 비교",
         fig=figure("fig_eis.svg", 12,
                    "500 mA/cm²에서의 Nyquist. 메시가 R_ct 아크를 축소, R_s 절편은 불변.",
                    S["axes"]["eis"]["note"]),
         body=analysis_block("eis") + tbl_eis()),
]

sections_html = ""
for s in SECTIONS:
    sections_html += (
        f'<section id="{s["id"]}"><div class="sh"><span class="sn">§{s["n"]}</span>'
        f'<h2>{esc(s["t"])}</h2></div>{s["fig"]}{s["body"]}</section>')

# scope / limitations (the honest core)
scope_html = (
    f'<section id="scope" class="scope"><div class="sh"><span class="sn">§12</span>'
    f'<h2>범위와 한계 — 니켈폼 젖음 질문</h2></div>'
    f'<div class="scope-card">'
    f'<div class="scope-h">이 시뮬이 하는 것 / 못 하는 것</div>'
    f'{paras(CRIT.get("scope_statement"))}</div>'
    f'<div class="scope-card accent">'
    f'<div class="scope-h">"출구 50% 가림이 최고" 가설 판정</div>'
    f'{paras(CRIT.get("nickel_foam_verdict"))}</div>'
    f'{overclaim_block()}'
    + (f'<div class="lims"><div class="lims-h">추가 한계</div><ul>{limitations_list()}</ul></div>'
       if limitations_list() else "")
    + '</section>')

# ---- baseline & symbols box (read FIRST) ----
SYMBOLS = [
    ("기준 메시 — 그림 1–4·§1–3의 기준",
     "pp_040x053 = 개구 L_h 1.18 mm · 개구율 φ 50% · 메시 두께 t_m 0.48 mm, 유로 전체(100%)를 출구쪽부터 피복. "
     "(실측에 실제로 쓴 메시. §5의 다른 곡선은 각기 다른 메시다.)"),
    ("메시 두께  t_m", "그물 자체의 두께. 유로 깊이 d_ch(0.9 mm)보다 얇아야 장착 가능."),
    ("유로 깊이  d_ch", "기포가 자라는 유로 채널의 깊이 = 0.9 mm (전극 두께가 아니라 유로 깊이)."),
    ("개구 크기  L_h", "그물코 한 칸(구멍)의 크기 [mm]."),
    ("개구율  φ", "그물에서 뚫린(열린) 면적의 비율. 낮을수록 촘촘(가닥이 많음)."),
    ("피복률  θ (theta)", "촉매 표면이 기포에 덮인 비율(0~1). 높을수록 반응할 자리↓."),
    ("홀드업  ε (epsilon)", "유로 부피 중 기포가 차지한 비율. 높을수록 전해질 이온 길 막힘↑."),
    ("위킹  wick", "그물이 기포를 촉매에서 떼어내는 강도(0~1). 개구 2 mm 이하에서 최대."),
    ("유속 부스트  u_boost", "그물이 유로를 좁혀 빨라진 국소 유속 배수(압력강하 위험 지표)."),
    ("전류밀도  j", "단위 면적당 전류 [mA/cm²]. 높을수록 기포가 많아 병목↑."),
    ("절감폭  ΔV", "같은 j에서 pristine(메시 없음) 대비 메시가 낮춘 전압 [mV]. +면 이득."),
]
symbols_html = (
    '<div class="abs" style="border-left-color:var(--good)"><div class="lab" style="color:var(--good)">'
    '기준 메시 &amp; 기호 — 먼저 읽어주세요</div><dl class="gl" style="margin-top:6px">'
    + "".join(f'<dt>{esc(t)}</dt><dd>{esc(d)}</dd>' for t, d in SYMBOLS)
    + '</dl></div>')


# ---- §13 extension A: nickel-foam reaction-zone lambda(x) (the flip) ----
def _orow(cover, key):
    for r in LEXT.get("rows", []):
        if r["pos"] == "outlet" and abs(r["cover"] - cover) < 1e-6:
            return r.get(key)
    return None
def _irow(cover, key):
    for r in LEXT.get("rows", []):
        if r["pos"] == "inlet" and abs(r["cover"] - cover) < 1e-6:
            return r.get(key)
    return None
_orows = [r for r in LEXT.get("rows", []) if r["pos"] == "outlet" and r["cover"] > 0]
_opk = max(_orows, key=lambda r: r["total_dV"]) if _orows else {"cover": 0.75, "total_dV": 0}
_q = (LEXT.get("params") or {}).get("q", 0.55)

lambda_rows = []
for r in LEXT.get("rows", []):
    if r["cover"] == 0:
        continue
    lambda_rows.append([chip(r["pos"], {"outlet": "good", "middle": "n", "inlet": "bad"}[r["pos"]]),
                        f'{int(r["cover"]*100)}%', f'{r["base_dV"]:.1f}', dv_chip(r["foam_dV"]),
                        f'{r["total_dV"]:.1f}'])
# grounded through-thickness foam model (foam_model.json) — the honest refutation
_foam = FOAM.get("ref_case", {})
_fo = sorted([r for r in _foam.get("rows", []) if r["pos"] == "outlet"], key=lambda r: r["cover"])
_zp = _fo[-1]["zwet_pris_out"] if _fo else 173
_zm = _fo[-1]["zwet_mesh_out"] if _fo else 564
_Lfoam = int((FOAM.get("foam") or {}).get("L_foam_um", 600))
_foam_full = _fo[-1]["foam_dV"] if _fo else 8.2
_qflip = FOAM.get("q_flip_min")
foam_rows = [[f'{int(r["cover"]*100)}%', f'{r["base_dV"]:.1f}', dv_chip(r["foam_dV"]),
              f'{r["total_dV"]:.1f}', f'{r["zwet_mesh_out"]:.0f}'] for r in _fo]
foam_tbl = table(["출구 피복", "기존 ΔV", "폼 재젖음 기여", "합계 ΔV", "젖음 깊이 µm"], foam_rows,
                 aligns=["right", "right", "right", "right", "right"],
                 highlight=lambda r, i: r[0] == "100%")
# §13 needs both the post-proc (LEXT) and grounded (FOAM) data; skip cleanly on a
# dry build where the upstream analysis JSONs are absent (matches the else {} loads).
lambda_html = "" if not (LEXT and FOAM) else (
    f'<section id="lambda"><div class="sh"><span class="sn">§13</span>'
    f'<h2>확장 ① — 니켈폼 반응영역 λ(x): 정직한 재검증 (뒤집힘은 물리로 따지면 재현 안 됨)</h2></div>'
    f'<p class="lead">실측 "출구 50% &gt; 100%"를 재현하려 니켈폼 반응영역 깊이 λ(x)를 <b>두 방식</b>으로 넣어봤다. '
    f'후처리로 대충 가정하면 뒤집힘이 나오지만, 님의 <b>실제 폼 물리로 제대로 풀면 뒤집힘은 사라진다</b> — 여전히 전면 100% 피복이 최적이다.</p>'
    f'<p><b>① 후처리(가정) 버전:</b> "물이 안 덮인 입구로만 폼에 들어가 하류를 적신다"고 가정하니 출구 {int(_opk["cover"]*100)}%'
    f'({_opk["total_dV"]:.0f} mV)가 전면 100%({_orow(1.0,"total_dV"):.0f} mV)를 이겼다(그림 13). '
    f'하지만 이 뒤집힘은 <b>메시가 폼 물유입을 q≳0.4로 막는다는 가정</b>과, 유입을 입구 한 곳으로만 놓은 데서 나온 것이다.</p>'
    f'<p><b>② 접지(grounded) 버전:</b> 님 폼(두께 {_Lfoam} µm·공극률 0.95·기공 450 µm)의 두께방향+길이방향 젖음을 실제로 풀면 — '
    f'<b>전면 100%가 최적</b>이고, 물유입 차단을 기하 최대(50%)는 물론 <b>소수성 극한 q=0.97까지 올려도, 유량 1–8 mL/min 어디서도 '
    f'뒤집히지 않는다</b>(그림 16). 결정적 이유: 유로가 폼을 <b>입구 한 곳이 아니라 길이 전체를 따라</b> 계속 적셔주므로, '
    f'입구를 덮어도 하류 폼이 굶지 않는다 — ①의 "입구만 급수" 가정이 틀렸던 것이다.</p>'
    f'<p><b>진짜인 것:</b> 폼 <b>재젖음 자체는 실재</b>한다. 메시가 가스로 말랐던 출구 폼을 <b>{_zp:.0f} → {_zm:.0f} µm</b> 깊이로 '
    f'다시 적셔 약 +{_foam_full:.0f} mV를 번다. 다만 이 이득이 <b>부분 피복에서 정점이 아니라 전면에서 포화</b>할 뿐이다.</p>'
    + figure("fig_lambda.svg", 13,
             "① 후처리(가정) 버전 — 오른쪽 출구 곡선이 부분 피복에서 정점(뒤집힘). 단, '입구만 급수' 가정에 의존.",
             "이 뒤집힘은 물유입 차단 q≳0.4 가정에서만 나온다. 아래 접지 버전(그림 16)이 이걸 반박한다.")
    + figure("fig_foam.svg", 16,
             "② 접지 버전 — 왼쪽: 후처리(노랑)는 부분에서 정점이지만 접지 모델(파랑)은 100%가 최적. "
             "오른쪽: 물유입 차단 q_eff를 소수성 극한 0.97까지 올려도 뒤집힘 없음.",
             f'폼 재젖음은 실재(출구 {_zp:.0f}→{_zm:.0f} µm)하지만 전면에서 포화. 접지 모델은 님 실측을 재현하지 못한다.')
    + foam_tbl
    + f'<div class="cav"><div class="cav-h">정직한 결론</div><ul>'
    f'<li><b>이 물리(폼 물공급)는 님의 outlet-50% 실측을 설명하지 못한다.</b> §13 초판의 뒤집힘은 가정 의존적 아티팩트였다 — 접지하면 사라진다.</li>'
    f'<li>남은 후보(모델 밖): (a) 소수성 메시가 <b>전면 피복 시 입구쪽에 가스를 가두는</b> 다운사이드, '
    f'(b) 메시 압착에 의한 <b>접촉저항/GDL 변형</b>, (c) "50/100" 라벨이 피복률이 아닌 <b>다른 의미</b>(미해결).</li>'
    f'<li>블라인드 유지: 어떤 버전도 실측 outlet-50%에 맞추지 않았다. 접지 모델의 반박이 오히려 <b>정직한 예측 실패의 기록</b>이다.</li></ul></div>'
    + '</section>')


# ---- §14 extension B: when does blocking reverse the benefit? ----
_ex = M2D.get("extremes", [])
def _exrow(idx, key):
    return _ex[idx].get(key) if idx < len(_ex) else None
_cross = M2D.get("cross_j", {})
rev_rows = []
for e in _ex:
    rev_rows.append([esc(e["tag"]), f'{e["hole"]:.1f}/{int(e["phi"]*100)}%/{e["t"]:.2f}',
                     dv_chip(e["peel"]), dv_chip(round(e["push"], 1)), dv_chip(e["block"]),
                     f'{e["net"]:.0f}'])
rev_tbl = table(["메시", "L_h/φ/t_m", "떼어냄", "밀어냄", "차단", "순 mV"], rev_rows,
                aligns=["left", "left", "right", "right", "right", "right"],
                highlight=lambda r, i: i == len(_ex) - 1)
_blk_ref = _exrow(0, "block"); _blk_ext = _exrow(len(_ex) - 1, "block")
reversal_html = "" if not M2D else (
    f'<section id="reversal"><div class="sh"><span class="sn">§14</span>'
    f'<h2>확장 ② — 차단(③)은 언제 이득을 역전시키나</h2></div>'
    f'<p class="lead">운전점(1000 mA/cm²)에서는 <b>절대 역전되지 않는다</b> — 메시를 두껍게 하면 차단이 커지지만 '
    f'유속 부스트(밀어냄)도 함께 커져 상쇄되기 때문이다. 역전은 <b>가스가 거의 없는 저전류</b>에서만 일어난다.</p>'
    f'<p>차단 비용 자체는 기하가 <b>거칠고(개구 큼)·촘촘하고·두꺼울수록</b> 커진다 — 기준 메시 {_blk_ref:.0f} mV에서 '
    f'극단(개구 7 mm·φ 5%·두께 0.88 mm) {_blk_ext:.0f} mV까지 (개구가 크면 위킹↓, 두꺼우면 차단↑). '
    f'그래도 밀어냄(≈+70 mV)이 이겨서 1000 mA/cm²에서는 순이득이 양수로 유지된다.</p>'
    f'<p>하지만 <b>저전류에서는 밀어낼 기포가 없어</b> 차단만 남는다. 거친+촘촘한+두꺼운 메시는 '
    f'<b>j ≲ 100–150 mA/cm²에서 오히려 전압을 올린다</b>(손해). 그 위로 가스가 쌓이기 시작하면 이득으로 바뀐다 '
    f'— 즉 "이 메시가 도움이 되기 시작하는 최소 전류"가 존재한다.</p>'
    + figure("fig_reversal.svg", 14,
             "전류밀도별 순 ΔV. 거친+촘촘한+두꺼운 메시는 저전류(붉은 영역)에서 음수 — 메시가 손해. "
             "약 100–150 mA/cm²에서 0을 지나 이득으로.",
             "기준(얇고 fine) 메시는 전 전류에서 이득. 압력강하는 별도(u_boost 프록시로만 다룸).")
    + figure("fig_block_growth.svg", 15,
             "네 메시의 작용 분해(1000 mA/cm²). 개구가 커지고 촘촘·두꺼워질수록 차단(빨강)이 −7→−37 mV로 커지지만 "
             "밀어냄이 이겨 순이득은 양수 유지.")
    + rev_tbl
    + '</section>')

disc_html = ""
if SYN.get("cross_axis_discussion") or SYN.get("design_recommendation") or SYN.get("conclusion"):
    disc_html = (
        f'<section id="disc"><div class="sh"><span class="sn">§15</span><h2>통합 논의 & 설계 권고</h2></div>'
        f'{paras(SYN.get("cross_axis_discussion"))}'
        + (f'<div class="rec"><div class="rec-h">이 셀에 대한 설계 권고</div>{paras(SYN.get("design_recommendation"))}</div>'
           if SYN.get("design_recommendation") else "")
        + (f'<h3>결론</h3>{paras(SYN.get("conclusion"))}' if SYN.get("conclusion") else "")
        + '</section>')

# ---- §16 governing equations (why the numbers come out) ----
def eqrow(key, note):
    return (f'<div class="eqrow"><div class="eqplate">{svg("eq_%s.svg" % key)}</div>'
            f'<div class="eqnote">{note}</div></div>')
def eqgrp(title, rows):
    return f'<div class="eqgrp"><div class="eqgrp-h">{esc(title)}</div>{"".join(rows)}</div>'

eqs_html = (
    f'<section id="eqs"><div class="sh"><span class="sn">§16</span>'
    f'<h2>모델 방정식 — 이 숫자들이 어디서 나오나</h2></div>'
    f'<p>리포트의 모든 mV·θ·ε·R 값은 아래 지배 방정식에서 계산된다. 각 식이 어느 그림의 수치를 만드는지 표시했다. '
    f'상수(0.6·0.5·0.3·L_ref=2 mm 등)는 실험 전 a priori로 고정된 값이다(블라인드).</p>'
    + eqgrp("A. 셀 전압의 뼈대 (모든 그림)", [
        eqrow("vcell", "셀 전압 = 열역학 최소 + 과전압들의 합. <b>그림 3</b>의 막대 분해가 바로 이 항들."),
        eqrow("bv", "Butler–Volmer: 전류–과전압 관계. <b>(1−θ)</b>가 기포 피복만큼 활성면적을 깎는다 → 피복이 오르면 같은 전류에 더 큰 η."),
        eqrow("etacov", "피복 과전압: θ→1이면 ln(1/(1−θ))로 전압이 폭증. <b>§1–3의 ΔV, 그림 1·3</b>의 근원."),
      ])
    + eqgrp("B. 채널 병목 — 가스가 어디에 쌓이나 (그림 4·5·7·11)", [
        eqrow("accum", "하류 누적 가스는 ∫j ds에 비례하고 <b>유속 u에 반비례</b>. → 유속↑이면 ε↓(<b>그림 7·11</b>), 출구로 갈수록 ∫j가 커져 θ↑(<b>그림 4</b>)."),
        eqrow("eps", "홀드업 ε = 누적가스/(1+누적가스). 포화형이라 절대 1을 못 넘음."),
        eqrow("theta", "Vogt–Balzer 피복 폐합: 벌크 void ε를 표면 피복 θ로 변환. θ_add는 메시 차단 바닥값."),
      ])
    + eqgrp("C. 메시 3작용 — 왜 두께·개구율·기공이 그렇게 (그림 1·2·8·9·14)", [
        eqrow("wick", "위킹 w: 개구 L_h가 L_ref=2 mm <b>이하면 min=1로 포화</b> → 기공 크기 무관(<b>그림 9 오른쪽 평탄</b>). 개구율 φ↓(촘촘)이면 w↑(<b>그림 9 왼쪽</b>)."),
        eqrow("peel", "① 떼어냄: 위킹이 피복 진폭을 깎음(θ_factor). <b>그림 1</b>의 +48 mV."),
        eqrow("sweep", "② 밀어냄: 두께 t_m↑ → u_boost↑ → retention↓(홀드업 배출↑). <b>그림 8·2</b>의 밀어냄 항."),
        eqrow("block", "③ 차단: 두껍고(t_m↑) 촘촘할수록(φ↓) θ_add↑. <b>그림 14</b> 저전류 역전의 원인."),
        eqrow("decomp", "세 작용의 합 = 순 ΔV. 각 항은 작용을 켜기 전·후의 η_cov 차이(<b>그림 1 워터폴</b>)."),
      ])
    + eqgrp("D. EIS (그림 12)", [
        eqrow("rct", "전하전달 저항: <b>(1−θ)j₀</b> 때문에 메시가 θ를 낮추면 R_ct↓ → <b>아크 축소</b>."),
        eqrow("zcell", "전체 임피던스 = 직렬 R_s + 전극별 (R_ct+Warburg)∥C_dl. R_s=η_ohm/j는 메시와 무관(절편 불변)."),
      ])
    + eqgrp("E. 음극 건식 물 한계 (dry-cathode)", [
        eqrow("water", "막이 공급 가능한 물의 한계전류 j_lim,w와 그에 따른 η_water. 전기삼투 끌림 n_drag가 한계를 낮춤."),
      ])
    + eqgrp("F. 니켈폼 λ(x) 확장 (그림 13·16)", [
        eqrow("foamW", "폼 축방향 젖음 W: 열린 표면에서 soak(1−q·c), 가스로 drain. <b>왜 안 뒤집히나</b> — soak가 유로 전체에서 계속 채워, 입구를 덮어도 하류가 안 굶음."),
        eqrow("zwet", "젖음 깊이 z_wet = 폼 두께 × W^m. 접지 모델의 출구 재젖음 173→564 µm."),
        eqrow("foamdV", "폼 재젖음 전압 이득(차등). 부분 피복이 아니라 <b>전면에서 포화</b>해 뒤집힘을 못 만듦(<b>그림 16</b>)."),
      ])
    + '</section>')

# glossary (plain-language term guide)
GLOSSARY = [
    ("θ 피복률 (coverage)", "촉매 표면이 기포에 덮인 비율(0~1). 높을수록 반응할 자리가 줄어 손실↑."),
    ("ε 홀드업 (holdup)", "유로 부피 중 기포가 차지한 비율. 높을수록 전해질 이온 길이 막혀 저항↑."),
    ("과전압 η (overpotential)", "이론 최소전압(E_rev, ~1.19 V) 위에 실제로 더 걸어야 하는 '손실 전압'. 활성화·옴·농도·기포 등으로 나뉨."),
    ("LSV / 분극곡선", "전류밀도 j를 올리며 셀전압 V를 기록한 곡선. 같은 j에서 V가 낮을수록 효율↑."),
    ("EIS / 임피던스", "작은 교류를 넣어 저항 성분을 주파수별로 분리. R_s(직렬=막·전해질), R_ct(전하전달=반응 저항, 기포 피복에 민감)."),
    ("위킹 wick", "소수성 그물이 기포를 끌어당겨 촉매에서 떼는 강도(0~1). 촘촘·미세할수록↑ (개구 2 mm 이하에서 포화)."),
    ("u_boost", "메시가 유로를 좁혀 생기는 국소 유속 배수. 압력강하 dP ≈ u² 이므로 dP 위험 지표(상한 4.0)."),
    ("ΔV (dV)", "같은 전류에서 pristine 대비 메시가 낮춘 전압(mV). +면 메시 이득."),
    ("dry-cathode (음극 건식)", "음극에 전해질을 직접 안 주고 물이 막을 통해서만 공급되는 AEM 방식(실제 셀 구성)."),
    ("블라인드 프로토콜", "모델을 pristine 실측 1개에만 맞추고, 메시 예측엔 메시 실측을 넣지 않는 것 — 진짜 예측력 검증."),
]
gloss_html = (
    f'<section id="gloss"><div class="sh"><span class="sn">§17</span><h2>용어 풀이</h2></div>'
    '<dl class="gl">'
    + "".join(f'<dt>{esc(t)}</dt><dd>{esc(d)}</dd>' for t, d in GLOSSARY)
    + '</dl></section>')

# data availability
csvs = sorted([p.name for p in OUT.glob("*.csv")])
csv_items = "".join(f"<li><code>{esc(c)}</code></li>" for c in csvs)
data_html = (
    f'<section id="data"><div class="sh"><span class="sn">§18</span><h2>데이터 (Excel) · PDF</h2></div>'
    f'<p>모든 곡선·지표는 UTF-8 BOM CSV로 저장되어 Excel에서 바로 열린다. 리포트 PDF와 그림 원본도 같은 폴더에 있다. '
    f'경로: <code>analysis/out/</code> (그림 SVG는 <code>analysis/out/figs/</code>).</p>'
    f'<div class="tw"><ul class="cols">{csv_items}</ul></div></section>')

CSS = """
<title>__TITLE__</title>
<style>
:root{
  --bg:#eef1f6; --surf:#ffffff; --surf2:#f5f7fb; --ink:#141d33; --ink2:#33405c;
  --mut:#66708a; --line:#dde3ee; --line2:#c9d2e2;
  --accent:#1f5fe0; --accent-soft:#e7eefc;
  --good:#0f7a58; --good-soft:#e2f3ec; --bad:#c22f3d; --bad-soft:#fbe6e8;
  --gold:#b3791a; --h2:#2f7fb8; --o2:#c67a1c;
  --serif:"Iowan Old Style","Charter","Georgia",serif;
  --sans:"Segoe UI","Malgun Gothic","Apple SD Gothic Neo","Pretendard",system-ui,sans-serif;
  --mono:"Cascadia Code",ui-monospace,"D2Coding","Consolas",monospace;
  --maxw:820px;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0c111c; --surf:#141c2b; --surf2:#111825; --ink:#e8edf7; --ink2:#c2ccdd;
  --mut:#8e9ab2; --line:#243146; --line2:#31415c;
  --accent:#5b8dff; --accent-soft:#182741;
  --good:#3fbf92; --good-soft:#12241d; --bad:#f0838f; --bad-soft:#2a1519;
  --gold:#d3a24a; --h2:#5fb0e0; --o2:#e0a24c;
}}
:root[data-theme="dark"]{
  --bg:#0c111c; --surf:#141c2b; --surf2:#111825; --ink:#e8edf7; --ink2:#c2ccdd;
  --mut:#8e9ab2; --line:#243146; --line2:#31415c;
  --accent:#5b8dff; --accent-soft:#182741;
  --good:#3fbf92; --good-soft:#12241d; --bad:#f0838f; --bad-soft:#2a1519;
  --gold:#d3a24a; --h2:#5fb0e0; --o2:#e0a24c;
}
:root[data-theme="light"]{
  --bg:#eef1f6; --surf:#ffffff; --surf2:#f5f7fb; --ink:#141d33; --ink2:#33405c;
  --mut:#66708a; --line:#dde3ee; --line2:#c9d2e2;
  --accent:#1f5fe0; --accent-soft:#e7eefc;
  --good:#0f7a58; --good-soft:#e2f3ec; --bad:#c22f3d; --bad-soft:#fbe6e8;
  --gold:#b3791a; --h2:#2f7fb8; --o2:#c67a1c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  line-height:1.62;font-size:16.5px;-webkit-font-smoothing:antialiased}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 22px 120px}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--accent);font-weight:600}
/* masthead */
.mast{padding:52px 0 30px;border-bottom:2px solid var(--ink);margin-bottom:8px}
.mast h1{font-family:var(--serif);font-weight:600;font-size:clamp(30px,5.4vw,46px);
  line-height:1.1;letter-spacing:-.01em;margin:14px 0 8px;text-wrap:balance;color:var(--ink)}
.mast .sub{color:var(--ink2);font-size:17px;max-width:60ch;margin:0}
.meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2px 26px;margin-top:26px;
  border-top:1px solid var(--line);padding-top:16px}
.mrow{display:flex;gap:10px;font-size:13.5px;padding:3px 0;border-bottom:1px dotted var(--line)}
.mk{color:var(--mut);min-width:56px;font-family:var(--mono);font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.mv{color:var(--ink2);font-weight:500}
/* abstract */
.abs{background:var(--surf);border:1px solid var(--line);border-left:3px solid var(--accent);
  border-radius:0 10px 10px 0;padding:20px 24px;margin:30px 0}
.abs .lab{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--accent);font-weight:600;margin-bottom:6px}
.abs p{margin:0;color:var(--ink2);font-size:15.5px}
/* key findings */
.kfbox{margin:34px 0}
.kfbox>.lab{font-family:var(--mono);font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);margin-bottom:12px}
ol.kf{margin:0;padding:0;list-style:none;counter-reset:kf}
ol.kf li{counter-increment:kf;position:relative;padding:11px 0 11px 44px;border-top:1px solid var(--line);
  font-size:15.5px;color:var(--ink2)}
ol.kf li::before{content:counter(kf,decimal-leading-zero);position:absolute;left:0;top:11px;
  font-family:var(--mono);font-size:12.5px;color:var(--accent);font-weight:700;
  background:var(--accent-soft);border-radius:5px;padding:2px 6px}
/* sections */
section{margin:46px 0;scroll-margin-top:20px}
.sh{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid var(--line2);padding-bottom:8px;margin-bottom:20px}
.sn{font-family:var(--mono);font-size:14px;color:var(--accent);font-weight:700}
h2{font-family:var(--serif);font-weight:600;font-size:24px;margin:0;letter-spacing:-.01em;color:var(--ink);text-wrap:balance}
h3{font-family:var(--sans);font-weight:700;font-size:16px;margin:26px 0 8px;color:var(--ink)}
p{margin:0 0 14px}
.lead{font-size:17px;font-weight:600;color:var(--ink);border-left:2px solid var(--accent);padding-left:12px;line-height:1.5}
.mut{color:var(--mut);font-size:14px}
.ilabel{display:inline-block;font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--accent);font-weight:700;margin-right:8px;vertical-align:1px}
code{font-family:var(--mono);font-size:.86em;background:var(--surf2);border:1px solid var(--line);
  border-radius:5px;padding:1px 5px;color:var(--ink)}
/* figures */
.fig{margin:22px 0;background:var(--surf);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.fig-body{padding:16px 16px 4px;overflow-x:auto;text-align:center}
.fig-body svg{max-width:100%;height:auto}
figcaption{padding:12px 18px 16px;border-top:1px solid var(--line);font-size:13.5px;color:var(--ink2);background:var(--surf2)}
.fig-n{font-family:var(--mono);font-size:11.5px;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.06em;margin-right:8px}
.fig-note{margin-top:6px;color:var(--mut);font-size:12.5px;font-style:italic}
/* tables */
.tw{overflow-x:auto;margin:18px 0;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
thead th{background:var(--surf2);text-align:left;padding:9px 12px;font-family:var(--mono);
  font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);font-weight:600;
  border-bottom:1px solid var(--line2);white-space:nowrap}
td{padding:8px 12px;border-bottom:1px solid var(--line);color:var(--ink2);
  font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:none}
tr.hi td{background:var(--accent-soft)}
.a-right{text-align:right} .a-left{text-align:left} .a-center{text-align:center}
td code{background:none;border:none;padding:0;color:var(--ink);font-weight:600}
/* chips */
.chip{display:inline-block;font-family:var(--mono);font-size:11.5px;font-weight:600;
  padding:1px 7px;border-radius:20px;line-height:1.5;white-space:nowrap}
.c-good{background:var(--good-soft);color:var(--good)}
.c-bad{background:var(--bad-soft);color:var(--bad)}
.c-n{background:var(--accent-soft);color:var(--accent)}
.c-muted{background:var(--surf2);color:var(--mut);border:1px solid var(--line)}
.warn{color:var(--gold);font-family:var(--mono);font-size:11px;font-weight:600}
/* caveats */
.cav{background:var(--surf2);border:1px solid var(--line);border-radius:9px;padding:12px 16px;margin:16px 0}
.cav-h{font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--gold);font-weight:700;margin-bottom:6px}
.cav ul{margin:0;padding-left:18px}.cav li{font-size:13.5px;color:var(--ink2);margin:3px 0}
/* scope */
.scope-card{background:var(--surf);border:1px solid var(--line);border-radius:12px;padding:18px 22px;margin:16px 0}
.scope-card.accent{border-left:3px solid var(--bad)}
.scope-h{font-family:var(--mono);font-size:12px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--ink);font-weight:700;margin-bottom:8px}
.scope-card.accent .scope-h{color:var(--bad)}
.scope-card p{font-size:15px;color:var(--ink2);margin:0 0 10px}.scope-card p:last-child{margin:0}
.ocs{margin:18px 0}.ocs-h{font-family:var(--mono);font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin-bottom:10px}
.oc{border:1px solid var(--line);border-radius:9px;padding:12px 16px;margin:8px 0;background:var(--surf2)}
.oc-claim{color:var(--bad);font-weight:600;font-size:14.5px;text-decoration:line-through;text-decoration-color:var(--line2)}
.oc-fix{color:var(--ink2);font-size:14px;margin-top:5px}
.lims{margin:18px 0}.lims-h{font-family:var(--mono);font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin-bottom:6px}
.lims ul{margin:0;padding-left:20px}.lims li{color:var(--ink2);font-size:14.5px;margin:4px 0}
/* mechanism cards (WHY) */
.mech{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}
.mech-card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--surf);
  border-top:3px solid var(--good)}
.mech-card.bad{border-top-color:var(--bad)}
.mc-h{font-weight:700;font-size:15px;color:var(--ink)}
.mc-h span{font-family:var(--mono);font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);font-weight:600;margin-left:4px}
.mc-v{font-family:var(--mono);font-size:26px;font-weight:700;color:var(--good);margin:4px 0 6px;font-variant-numeric:tabular-nums}
.mech-card.bad .mc-v{color:var(--bad)}
.mc-d{font-size:13px;color:var(--ink2);line-height:1.5}
.mc-t{display:block;margin-top:6px;font-family:var(--mono);font-size:11px;color:var(--mut)}
.mech-net{background:var(--accent-soft);border-radius:10px;padding:12px 16px;margin:6px 0 8px;
  font-size:15px;color:var(--ink);text-align:center;font-variant-numeric:tabular-nums}
.mech-net b{color:var(--accent);font-size:17px}
@media(max-width:640px){.mech{grid-template-columns:1fr}}
/* worked-calculation box (under figs 1 & 4) */
.calc{background:var(--surf2);border:1px solid var(--line);border-left:3px solid var(--accent);
  border-radius:0 10px 10px 0;padding:14px 18px;margin:16px 0;font-size:13.5px}
.calc-h{font-family:var(--mono);font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;
  color:var(--accent);font-weight:700;margin-bottom:8px}
.calc-in{color:var(--ink2);margin-bottom:9px;padding-bottom:8px;border-bottom:1px dotted var(--line);line-height:1.55}
.calc-steps{margin:0;padding-left:0;list-style:none}
.calc-steps li{padding:7px 0;border-bottom:1px dotted var(--line);color:var(--ink2);line-height:1.6}
.calc-steps li:last-child{border-bottom:none}
.calc .eq{font-family:var(--mono);color:var(--ink);font-size:12.5px;background:var(--surf);
  border:1px solid var(--line);border-radius:5px;padding:1px 6px}
.calc .cv{font-family:var(--mono);color:var(--good);font-weight:700;white-space:nowrap}
.calc-out{margin-top:10px;padding-top:9px;border-top:1px solid var(--line2);font-weight:600;color:var(--ink);font-size:14px}
.calc sub{font-size:.8em}
/* plain intro */
.intro{background:var(--surf);border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin:30px 0}
.intro .lab{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--good);font-weight:600;margin-bottom:8px}
.intro p{font-size:15.5px;color:var(--ink2);margin:0 0 10px}.intro p:last-child{margin:0}
.intro b{color:var(--ink)}
/* equations */
.eqgrp{margin:16px 0}
.eqgrp-h{font-weight:700;font-size:15px;color:var(--ink);margin:18px 0 6px;padding-bottom:4px;border-bottom:1px solid var(--line2)}
.eqrow{display:flex;gap:16px;align-items:center;padding:10px 0;border-bottom:1px dotted var(--line);flex-wrap:wrap}
.eqplate{background:#f5f7fc;border:1px solid #e2e7f2;border-radius:8px;padding:7px 14px;overflow-x:auto;flex:0 1 auto;max-width:100%}
.eqplate svg{height:auto;max-width:100%;display:block}
.eqnote{flex:1 1 230px;font-size:13.5px;color:var(--ink2);line-height:1.5}
.eqnote b{color:var(--ink)}
/* glossary */
dl.gl{margin:0;border-top:1px solid var(--line)}
dl.gl dt{font-weight:700;font-size:14.5px;color:var(--ink);margin-top:14px}
dl.gl dd{margin:3px 0 0;font-size:14px;color:var(--ink2);padding-bottom:12px;border-bottom:1px solid var(--line)}
/* recommendation */
.rec{background:var(--accent-soft);border-radius:12px;padding:18px 22px;margin:22px 0}
.rec-h{font-family:var(--mono);font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);font-weight:700;margin-bottom:8px}
.rec p{color:var(--ink2);font-size:15px}
ul.cols{columns:2;margin:0;padding-left:18px}ul.cols li{margin:4px 0;font-size:13.5px;break-inside:avoid}
footer{margin-top:60px;padding-top:20px;border-top:1px solid var(--line);color:var(--mut);font-size:12.5px;font-family:var(--mono)}
@media(max-width:560px){.meta{grid-template-columns:1fr}ul.cols{columns:1}body{font-size:16px}}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
/* ---- print / PDF ---- */
@media print{
  :root{--bg:#fff;--surf:#fff;--surf2:#f4f6fa;--ink:#141d33;--ink2:#33405c;--mut:#66708a;
    --line:#dde3ee;--line2:#c9d2e2;--accent:#1f5fe0;--accent-soft:#eaf1fd;
    --good:#0f7a58;--good-soft:#e6f4ee;--bad:#c22f3d;--bad-soft:#fbeaec;--gold:#a06d14;}
  @page{size:A4;margin:13mm 12mm;}
  body{font-size:10.4pt;background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
  .wrap{max-width:100%;padding:0;}
  .mast{padding-top:4px;}
  h2{font-size:17pt;} h1{font-size:26pt;}
  .fig,.tw,.mech,.mech-card,.mech-net,.scope-card,.cav,.abs,.intro,.rec,figure,.oc{break-inside:avoid;}
  .sh{break-after:avoid;}
  section{break-inside:auto;}
  .fig-body svg{max-width:100%;}
  a{color:inherit;text-decoration:none;}
  footer{break-inside:avoid;}
}
</style>
"""

HTML = CSS.replace("__TITLE__", esc(TITLE)) + f"""
<div class="wrap">
  <header class="mast">
    <div class="eyebrow">시뮬레이션 스터디 · 블라인드 프로토콜</div>
    <h1>{esc(TITLE)}</h1>
    <p class="sub">소수성 PP 기포관리 메시의 기하·운전 파라미터가 AEM 수전해 셀 성능에
      미치는 영향을 캘리브레이션된 채널 병목 모델로 예측·비교한다.</p>
    <div class="meta">{meta_html}</div>
  </header>

  <div class="abs"><div class="lab">초록 · Abstract</div><p>{esc(ABSTRACT)}</p></div>

  <div class="intro">
    <div class="lab">30초 요약 · 무슨 일이 벌어지나</div>
    <p>물을 전기분해하면 촉매 표면에서 기포(O₂·H₂)가 끊임없이 생긴다. 이 기포는 두 가지로
      성능을 깎는다 — <b>① 촉매를 덮어</b> 반응할 자리를 가리고(피복 θ), <b>② 유로를 채워</b>
      전류가 지나갈 전해질 길을 막는다(홀드업 ε → 저항↑). 전류가 높을수록 기포가 많아져 더 심해진다.</p>
    <p>촉매 위에 <b>소수성 PP 그물(메시)</b>을 덮으면: 그물 가닥이 기포를 촉매에서 <b>걷어내고</b>(떼어냄),
      좁아진 유로의 빠른 물살이 기포를 하류로 <b>쓸어낸다</b>(밀어냄). 대신 그물이 전해질이 촉매로
      닿는 길을 조금 <b>막는다</b>(차단, 손해). 순효과 = 떼어냄 + 밀어냄 − 차단. §1이 이걸 mV로 쪼갠다.</p>
  </div>

  <div class="kfbox"><div class="lab">핵심 발견 · Key findings</div>{kf_list()}</div>

  {symbols_html}

  {sections_html}
  {scope_html}
  {lambda_html}
  {reversal_html}
  {disc_html}
  {eqs_html}
  {gloss_html}
  {data_html}

  <footer>bubblesim · channel + meshlayer (blind) · 계산 {len(csvs)} CSV + 15 figures + 메커니즘 분해 + λ(x) 확장 ·
    이 리포트의 수치는 전부 재현 가능한 계산 산출물이다.</footer>
</div>
"""

(OUT / "report.html").write_text(HTML, encoding="utf-8")
print("report.html ->", OUT / "report.html", f"({len(HTML)} bytes)")
