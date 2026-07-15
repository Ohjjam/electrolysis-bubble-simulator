# -*- coding: utf-8 -*-
"""Assemble the mesh-study report HTML (self-contained, inlined SVG figures).

Reads: out/summary.json, out/narrative.json (workflow prose), out/figs/*.svg
Writes: out/report.html  (Artifact-ready: <title> + <style> + body content only)
"""
import json
import html
from pathlib import Path

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

SECTIONS = [
    dict(n=1, id="calib", t="캘리브레이션 & 방법",
         fig=figure("fig_calib.svg", 1,
                    "측정된 pristine 분극곡선과 캘리브레이션된 모델(선). 16점 RMSE "
                    f'{S["pristine"]["calib_RMSE_mV"]} mV.',
                    "메시 곡선은 이 pristine 보정만으로 기하구조에서 예측한다 — 메시 실측은 모델에 넣지 않음."),
         body=(f'<p>모든 스윕은 실험탭이 쓰는 것과 동일한 채널 병목 솔버'
               f'(<code>bubblesim.solvers.channel</code> + <code>kernel.meshlayer</code>)를 '
               f'기준 셀에서 한 축씩 돌린 것이다. 기준 셀은 {D0["n_ch"]}채널 사행, '
               f'{D0["w_ch_mm"]}/{D0["d_ch_mm"]} mm 유로, {D0["c_mol"]} M KOH {D0["T"]}°C, '
               f'4 mL/min, dry-cathode AEM. 효율 지표는 고정 전류에서의 셀전압 V@500·V@1000 '
               f'(낮을수록 좋음)과 pristine 대비 절감폭 ΔV(+면 메시 이득)이다.</p>'
               + (f'<p class="mut">{esc(CRIT.get("blind_ok"))}</p>' if CRIT.get("blind_ok") else ""))),
    dict(n=2, id="catalog", t="어떤 메시가 가장 효율이 좋은가",
         fig=figure("fig_catalog_lsv.svg", 2, "장착 가능한 실제 PP 메시들의 분극곡선(pristine 파선 대비).") +
             figure("fig_catalog_bar.svg", 3, "메시별 ΔV@1000 (초록=장착가능). 상위권은 촘촘·얇은 메시.",
                    "0.9 mm 유로에는 t≥0.9 mm 메시 4종이 아예 장착 불가."),
         body=analysis_block("catalog") + tbl_catalog()),
    dict(n=3, id="thickness", t="두께 (t_m)",
         fig=figure("fig_thickness.svg", 4,
                    "두께에 따른 전기적 이득(초록)과 압력강하 프록시 u_boost(빨강).",
                    "얇을수록 dP가 낮다. 이득은 t≈0.6–0.75 mm에서 완만한 정점 후 정체·역전."),
         body=analysis_block("thickness") + tbl_generic("thickness", "두께 mm", lambda r: f'{r["t_mm"]:.2f}')),
    dict(n=4, id="open", t="개구율 φ (간격/밀도)",
         fig=figure("fig_open_pore.svg", 5,
                    "왼쪽: 개구율 φ에 따른 ΔV@1000 (촘촘할수록 위킹↑). 오른쪽: 기공 크기 — 2 mm 이하 등가.",
                    "u_boost는 φ에 무관(두께/깊이에만 의존)."),
         body=analysis_block("open_area") + tbl_generic("open_area", "개구율 φ", lambda r: f'{int(r["open_frac"]*100)}%')),
    dict(n=5, id="pore", t="기공(개구) 크기",
         fig="", body=analysis_block("pore_size") + tbl_generic("pore_size", "개구 mm", lambda r: f'{r["hole_mm"]:.2f}')),
    dict(n=6, id="coverage", t="가린 면적 × 위치 — 사용자의 핵심 질문",
         fig=figure("fig_coverage.svg", 6,
                    "피복률·위치별 ΔV@1000. 부분 피복에서 outlet ≫ middle ≫ inlet.",
                    "모델은 100% 전면 피복이 최적. 실측의 'outlet 50%가 100%보다 좋다'는 재현되지 않는다(§9 참조)."),
         body=analysis_block("coverage") + tbl_coverage()),
    dict(n=7, id="flow", t="유속 (펌프 유량)",
         fig=figure("fig_flow.svg", 7,
                    "왼쪽: 유량별 pristine vs 메시 V@1000. 오른쪽: 메시 이득 ΔV — 저유속 질식영역에서 폭발적.",
                    "운전점 4 mL/min에서 ΔV@1000 ≈ 99 mV, 1 mL/min에서는 ≈ 374 mV."),
         body=analysis_block("flow") + tbl_flow()),
    dict(n=8, id="eis", t="EIS 비교",
         fig=figure("fig_eis.svg", 8,
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
    f'<section id="scope" class="scope"><div class="sh"><span class="sn">§9</span>'
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

disc_html = ""
if SYN.get("cross_axis_discussion") or SYN.get("design_recommendation") or SYN.get("conclusion"):
    disc_html = (
        f'<section id="disc"><div class="sh"><span class="sn">§10</span><h2>통합 논의 & 설계 권고</h2></div>'
        f'{paras(SYN.get("cross_axis_discussion"))}'
        + (f'<div class="rec"><div class="rec-h">이 셀에 대한 설계 권고</div>{paras(SYN.get("design_recommendation"))}</div>'
           if SYN.get("design_recommendation") else "")
        + (f'<h3>결론</h3>{paras(SYN.get("conclusion"))}' if SYN.get("conclusion") else "")
        + '</section>')

# data availability
csvs = sorted([p.name for p in OUT.glob("*.csv")])
csv_items = "".join(f"<li><code>{esc(c)}</code></li>" for c in csvs)
data_html = (
    f'<section id="data"><div class="sh"><span class="sn">§11</span><h2>데이터 (Excel)</h2></div>'
    f'<p>모든 곡선·지표는 UTF-8 BOM CSV로 저장되어 Excel에서 바로 열린다. '
    f'경로: <code>analysis/out/</code>. 그림 원본 SVG는 <code>analysis/out/figs/</code>.</p>'
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
/* recommendation */
.rec{background:var(--accent-soft);border-radius:12px;padding:18px 22px;margin:22px 0}
.rec-h{font-family:var(--mono);font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);font-weight:700;margin-bottom:8px}
.rec p{color:var(--ink2);font-size:15px}
ul.cols{columns:2;margin:0;padding-left:18px}ul.cols li{margin:4px 0;font-size:13.5px;break-inside:avoid}
footer{margin-top:60px;padding-top:20px;border-top:1px solid var(--line);color:var(--mut);font-size:12.5px;font-family:var(--mono)}
@media(max-width:560px){.meta{grid-template-columns:1fr}ul.cols{columns:1}body{font-size:16px}}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
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

  <div class="kfbox"><div class="lab">핵심 발견 · Key findings</div>{kf_list()}</div>

  {sections_html}
  {scope_html}
  {disc_html}
  {data_html}

  <footer>bubblesim · channel + meshlayer (blind) · 생성: 계산 {len(csvs)} CSV + 8 figures ·
    이 리포트의 수치는 전부 재현 가능한 계산 산출물이다.</footer>
</div>
"""

(OUT / "report.html").write_text(HTML, encoding="utf-8")
print("report.html ->", OUT / "report.html", f"({len(HTML)} bytes)")
