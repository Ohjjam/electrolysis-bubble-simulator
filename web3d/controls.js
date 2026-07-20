/* Shared control definitions + builder for BOTH front-ends (app2d, app3d).
 *
 * The two pages are two VIEWS of one running simulation (server3d_app.py on
 * :8766). They must never disagree about a number, so the widget list lives
 * here once — a slider that exists in one page exists in the other, with the
 * same range, unit and physical limit. Each page then:
 *
 *   buildControls(host, SIM_CTRL, P, send)   -> { sync(designer, speed) }
 *
 * and calls `sync()` on every poll, so a value changed in one tab shows up in
 * the other within one poll (~110 ms) without the pages talking to each other.
 * Widgets the user is actively editing are never overwritten mid-drag.
 *
 * `speed` is a server-side lever but lives outside `designer`, so sync() takes
 * it separately.
 */
(function (g) {
  "use strict";

  g.SIM_CTRL = [
    ["운전 (전기)", [
      { k:"mode", nm:"운전 모드", seg:[["CP","정전류 CP"],["CA","정전압 CA"]], v:"CP" },
      { k:"j", nm:"전류밀도 j", un:"A/cm²", min:0.01, max:3, step:0.01, v:0.5, lo:0, hi:10 },
      { k:"V_cell", nm:"셀 전압 (CA)", un:"V", min:1.2, max:2.6, step:0.01, v:2.0, lo:0, hi:5 },
      { k:"electrolyte", nm:"전해질", seg:[["KOH","KOH"],["H2SO4","H₂SO₄"],["PB","인산"]], v:"KOH" },
      { k:"c_mol", nm:"농도 (>0.3 M이면 합체 억제)", un:"mol/L", min:0.1, max:12, step:0.1, v:6, lo:0.01, hi:20 },
    ]],
    ["유동 · 기포", [
      { k:"u_flow", nm:"유량 (펌프)", un:"m/s", min:0, max:2, step:0.01, v:0.35, lo:0, hi:5 },
      { k:"theta", nm:"전극 물 접촉각 (기포 이탈)", un:"°", min:10, max:160, step:1, v:60, lo:5, hi:179 },
      { k:"tilt", nm:"셀 기울기", un:"°", min:0, max:90, step:1, v:0, lo:0, hi:90 },
      { k:"speed", nm:"시간 배속 (0.02=초고속카메라)", un:"×", min:0.02, max:3, step:0.02, v:1, lo:0.01, hi:5 },
    ]],
    ["촉매 / 막", [
      { k:"j0_cathode", nm:"음극 j₀ (HER)", un:"A/m²", num:1, v:130, lo:1e-6, hi:1e5 },
      { k:"j0_anode", nm:"양극 겉보기 j₀ (피팅값)", un:"A/m²", num:1, v:1.3e-7, lo:1e-12, hi:1e2 },
      { k:"alpha_a", nm:"양극 α (Tafel 기울기)", un:"–", min:0.3, max:1.6, step:0.01, v:1, lo:0.1, hi:2 },
      { k:"r_mem", nm:"막·접촉 면저항 (피팅값)", un:"Ω·m²", num:1, v:3.2e-6, lo:0, hi:1e-3 },
      { k:"departure_diameter_um", nm:"무유동 이탈직경 (실측 입력)", un:"µm",
        min:20, max:1000, step:2, v:244, lo:2, hi:10000,
        help:"펌프 유동이 없을 때 해당 전극에서 측정한 단일 기포 이탈직경입니다. 기존의 임의 Fritz 배율 대신 사용하며, 미측정 기본값 244 µm는 정량 예측값이 아닙니다." },
      { k:"gap_mm", nm:"전해질 갭 (모델 관례, r_mem과 짝)", un:"mm", min:0.1, max:3, step:0.05, v:2, lo:0.05, hi:10 },
      { k:"C_dl_anode", nm:"양극 이중층 C_dl (EIS 전용)", un:"F/m²", min:0.01, max:2, step:0.01, v:0.2, lo:0.001, hi:100 },
      { k:"C_dl_cathode", nm:"음극 이중층 C_dl (EIS 전용)", un:"F/m²", min:0.01, max:2, step:0.01, v:0.2, lo:0.001, hi:100 },
      { k:"t_mem_um", nm:"막 두께 (건식 음극 물수송·형상)", un:"µm", min:10, max:200, step:5, v:50, lo:1, hi:1000 },
      { k:"t_ptl_um", nm:"PTL 두께 (3D 형상만)", un:"µm", min:50, max:600, step:10, v:200, lo:5, hi:3000 },
    ]],
    // Dry cathode (anolyte-only AEM): the cathode gets NO liquid feed, so every
    // electron's water must cross the membrane — back-diffusion supplies it while
    // the OH- current drags water the other way. OFF by default (both electrodes
    // wetted), so nothing changes until it is switched on.
    ["음극 건식 (물 투과)", [
      { k:"dry_cathode", nm:"음극 건식 (양극에만 전해질)", seg:[["0","꺼짐 (양쪽 습윤)"],["1","켜짐 (건식)"]], v:"0" },
      { k:"n_drag", nm:"전기삼투 끌림 n_drag (OH⁻ 1개가 끌고가는 물)", un:"–", min:0, max:6, step:0.1, v:2.5, lo:0, hi:10 },
      { k:"D_w_mem", nm:"막 내 물 확산계수", un:"m²/s", num:1, v:1e-9, lo:1e-12, hi:1e-7 },
    ]],
    ["환경", [
      { k:"B", nm:"자기장 B (MHD 경험식)", un:"T", min:0, max:3, step:0.05, v:0, lo:0, hi:20 },
      { k:"E", nm:"DEP 기준 전기장 E", un:"MV/m", min:0, max:3, step:0.02, v:0, lo:0, hi:50 },
      { k:"dep_grad_um", nm:"전기장 구배 길이 (모델)", un:"µm", min:10, max:1000, step:10, v:100, lo:1, hi:1e6 },
      { k:"T", nm:"온도", un:"°C", min:20, max:90, step:1, v:60, lo:0, hi:100 },
      { k:"Pbar", nm:"압력", un:"bar", min:1, max:30, step:0.5, v:1, lo:0.1, hi:200 },
    ]],
    ["셀 형상 (격자 재생성)", [
      { k:"W_cm", nm:"전극 폭", un:"cm", min:1, max:20, step:0.5, v:5, lo:0.2, hi:100 },
      { k:"H_cm", nm:"전극 높이", un:"cm", min:1, max:30, step:0.5, v:5, lo:0.2, hi:200 },
      { k:"ff", nm:"유로 형식", seg:[["serp","사행"],["par","병렬"],["inter","교차"],["custom","직접"]], v:"serp" },
      { k:"n_ch", nm:"채널 수", un:"개", min:1, max:20, step:1, v:8, lo:1, hi:200 },
      { k:"w_ch_mm", nm:"채널 폭", un:"mm", min:0.2, max:5, step:0.1, v:1, lo:0.05, hi:20 },
      { k:"d_ch_mm", nm:"채널 깊이 (기포 크기 상한)", un:"mm", min:0.2, max:5, step:0.1, v:1, lo:0.05, hi:20 },
      { k:"w_land_mm", nm:"리브 폭", un:"mm", min:0.2, max:5, step:0.1, v:1, lo:0.05, hi:20 },
      { k:"h_mm", nm:"복셀 한 칸 크기", un:"mm", min:0.4, max:3, step:0.05, v:2, lo:0.4, hi:3,
        help:"3D 계산 격자 한 칸의 실제 길이입니다. 작을수록 유로와 분포가 세밀하지만 계산량이 커집니다." },
    ]],
    // Real boundary conditions, not decoration: the inlet is the prescribed
    // normal velocity on y=0, the outlet is the Dirichlet p=0 face on y=Ly.
    // Narrowing the outlet turns the rest of the top into PLATE — liquid and
    // gas both have to find the port.
    ["포트 (입구 · 출구)", [
      { k:"in_face", nm:"입구 면", seg:[["bottom","아래"],["left","왼쪽"],["right","오른쪽"]], v:"bottom" },
      { k:"in_w", nm:"입구 폭 (0 = 형식 기본값)", un:"–", min:0, max:1, step:0.02, v:0, lo:0, hi:1 },
      { k:"in_z", nm:"입구 위치 (그 변을 따라)", un:"–", min:0, max:1, step:0.01, v:0.94, lo:0, hi:1 },
      { k:"out_face", nm:"출구 면", seg:[["top","위"],["left","왼쪽"],["right","오른쪽"]], v:"top" },
      { k:"out_w", nm:"출구 폭 (0=자동, 1=면 전체)", un:"–", min:0, max:1, step:0.02, v:0, lo:0, hi:1 },
      { k:"out_z", nm:"출구 위치 (그 변을 따라)", un:"–", min:0, max:1, step:0.01, v:0.06, lo:0, hi:1 },
    ]],
  ];

  const near = (a, b) => Math.abs(+a - +b) <= Math.max(1e-9, Math.abs(+b) * 1e-6);

  /** Build one group list into `host`. Returns { sync } to pull server state. */
  g.buildControls = function (host, groups, P, send) {
    const reg = {};                     // key -> setter used by sync()
    const rows = {};
    // Polling runs faster than the debounced POST.  Without a short acknowledgement
    // window, the next poll can overwrite a value the user has just selected with
    // the server's previous value, making segmented buttons appear unresponsive.
    const pendingAck = {};               // key -> { value, until }
    const sameValue = (a, b) => {
      const an = +a, bn = +b;
      return Number.isFinite(an) && Number.isFinite(bn)
        ? near(an, bn) : String(a) === String(b);
    };
    const publish = (c, value) => {
      P[c.k] = value;
      if (c.local) return;
      // Leaving the directly drawn plate must also release its authoritative
      // mask. Otherwise the UI says "serpentine/parallel/interdigitated" while
      // the solver and 3-D ribs keep rendering the previous custom drawing.
      // send() is debounced, so mask + ff travel in one /api3d/op rebuild.
      if (c.k === "ff" && value !== "custom") {
        P.mask = "";
        pendingAck.mask = { value: "", until: Date.now() + 1500 };
        send("mask", "");
      }
      pendingAck[c.k] = { value, until: Date.now() + 1500 };
      send(c.k, value);
    };

    const refreshDependencies = () => {
      const disabled = {
        j: String(P.mode) === "CA",
        V_cell: String(P.mode) !== "CA",
        n_drag: ![1, "1", true].includes(P.dry_cathode),
        D_w_mem: ![1, "1", true].includes(P.dry_cathode),
        bcount: String(P.bview || "move") === "move",
        trace: String(P.bview || "move") === "dist",
      };
      for (const [k, off] of Object.entries(disabled)) {
        const row = rows[k]; if (!row) continue;
        row.style.opacity = off ? ".42" : "";
        row.querySelectorAll("input,button,select").forEach(x => x.disabled = off);
        row.setAttribute("aria-disabled", off ? "true" : "false");
      }
    };

    for (const [title, items] of groups) {
      const box = document.createElement("div"); box.className = "box";
      box.insertAdjacentHTML("beforeend", `<h3>${title}</h3>`);

      for (const c of items) {
        P[c.k] = c.v;
        const row = document.createElement("div"); row.className = "ctl";
        row.dataset.key = c.k; rows[c.k] = row;
        const appendHelp = () => {
          if (!c.help) return;
          row.insertAdjacentHTML("beforeend",
            `<div class="ctlHelp" style="margin-top:3px;color:var(--dim);font-size:10px;line-height:1.45">${c.help}</div>`);
          row.title = c.help;
        };

        if (c.seg) {
          row.insertAdjacentHTML("beforeend",
            `<div class="lab"><span class="nm">${c.nm}</span></div>`);
          const seg = document.createElement("div"); seg.className = "seg mini";
          seg.setAttribute("role", "group"); seg.setAttribute("aria-label", c.nm);
          for (const [val, label] of c.seg) {
            const b = document.createElement("button");
            b.textContent = label; b.dataset.v = val;
            b.setAttribute("aria-pressed", val === c.v ? "true" : "false");
            if (val === c.v) b.classList.add("on");
            b.onclick = () => {
              seg.querySelectorAll("button").forEach(x => {
                x.classList.remove("on"); x.setAttribute("aria-pressed", "false");
              });
              b.setAttribute("aria-pressed", "true");
              b.classList.add("on"); publish(c, val);
              refreshDependencies();
            };
            seg.appendChild(b);
          }
          row.appendChild(seg); appendHelp(); box.appendChild(row);
          reg[c.k] = v => {
            if (P[c.k] === v) return;
            P[c.k] = v;
            seg.querySelectorAll("button").forEach(x => {
              const on = x.dataset.v === String(v); x.classList.toggle("on", on);
              x.setAttribute("aria-pressed", on ? "true" : "false");
            });
            refreshDependencies();
          };
          continue;
        }

        if (c.num) {                     // number-only (wide range: j0, r_mem)
          row.innerHTML =
            `<div class="lab"><span class="nm">${c.nm}</span><span class="un hint">${c.un}</span></div>
             <div class="ri"><input type="number" step="any" value="${c.v}" style="width:100%"></div>`;
          const nu = row.querySelector("input[type=number]");
          nu.setAttribute("aria-label", `${c.nm} (${c.un || ""})`);
          nu.addEventListener("change", () => {
            let x = Math.max(c.lo, Math.min(c.hi, +nu.value));
            if (!isFinite(x)) x = c.v;
            nu.value = x; publish(c, x);
          });
          appendHelp(); box.appendChild(row);
          reg[c.k] = v => {
            if (document.activeElement === nu || near(P[c.k], v)) return;
            P[c.k] = +v; nu.value = v;
          };
          continue;
        }

        // slider + typed box (the box accepts values beyond the slider range,
        // clamped to the physical limits lo..hi)
        row.innerHTML =
          `<div class="lab"><span class="nm">${c.nm}</span><span class="un hint">${c.un}</span></div>
           <div class="ri"><input type="range" min="${c.min}" max="${c.max}" step="${c.step}" value="${c.v}">
           <input type="number" step="${c.step}" value="${c.v}"></div>`;
        const sl = row.querySelector("input[type=range]");
        const nu = row.querySelector("input[type=number]");
        sl.setAttribute("aria-label", `${c.nm} 슬라이더`);
        nu.setAttribute("aria-label", `${c.nm} (${c.un || ""})`);
        const apply = x => { publish(c, x); refreshDependencies(); };
        sl.addEventListener("input", () => { nu.value = sl.value; apply(+sl.value); });
        nu.addEventListener("change", () => {
          let x = Math.max(c.lo, Math.min(c.hi, +nu.value)); if (!isFinite(x)) x = c.v;
          nu.value = x; sl.value = Math.max(c.min, Math.min(c.max, x)); apply(x);
        });
        appendHelp(); box.appendChild(row);
        reg[c.k] = v => {
          const busy = document.activeElement === nu || document.activeElement === sl;
          if (busy || near(P[c.k], v)) return;
          P[c.k] = +v; nu.value = v;
          sl.value = Math.max(c.min, Math.min(c.max, +v));
        };
      }
      host.appendChild(box);
    }

    /** Pull the server's authoritative state into the widgets (both tabs agree). */
    function sync(designer, speed) {
      if (!designer) return;
      for (const k in reg) {
        const v = (k === "speed") ? speed : designer[k];
        if (v === undefined || v === null) continue;
        const pending = pendingAck[k];
        if (pending) {
          if (sameValue(pending.value, v)) delete pendingAck[k];
          else if (Date.now() < pending.until) continue;
          else delete pendingAck[k];
        }
        reg[k](v);
      }
      refreshDependencies();
    }
    refreshDependencies();
    return { sync, reg };
  };

  /* ---- volumetric pump flow <-> channel velocity -------------------------
   * A pump is set in mL/min; the solvers need the CHANNEL VELOCITY u [m/s].
   * The two are one geometric step apart:
   *      Q = u * A_ch,   A_ch = w_ch * d_ch * (parallel channels in the field)
   * A serpentine is ONE continuous channel, so all the flow goes through a
   * single cross-section; parallel/interdigitated split it over n_ch.
   * (The 1-D channel model's gas:liquid only needs u*d_ch — the width cancels
   * — but the VOLUME the user's pump delivers does depend on w_ch, which is
   * exactly why the m/s knob felt wrong.)
   */
  g.chanArea_m2 = function (d) {
    const w = Math.max(1e-4, +d.w_ch_mm || 1) * 1e-3;
    const dp = Math.max(1e-4, +d.d_ch_mm || 1) * 1e-3;
    const par = (d.ff === "par" || d.ff === "inter")
      ? Math.max(1, Math.round(+d.n_ch || 1)) : 1;   // serpentine/custom: one path
    return w * dp * par;
  };
  g.flowMLmin = d => (+d.u_flow || 0) * g.chanArea_m2(d) * 60e6;   // m3/s -> mL/min
  g.flowToU = (mlmin, d) => Math.max(0, mlmin) / 60e6 / g.chanArea_m2(d);

  /* ---- shared CSV export (both pages, per-panel buttons) -----------------
   * Every file is UTF-8 BOM (Excel opens Korean correctly) and carries the
   * full condition as `# key,value` comment rows, so a folder of exports is
   * self-describing and comparable. */
  g.CSV_KEYS = ["ff","n_ch","W_cm","H_cm","w_ch_mm","d_ch_mm","w_land_mm","h_mm",
    "mode","j","V_cell","u_flow","electrolyte","c_mol","T","Pbar","theta","tilt",
    "departure_diameter_um","dep_grad_um",
    "j0_cathode","j0_anode","alpha_a","r_mem","gap_mm","t_mem_um","C_dl_anode","C_dl_cathode",
    "t_ptl_um","void_frac","mesh_id","mesh_cover","mesh_pos","mesh_theta",
    "dry_cathode","n_drag","D_w_mem","in_face","in_z","in_w","out_face","out_z","out_w"];
  function csvCell(v){ if(v==null) return ""; const s=String(v);
    return /[",\n]/.test(s) ? '"'+s.replace(/"/g,'""')+'"' : s; }
  // rows = array of arrays. designer = the condition dict (optional).
  g.csvDownload = function(name, rows, designer, title){
    const out = [];
    if (title) out.push(["# "+title]);
    out.push(["# 내보낸 시각", new Date().toLocaleString("ko-KR")]);
    if (designer){
      if (g.flowMLmin && designer.u_flow!=null){
        out.push(["# 펌프유량_mL_per_min", +g.flowMLmin(designer).toFixed(3)]);
        out.push(["# 유로단면_mm2", +(g.chanArea_m2(designer)*1e6).toFixed(4)]);
      }
      out.push(["# --- 조건 (designer) ---"]);
      for (const k of g.CSV_KEYS) if (designer[k]!==undefined) out.push(["# "+k, designer[k]]);
      out.push([]);
    }
    const body = out.concat(rows).map(r=>r.map(csvCell).join(",")).join("\r\n");
    const blob = new Blob(["﻿"+body], {type:"text/csv;charset=utf-8;"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    const t = new Date(), p = n => String(n).padStart(2,"0");
    a.download = `${name}_${t.getFullYear()}${p(t.getMonth()+1)}${p(t.getDate())}`
              + `_${p(t.getHours())}${p(t.getMinutes())}${p(t.getSeconds())}.csv`;
    document.body.appendChild(a); a.click();
    setTimeout(()=>{ URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    g.csvDownload._last = a.download;    // headless verify
    return a.download;
  };

  /* ---- drag-to-move + corner-resize for a floating/dashboard panel ---------
   * Drag ANYWHERE on the panel (except form controls / [data-nodrag] / a canvas
   * that handles clicks) to move it — window style, no thin title-bar to hunt
   * for. A click (no real move) does NOT float it; only a >4 px drag does. Any
   * pointerdown raises it to the FRONT. Corner-drag resizes (native CSS). Layout
   * persists per `key` in localStorage; DOUBLE-CLICK the header resets it. */
  g._zTop = g._zTop || 60;
  g.dragResize = function (el, handle, key) {
    if (!el) return;
    handle = handle || el;                     // default: the whole panel is the grip
    const mobileLayout = matchMedia("(max-width:900px)");
    const syncInputMode = () => {
      el.style.resize = mobileLayout.matches ? "none" : "both";
      handle.style.touchAction = mobileLayout.matches ? "pan-y" : "none";
    };
    syncInputMode();
    mobileLayout.addEventListener("change", syncInputMode);
    if (getComputedStyle(el).overflow === "visible") el.style.overflow = "auto";
    let saveT = null;
    const save = () => {
      clearTimeout(saveT);
      saveT = setTimeout(() => {
        try {
          localStorage.setItem(key, JSON.stringify({
            l: el.style.left, t: el.style.top, w: el.style.width, h: el.style.height,
            z: el.style.zIndex }));
        } catch (e) {}
      }, 250);
    };
    const toFront = () => { el.style.zIndex = (g._zTop += 1); };
    const lift = () => {                       // move out of flow, keep on-screen
      if (el._floated) return;
      const r = el.getBoundingClientRect();
      el.style.position = "fixed";
      el.style.left = r.left + "px"; el.style.top = r.top + "px";
      el.style.width = r.width + "px"; el.style.height = r.height + "px";
      el.style.right = "auto"; el.style.bottom = "auto";
      el.style.margin = "0"; el._floated = true; toFront();
    };
    // restore a saved layout
    try {
      const s = JSON.parse(localStorage.getItem(key) || "null");
      if (s && (s.l || s.t)) {
        el.style.position = "fixed"; el.style.right = "auto"; el.style.bottom = "auto";
        el.style.margin = "0"; el._floated = true;
        // clamp the saved position into the CURRENT viewport — a layout saved on
        // a wide screen (or before the window shrank) could otherwise restore the
        // panel fully off-screen with no way to drag it back.
        const L = parseFloat(s.l), T = parseFloat(s.t);
        if (isFinite(L)) el.style.left = Math.max(0, Math.min(innerWidth - 40, L)) + "px";
        if (isFinite(T)) el.style.top = Math.max(0, Math.min(innerHeight - 30, T)) + "px";
        if (s.w) el.style.width = s.w; if (s.h) el.style.height = s.h;
        el.style.zIndex = s.z || (g._zTop += 1);
      }
    } catch (e) {}
    // ANY pointerdown on the panel brings it to the front (so clicking a chart —
    // not just the box border — raises it above overlapping panels)
    el.addEventListener("pointerdown", () => {
      if (!mobileLayout.matches && el._floated) toFront();
    }, true);
    // drag with a 4 px threshold so a plain click never floats the panel
    const NODRAG = "input,button,select,textarea,a,label,[data-nodrag]";
    let sx, sy, ox, oy, armed = false, dragging = false, pid = null;
    handle.addEventListener("pointerdown", e => {
      if (mobileLayout.matches) return;
      if (e.target.closest(NODRAG)) return;
      // the bottom-right ~20 px is the native CSS resize grip — leave it to
      // resize, don't also start a MOVE (that double-action felt broken)
      const r = el.getBoundingClientRect();
      if (e.clientX > r.right - 20 && e.clientY > r.bottom - 20) return;
      armed = true; dragging = false; pid = e.pointerId; sx = e.clientX; sy = e.clientY;
    });
    handle.addEventListener("pointermove", e => {
      if (!armed) return;
      if (!dragging) {
        if (Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) < 4) return;
        dragging = true; lift();
        ox = parseFloat(el.style.left) || 0; oy = parseFloat(el.style.top) || 0;
        try { handle.setPointerCapture(pid); } catch (er) {}
        handle.style.cursor = "grabbing";
      }
      const mw = innerWidth - 40, mh = innerHeight - 30;
      el.style.left = Math.max(-el.offsetWidth + 60, Math.min(mw, ox + e.clientX - sx)) + "px";
      el.style.top = Math.max(0, Math.min(mh, oy + e.clientY - sy)) + "px";
      e.preventDefault();
    });
    const end = e => { if (dragging) save(); dragging = false; armed = false;
      handle.style.cursor = ""; try { handle.releasePointerCapture(pid); } catch (er) {} };
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    // native corner-resize: the browser sets el.style.width/height inline. On
    // the closing mouseup, if a size was set (or the panel already floats), float
    // it (so the size persists in place) and save. This does NOT rely on
    // ResizeObserver (absent in some embedded viewers); RO, when present, just
    // keeps the saved size live during the drag.
    const endResize = () => {
      if (mobileLayout.matches) return;
      if (el.style.width || el.style.height || el._floated) {
        if (!el._floated) lift(); save();
      }
    };
    el.addEventListener("mouseup", endResize);
    el.addEventListener("pointerup", endResize);
    if (window.ResizeObserver) new ResizeObserver(() => { if (el._floated) save(); }).observe(el);
    // double-click the header: reset to default layout
    handle.addEventListener("dblclick", () => {
      if (mobileLayout.matches) return;
      try { localStorage.removeItem(key); } catch (e) {}
      el._floated = false;
      for (const p of ["position","left","top","right","bottom","width","height","zIndex","margin"])
        el.style[p] = "";
      el.style.resize = "both"; el.style.overflow = "auto";
    });
  };
})(window);
