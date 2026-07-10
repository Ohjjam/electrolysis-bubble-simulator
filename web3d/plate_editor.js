/* Draw-your-own flow field — shared by app2d and app3d.
 *
 * The canvas is a MASK_N x MASK_N picture of the plate seen from the electrode:
 * z runs left->right (cell width), y runs bottom->top (flow / buoyancy). A
 * painted cell is LAND (rib); an empty cell is CHANNEL. The mask is sent to the
 * server as a '0'/'1' string and becomes `cfg.land_mask`, which `voxelize()`
 * resamples onto whatever grid the current cell size implies — so a drawing
 * survives a change of electrode size or voxel count.
 *
 * The inlet (green, bottom) and outlet (red, top) are drawn from the ports the
 * ENGINE actually applies (`state.ports`), not from the slider values, so what
 * you see is the boundary condition the projection solves against.
 *
 *   mountPlateEditor(host, { P, send, reg })  ->  { sync(state) }
 */
(function (g) {
  "use strict";

  const N = 32;                     // editor resolution (z, y)

  g.MASK_N = N;

  g.mountPlateEditor = function (host, { P, send, reg }) {
    let mask = new Uint8Array(N * N);          // row-major, row 0 = inlet (y=0)
    let ports = null, painting = 0, brush = 1, dirty = false;

    host.className = "box";
    host.innerHTML = `
      <h3>유로 직접 그리기</h3>
      <div class="hint" style="margin-bottom:6px;line-height:1.35">
        칠한 칸 = <b>리브(막힘)</b>, 빈 칸 = <b>채널</b>. 드래그로 칠하고
        <b>Shift+드래그</b>로 지웁니다. 그리면 유로 형식이 <b>직접</b>으로 바뀝니다.<br>
        아래 초록 = 입구, 위 빨강 = 출구 (엔진이 실제로 적용하는 경계).
      </div>
      <canvas id="peCv" width="${N * 12}" height="${N * 12}"
              style="width:100%;display:block;border:1px solid var(--line);
                     border-radius:8px;cursor:crosshair;touch-action:none"></canvas>
      <div class="ri" style="margin-top:7px">
        <span class="hint" style="flex:none">붓</span>
        <input id="peBrush" type="range" min="1" max="4" step="1" value="1">
        <span class="hint" id="peBrushN" style="flex:none;width:12px">1</span>
      </div>
      <div class="row" style="display:flex;gap:6px;margin-top:6px">
        <button class="btn" id="peLoad">현재 형식 불러오기</button>
        <button class="btn" id="peClear">비우기</button>
        <button class="btn" id="peInvert">반전</button>
      </div>
      <div class="hint" id="peStat" style="margin-top:6px">–</div>`;

    const cv = host.querySelector("#peCv");
    const ctx = cv.getContext("2d");
    const css = getComputedStyle(document.documentElement);
    const V = (n, fb) => (css.getPropertyValue(n) || fb).trim() || fb;
    const COL = { land: V("--cv-land", "#aab4c4"), ch: V("--cv-liq", "#e9f1fa"),
                  grid: V("--line", "#d6dce6"), inl: V("--grn", "#0f8a63"),
                  out: V("--warn", "#c9333f"), dim: V("--dim", "#68738a") };

    const at = (j, k) => mask[j * N + k];
    const set = (j, k, v) => { if (j >= 0 && j < N && k >= 0 && k < N) mask[j * N + k] = v; };

    function draw() {
      const w = cv.width, h = cv.height, c = w / N;
      ctx.fillStyle = COL.ch; ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = COL.land;
      for (let j = 0; j < N; j++) for (let k = 0; k < N; k++) {
        if (at(j, k)) ctx.fillRect(k * c, h - (j + 1) * c, c, c);   // y up
      }
      ctx.strokeStyle = COL.grid; ctx.lineWidth = 0.5; ctx.globalAlpha = 0.7;
      for (let i = 0; i <= N; i += 4) {
        ctx.beginPath(); ctx.moveTo(i * c, 0); ctx.lineTo(i * c, h); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, i * c); ctx.lineTo(w, i * c); ctx.stroke();
      }
      ctx.globalAlpha = 1;
      // ports, drawn on the edge the ENGINE actually put them on. `in`/`out`
      // are indexed along z for bottom/top and along y for left/right.
      const bar = Math.max(4, c * 0.5);
      if (ports) {
        const edge = (arr, face, col) => {
          ctx.fillStyle = col;
          for (let i = 0; i < N; i++) {
            if (face === "bottom" || face === "top") {
              const kk = Math.min(ports.nz - 1, Math.floor((i + 0.5) / N * ports.nz));
              if (arr[kk]) ctx.fillRect(i * c, face === "bottom" ? h - bar : 0, c, bar);
            } else {
              const jj = Math.min(ports.ny - 1, Math.floor((i + 0.5) / N * ports.ny));
              // row j = 0 is the inlet edge, drawn at the BOTTOM of the canvas
              if (arr[jj]) ctx.fillRect(face === "left" ? 0 : w - bar,
                                        h - (i + 1) * c, bar, c);
            }
          }
        };
        edge(ports.in, ports.in_face || "bottom", COL.inl);
        edge(ports.out, ports.out_face || "top", COL.out);
      }
      const nLand = mask.reduce((a, b) => a + b, 0);
      // A drawn plate fed through the WHOLE bottom row (in_w = 0) squeezes the
      // full pump flow through whatever gap you left: measured 2.9 m/s where the
      // pump asks for 0.35. That is real, but it is rarely what you meant.
      const jetRisk = P.ff === "custom" && +P.in_w === 0;
      host.querySelector("#peStat").innerHTML =
        `리브 <b style="color:var(--tx)">${(100 * nLand / (N * N)).toFixed(0)}%</b> · ` +
        `${N}×${N} 격자 (물리 격자에 자동 리샘플)` +
        (P.ff === "custom" ? "" : ` · <span style="color:var(--dim)">아직 적용 안 됨 — 그리면 적용</span>`) +
        (jetRisk ? `<br><span style="color:var(--gold)">입구 폭 = 0 (바닥 전체 급수)</span>` +
                   `<span style="color:var(--dim)"> — 좁은 틈으로 유량이 몰려 제트가 생깁니다. ` +
                   `포트 폭을 0.1 정도로 지정해 보세요.</span>` : "");
    }

    function cellAt(ev) {
      const r = cv.getBoundingClientRect();
      const k = Math.floor((ev.clientX - r.left) / r.width * N);
      const j = N - 1 - Math.floor((ev.clientY - r.top) / r.height * N);
      return [j, k];
    }
    function paint(ev) {
      const [j, k] = cellAt(ev);
      const v = ev.shiftKey ? 0 : 1;
      const b = brush - 1;
      for (let dj = -b; dj <= b; dj++) for (let dk = -b; dk <= b; dk++) set(j + dj, k + dk, v);
      dirty = true; draw();
    }
    function commit() {
      if (!dirty) return;
      dirty = false;
      // switch the flow field over to the drawing and push it in one batch
      if (P.ff !== "custom") { P.ff = "custom"; send("ff", "custom"); reg.ff && reg.ff("custom"); }
      send("mask", Array.from(mask, v => (v ? "1" : "0")).join(""));
    }

    cv.addEventListener("pointerdown", e => {
      painting = 1; cv.setPointerCapture(e.pointerId); paint(e); e.preventDefault();
    });
    cv.addEventListener("pointermove", e => { if (painting) paint(e); });
    cv.addEventListener("pointerup", () => { painting = 0; commit(); });
    cv.addEventListener("pointercancel", () => { painting = 0; commit(); });
    cv.addEventListener("contextmenu", e => e.preventDefault());

    const brushSl = host.querySelector("#peBrush");
    brushSl.oninput = () => { brush = +brushSl.value; host.querySelector("#peBrushN").textContent = brush; };

    host.querySelector("#peClear").onclick = () => { mask.fill(0); dirty = true; draw(); commit(); };
    host.querySelector("#peInvert").onclick = () => {
      for (let i = 0; i < mask.length; i++) mask[i] ^= 1;
      dirty = true; draw(); commit();
    };
    // seed the canvas from whatever the engine is running right now, so the
    // user starts from a real serpentine/parallel plate instead of a blank sheet
    host.querySelector("#peLoad").onclick = () => {
      if (!lastLand) return;
      const { ny, nz, m } = lastLand;
      for (let j = 0; j < N; j++) for (let k = 0; k < N; k++) {
        const jj = Math.min(ny - 1, Math.floor((j + 0.5) / N * ny));
        const kk = Math.min(nz - 1, Math.floor((k + 0.5) / N * nz));
        mask[j * N + k] = m[jj * nz + kk] ? 1 : 0;
      }
      dirty = true; draw(); commit();
    };

    let lastLand = null;
    draw();

    return {
      sync(st) {
        if (!st) return;
        if (st.land2d) lastLand = st.land2d;
        if (st.ports) { ports = st.ports; }
        draw();
      },
    };
  };
})(window);
