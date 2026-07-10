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
      { k:"theta", nm:"접촉각 (이탈 크기)", un:"°", min:10, max:160, step:1, v:60, lo:5, hi:179 },
      { k:"drag_K", nm:"기포 유동차단 세기", un:"/s", min:0, max:200, step:5, v:60, lo:0, hi:1000 },
      { k:"tilt", nm:"셀 기울기", un:"°", min:0, max:90, step:1, v:0, lo:0, hi:90 },
      { k:"speed", nm:"시간 배속 (0.02=초고속카메라)", un:"×", min:0.02, max:3, step:0.02, v:1, lo:0.01, hi:5 },
    ]],
    ["촉매 / 막", [
      { k:"j0_cathode", nm:"음극 j₀ (HER)", un:"A/m²", num:1, v:130, lo:1e-6, hi:1e5 },
      { k:"j0_anode", nm:"양극 j₀ (OER)", un:"A/m²", num:1, v:1.3e-7, lo:1e-12, hi:1e2 },
      { k:"alpha_a", nm:"양극 α (Tafel 기울기)", un:"–", min:0.3, max:1.6, step:0.01, v:1, lo:0.1, hi:2 },
      { k:"r_mem", nm:"막 면저항", un:"Ω·m²", num:1, v:3.2e-6, lo:0, hi:1e-3 },
      { k:"gap_mm", nm:"전해질 갭 (모델 관례, r_mem과 짝)", un:"mm", min:0.1, max:3, step:0.05, v:2, lo:0.05, hi:10 },
      { k:"t_mem_um", nm:"막 두께", un:"µm", min:10, max:200, step:5, v:50, lo:1, hi:1000 },
      { k:"t_ptl_um", nm:"PTL 두께", un:"µm", min:50, max:600, step:10, v:200, lo:5, hi:3000 },
      { k:"eps_ptl", nm:"PTL 공극률", un:"–", min:0.3, max:0.9, step:0.01, v:0.7, lo:0.05, hi:0.95 },
    ]],
    ["환경", [
      { k:"B", nm:"자기장 B", un:"T", min:0, max:3, step:0.05, v:0, lo:0, hi:20 },
      { k:"E", nm:"전기장 E", un:"MV/m", min:0, max:3, step:0.02, v:0, lo:0, hi:50 },
      { k:"T", nm:"온도", un:"°C", min:20, max:90, step:1, v:60, lo:0, hi:250 },
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
      { k:"h_mm", nm:"복셀 해상도 (작을수록 정밀↑ 속도↓)", un:"mm", min:0.4, max:3, step:0.05, v:2, lo:0.4, hi:3 },
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
      { k:"out_w", nm:"출구 폭 (1 = 그 면 전체)", un:"–", min:0.02, max:1, step:0.02, v:1, lo:0.01, hi:1 },
      { k:"out_z", nm:"출구 위치 (그 변을 따라)", un:"–", min:0, max:1, step:0.01, v:0.06, lo:0, hi:1 },
    ]],
  ];

  const near = (a, b) => Math.abs(+a - +b) <= Math.max(1e-9, Math.abs(+b) * 1e-6);

  /** Build one group list into `host`. Returns { sync } to pull server state. */
  g.buildControls = function (host, groups, P, send) {
    const reg = {};                     // key -> setter used by sync()

    for (const [title, items] of groups) {
      const box = document.createElement("div"); box.className = "box";
      box.insertAdjacentHTML("beforeend", `<h3>${title}</h3>`);

      for (const c of items) {
        P[c.k] = c.v;
        const row = document.createElement("div"); row.className = "ctl";

        if (c.seg) {
          row.insertAdjacentHTML("beforeend",
            `<div class="lab"><span class="nm">${c.nm}</span></div>`);
          const seg = document.createElement("div"); seg.className = "seg mini";
          for (const [val, label] of c.seg) {
            const b = document.createElement("button");
            b.textContent = label; b.dataset.v = val;
            if (val === c.v) b.classList.add("on");
            b.onclick = () => {
              seg.querySelectorAll("button").forEach(x => x.classList.remove("on"));
              b.classList.add("on"); P[c.k] = val;
              if (!c.local) send(c.k, val);
            };
            seg.appendChild(b);
          }
          row.appendChild(seg); box.appendChild(row);
          reg[c.k] = v => {
            if (P[c.k] === v) return;
            P[c.k] = v;
            seg.querySelectorAll("button").forEach(
              x => x.classList.toggle("on", x.dataset.v === String(v)));
          };
          continue;
        }

        if (c.num) {                     // number-only (wide range: j0, r_mem)
          row.innerHTML =
            `<div class="lab"><span class="nm">${c.nm}</span><span class="un hint">${c.un}</span></div>
             <div class="ri"><input type="number" step="any" value="${c.v}" style="width:100%"></div>`;
          const nu = row.querySelector("input[type=number]");
          nu.addEventListener("change", () => {
            let x = Math.max(c.lo, Math.min(c.hi, +nu.value));
            if (!isFinite(x)) x = c.v;
            nu.value = x; P[c.k] = x; if (!c.local) send(c.k, x);
          });
          box.appendChild(row);
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
        const apply = x => { P[c.k] = x; if (!c.local) send(c.k, x); };
        sl.addEventListener("input", () => { nu.value = sl.value; apply(+sl.value); });
        nu.addEventListener("change", () => {
          let x = Math.max(c.lo, Math.min(c.hi, +nu.value)); if (!isFinite(x)) x = c.v;
          nu.value = x; sl.value = Math.max(c.min, Math.min(c.max, x)); apply(x);
        });
        box.appendChild(row);
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
        if (v !== undefined && v !== null) reg[k](v);
      }
    }
    return { sync, reg };
  };
})(window);
