/* Draw-your-own flow field — shared by app2d and app3d.
 *
 * The canvas is a picture of the plate seen from the electrode, drawn at the
 * PHYSICS GRID resolution: z runs left->right (cell width), y runs bottom->top
 * (flow / buoyancy). A painted cell is LAND (rib); an empty cell is CHANNEL.
 * One drawn square = one solver cell, so what you draw is exactly what runs.
 *
 * (Drawing on a fixed 32x32 canvas and letting `voxelize()` downsample it was
 * the original design and it was broken: nearest-neighbour resampling of 32 rows
 * onto a 25-cell grid never samples 7 of them, so a one-cell rib drawn on 22% of
 * the rows silently did not exist. When the grid itself changes -- electrode
 * size, channel depth -- the drawing is carried across once, area-weighted.)
 *
 * The mask travels as 'ny,nz:0101...' so the shape rides with the bits.
 *
 * DRAWING, not pixel-pushing. Real ribs are straight bars, so the default tool
 * is an axis-snapped LINE; there is a rectangle, a free brush, undo/redo, a
 * mirror mode, and a large pop-out view (a 25-cell grid inside a 300 px panel
 * gives 12 px cells, which is not something you can aim at).
 *
 * The engine rebuilds its whole voxel grid — and restarts the bubble population
 * — every time the mask changes, so edits are COALESCED: a stroke lands
 * immediately on the canvas and is pushed to the server after a short quiet
 * period. The canvas also mirrors the running plate whenever the flow field is a
 * preset, so you start from what you can see rather than from a blank sheet.
 *
 * The inlet (green) and outlet (red) are drawn on the edge the ENGINE actually
 * put them on (`state.ports`), not from the slider values.
 *
 *   mountPlateEditor(host, { P, send, reg })  ->  { sync(state) }
 */
(function (g) {
  "use strict";

  const SEND_QUIET_MS = 450;        // coalesce edits before the grid rebuild
  const MAX_UNDO = 60;

  g.MASK_N = () => (g.__peState ? g.__peState().NY : 0);   // legacy accessor

  /** (n_out, n_in) fractional-overlap rows, each summing to 1. */
  function overlap(nOut, nIn) {
    const W = [];
    for (let o = 0; o < nOut; o++) {
      const lo = o * nIn / nOut, hi = (o + 1) * nIn / nOut, row = new Float64Array(nIn);
      let tot = 0;
      for (let i = Math.floor(lo); i < Math.min(Math.ceil(hi), nIn); i++) {
        row[i] = Math.max(0, Math.min(hi, i + 1) - Math.max(lo, i)); tot += row[i];
      }
      if (tot > 0) for (let i = 0; i < nIn; i++) row[i] /= tot;
      W.push(row);
    }
    return W;
  }

  g.mountPlateEditor = function (host, { P, send, reg }) {
    // The editor grid IS the physics grid: no resampling, so what you draw is
    // exactly what the solver runs. (Drawing on a finer canvas and downsampling
    // silently DELETED 22% of the rows — a rib you drew could simply not exist.)
    let NY = 25, NZ = 25;
    let mask = new Uint8Array(NY * NZ);      // row-major, row 0 = inlet (y=0)
    let ports = null, lastLand = null, cellMM = null;
    let tool = "line", erase = false, brush = 1, mirror = false;
    let drag = null, hover = null;
    let undo = [], redo = [], sendTimer = null, pending = false;

    host.className = "box";
    host.innerHTML = `
      <h3>유로 직접 그리기</h3>
      <div class="pe-tools">
        <button class="btn pe-t" data-tool="line" title="직선 리브 — 축에 자동 정렬 (Alt = 자유각)">직선</button>
        <button class="btn pe-t" data-tool="rect" title="채워진 사각형">사각형</button>
        <button class="btn pe-t" data-tool="brush" title="자유 붓">붓</button>
        <button class="btn pe-t" data-tool="erase" title="지우개 — 어느 도구에서든 Shift 또는 우클릭">지우개</button>
      </div>
      <div class="ri" style="margin-top:6px">
        <span class="hint" style="flex:none">굵기</span>
        <input class="pe-brush" type="range" min="1" max="5" step="1" value="1">
        <span class="hint pe-brushn" style="flex:none;width:10px">1</span>
        <label class="pe-chk"><input class="pe-mirror" type="checkbox"> 좌우대칭</label>
      </div>
      <canvas class="pe-cv" width="512" height="512"></canvas>
      <div class="pe-tools" style="margin-top:6px">
        <button class="btn pe-undo" title="Ctrl+Z">↶ 되돌리기</button>
        <button class="btn pe-redo" title="Ctrl+Y">↷ 다시</button>
        <button class="btn pe-big">⤢ 크게</button>
      </div>
      <div class="pe-tools" style="margin-top:6px">
        <button class="btn pe-load">현재 유로 불러오기</button>
        <button class="btn pe-clear">비우기</button>
        <button class="btn pe-inv">반전</button>
      </div>
      <div class="hint pe-stat" style="margin-top:6px">–</div>`;

    if (!document.getElementById("pe-style")) {
      const st = document.createElement("style");
      st.id = "pe-style";
      st.textContent = `
        /* self-contained: app2d has no .btn rule of its own */
        .pe-tools .btn, #pe-overlay .btn{background:var(--surf,#f3f6fb);color:var(--tx,#1a2331);
          border:1px solid var(--line,#d6dce6);border-radius:8px;cursor:pointer;font:inherit}
        .pe-tools .btn:hover:not(:disabled), #pe-overlay .btn:hover{border-color:var(--accent)}
        .pe-tools{display:flex;gap:5px}
        .pe-tools .btn{flex:1;padding:5px 2px;font-size:11.5px}
        .pe-tools .btn:disabled{opacity:.4;cursor:default}
        .pe-t.on{border-color:var(--accent);color:var(--accent);background:var(--surf2);font-weight:600}
        .pe-chk{display:flex;align-items:center;gap:4px;flex:none;font-size:11px;color:var(--dim);cursor:pointer}
        .pe-cv{width:100%;aspect-ratio:1;display:block;margin-top:7px;border:1px solid var(--line);
               border-radius:8px;cursor:crosshair;touch-action:none;background:var(--cv-liq,#e9f1fa)}
        .pe-dirty{color:var(--gold)}
        #pe-overlay{position:fixed;inset:0;z-index:200;background:rgba(15,22,33,.55);
                    display:flex;align-items:center;justify-content:center;backdrop-filter:blur(3px)}
        #pe-overlay .wrap{background:var(--card);border:1px solid var(--line);border-radius:14px;
                          padding:14px;box-shadow:0 20px 60px rgba(20,32,52,.25)}
        /* clamp, not bare vmin: some embedded viewports report 0 and the canvas
           collapses to a couple of pixels */
        #pe-overlay canvas{width:clamp(300px, 78vmin, 900px);height:auto;aspect-ratio:1;
                           display:block;border:1px solid var(--line);border-radius:10px;
                           cursor:crosshair;touch-action:none;background:var(--cv-liq,#e9f1fa)}
        #pe-overlay .hd{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;
                        font-size:13px;font-weight:600;gap:16px}`;
      document.head.appendChild(st);
    }

    const $ = q => host.querySelector(q);
    const css = getComputedStyle(document.documentElement);
    const V = (n, fb) => (css.getPropertyValue(n) || fb).trim() || fb;
    const COL = { land: V("--cv-land", "#aab4c4"), ch: V("--cv-liq", "#e9f1fa"),
                  grid: V("--line", "#d6dce6"), inl: V("--grn", "#0f8a63"),
                  out: V("--warn", "#c9333f"), acc: V("--accent", "#1f6feb"),
                  dim: V("--dim", "#68738a") };

    const idx = (j, k) => j * NZ + k;
    const inb = (j, k) => j >= 0 && j < NY && k >= 0 && k < NZ;

    const canvases = [$(".pe-cv")];
    let overlay = null;

    // ------------------------------------------------------------ stroke model
    function cellsOfStroke(s) {
      if (!s) return [];
      const [j0, k0] = s.a, [j1, k1] = s.b || s.a;
      const out = [];
      const b = brush - 1;
      const stamp = (j, k) => {
        for (let dj = -b; dj <= b; dj++) for (let dk = -b; dk <= b; dk++)
          if (inb(j + dj, k + dk)) out.push([j + dj, k + dk]);
      };
      if (s.tool === "rect") {
        for (let j = Math.min(j0, j1); j <= Math.max(j0, j1); j++)
          for (let k = Math.min(k0, k1); k <= Math.max(k0, k1); k++) out.push([j, k]);
        return out;
      }
      if (s.tool === "brush") { (s.path || [s.a]).forEach(([j, k]) => stamp(j, k)); return out; }
      // line: snapped to the nearest axis unless Alt asks for a free angle,
      // because a rib that is one cell off horizontal is a different flow field
      let jj1 = j1, kk1 = k1;
      if (!s.free) {
        if (Math.abs(j1 - j0) >= Math.abs(k1 - k0)) kk1 = k0; else jj1 = j0;
      }
      const n = Math.max(Math.abs(jj1 - j0), Math.abs(kk1 - k0));
      for (let i = 0; i <= n; i++) {
        const t = n ? i / n : 0;
        stamp(Math.round(j0 + (jj1 - j0) * t), Math.round(k0 + (kk1 - k0) * t));
      }
      return out;
    }

    function paintCells(cells, val) {
      for (const [j, k] of cells) {
        mask[idx(j, k)] = val;
        if (mirror) mask[idx(j, NZ - 1 - k)] = val;
      }
    }

    // ---------------------------------------------------------------- drawing
    function render() {
      const preview = drag ? cellsOfStroke(drag) : [];
      const pv = new Set(preview.map(([j, k]) => idx(j, k)));
      if (mirror) preview.forEach(([j, k]) => pv.add(idx(j, NZ - 1 - k)));
      const val = drag ? !drag.erase : !erase;

      for (const cv of canvases) {
        const ctx = cv.getContext("2d");
        const w = cv.width, h = cv.height, cx = w / NZ, cy = h / NY;
        ctx.fillStyle = COL.ch; ctx.fillRect(0, 0, w, h);

        ctx.fillStyle = COL.land;
        for (let j = 0; j < NY; j++) for (let k = 0; k < NZ; k++)
          if (mask[idx(j, k)] && !pv.has(idx(j, k))) ctx.fillRect(k*cx, h - (j+1)*cy, cx, cy);

        // stroke preview: see what the drag WILL do before letting go
        if (pv.size) {
          ctx.globalAlpha = 0.8;
          ctx.fillStyle = val ? COL.acc : COL.ch;
          for (const i of pv) ctx.fillRect((i % NZ)*cx, h - (Math.floor(i/NZ)+1)*cy, cx, cy);
          ctx.globalAlpha = 1;
        }

        // cell borders — these ARE the solver's cells, one drawn square each
        ctx.strokeStyle = COL.dim; ctx.globalAlpha = 0.22; ctx.lineWidth = 1;
        for (let k = 1; k < NZ; k++) {
          const x = Math.round(k * cx) + 0.5;
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
        }
        for (let j = 1; j < NY; j++) {
          const y = Math.round(h - j * cy) + 0.5;
          ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
        }
        ctx.globalAlpha = 1;

        if (hover && !drag) {
          ctx.strokeStyle = COL.acc; ctx.lineWidth = 2;
          ctx.strokeRect(hover[1]*cx + 1, h - (hover[0]+1)*cy + 1, cx - 2, cy - 2);
        }

        const bar = Math.max(4, Math.min(cx, cy) * 0.55);
        if (ports) {
          const edge = (arr, face, col) => {
            ctx.fillStyle = col;
            if (face === "bottom" || face === "top") {
              for (let k = 0; k < NZ; k++)
                if (arr[Math.min(ports.nz - 1, k)]) ctx.fillRect(k*cx, face === "bottom" ? h - bar : 0, cx, bar);
            } else {
              for (let j = 0; j < NY; j++)
                if (arr[Math.min(ports.ny - 1, j)]) ctx.fillRect(face === "left" ? 0 : w - bar, h - (j+1)*cy, bar, cy);
            }
          };
          edge(ports.in, ports.in_face || "bottom", COL.inl);
          edge(ports.out, ports.out_face || "top", COL.out);
        }
      }
      status();
    }

    function status() {
      const nLand = mask.reduce((a, b) => a + b, 0);
      const jet = P.ff === "custom" && +P.in_w === 0;
      const mm = cellMM ? ` · 한 칸 ${cellMM.toFixed(1)} mm` : "";
      $(".pe-stat").innerHTML =
        `리브 <b style="color:var(--tx)">${(100*nLand/(NY*NZ)).toFixed(0)}%</b> · ` +
        `<b style="color:var(--tx)">${NY}×${NZ}</b> = 물리격자 그대로${mm}` +
        (pending ? ` · <span class="pe-dirty">적용 대기…</span>` : "") +
        (P.ff === "custom" ? "" : ` · <span style="color:var(--dim)">그리면 적용됩니다</span>`) +
        (jet ? `<br><span style="color:var(--gold)">입구 폭 = 0 (바닥 전체 급수)</span>` +
               `<span style="color:var(--dim)"> — 좁은 틈으로 유량이 몰려 제트가 생깁니다. ` +
               `포트 폭을 0.1 정도로 지정해 보세요.</span>` : "");
      $(".pe-undo").disabled = !undo.length;
      $(".pe-redo").disabled = !redo.length;
    }

    // ------------------------------------------------------------- committing
    function snapshot() {
      undo.push(mask.slice());
      if (undo.length > MAX_UNDO) undo.shift();
      redo.length = 0;
    }
    function scheduleSend() {
      pending = true;
      clearTimeout(sendTimer);
      // the engine rebuilds its voxel grid (and restarts the bubbles) on every
      // mask change, so wait until the hand stops moving
      sendTimer = setTimeout(() => {
        pending = false;
        if (P.ff !== "custom") { P.ff = "custom"; send("ff", "custom"); reg.ff && reg.ff("custom"); }
        // the shape travels with the bits: the grid is rectangular and changes
        send("mask", `${NY},${NZ}:` + Array.from(mask, v => (v ? "1" : "0")).join(""));
        render();
      }, SEND_QUIET_MS);
      render();
    }
    function restore(from, to) {
      if (!from.length) return;
      to.push(mask.slice());
      mask = from.pop();
      scheduleSend();
    }

    // ----------------------------------------------------------- interactions
    function cellAt(cv, ev) {
      const r = cv.getBoundingClientRect();
      const k = Math.floor((ev.clientX - r.left) / r.width * NZ);
      const j = NY - 1 - Math.floor((ev.clientY - r.top) / r.height * NY);
      return [Math.max(0, Math.min(NY-1, j)), Math.max(0, Math.min(NZ-1, k))];
    }
    function wire(cv) {
      cv.addEventListener("pointerdown", e => {
        if (e.button === 1) return;
        // capture is a nicety (it keeps the stroke alive outside the canvas);
        // if the browser refuses the pointer id, draw anyway rather than drop
        // the whole stroke on the floor
        try { cv.setPointerCapture(e.pointerId); } catch (_) {}
        const a = cellAt(cv, e);
        drag = { tool: tool, a, b: a, free: e.altKey, path: [a],
                 erase: erase || e.shiftKey || e.button === 2 };
        render(); e.preventDefault();
      });
      cv.addEventListener("pointermove", e => {
        const c = cellAt(cv, e);
        if (!drag) { hover = c; render(); return; }
        drag.free = e.altKey;
        if (drag.tool === "brush") {        // interpolate: a fast drag must not gap
          const [pj, pk] = drag.path[drag.path.length - 1];
          const n = Math.max(Math.abs(c[0]-pj), Math.abs(c[1]-pk));
          if (!n) drag.path.push(c);
          for (let i = 1; i <= n; i++)
            drag.path.push([Math.round(pj + (c[0]-pj)*i/n), Math.round(pk + (c[1]-pk)*i/n)]);
        }
        drag.b = c; render();
      });
      const finish = () => {
        if (!drag) return;
        const cells = cellsOfStroke(drag);
        if (cells.length) { snapshot(); paintCells(cells, drag.erase ? 0 : 1); scheduleSend(); }
        drag = null; render();
      };
      cv.addEventListener("pointerup", finish);
      cv.addEventListener("pointercancel", () => { drag = null; render(); });
      cv.addEventListener("pointerleave", () => { if (!drag) { hover = null; render(); } });
      cv.addEventListener("contextmenu", e => e.preventDefault());
    }
    canvases.forEach(wire);

    host.querySelectorAll(".pe-t").forEach(b => b.onclick = () => {
      host.querySelectorAll(".pe-t").forEach(x => x.classList.remove("on"));
      b.classList.add("on");
      erase = b.dataset.tool === "erase";
      tool = erase ? "brush" : b.dataset.tool;
      render();
    });
    host.querySelector('.pe-t[data-tool="line"]').classList.add("on");

    const bs = $(".pe-brush");
    bs.oninput = () => { brush = +bs.value; $(".pe-brushn").textContent = brush; render(); };
    $(".pe-mirror").onchange = e => { mirror = e.target.checked; render(); };
    $(".pe-undo").onclick = () => restore(undo, redo);
    $(".pe-redo").onclick = () => restore(redo, undo);
    $(".pe-clear").onclick = () => { snapshot(); mask.fill(0); scheduleSend(); };
    $(".pe-inv").onclick = () => { snapshot(); for (let i=0;i<mask.length;i++) mask[i] ^= 1; scheduleSend(); };
    $(".pe-load").onclick = () => { snapshot(); loadFromEngine(); scheduleSend(); };

    addEventListener("keydown", e => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const t = (e.target.tagName || "").toLowerCase();
      if (t === "input" || t === "textarea") return;
      if (e.key === "z" && !e.shiftKey) { e.preventDefault(); restore(undo, redo); }
      else if (e.key === "y" || (e.key === "z" && e.shiftKey)) { e.preventDefault(); restore(redo, undo); }
    });

    // ------------------------------------------------------------ pop-out view
    $(".pe-big").onclick = () => {
      if (overlay) return;
      overlay = document.createElement("div");
      overlay.id = "pe-overlay";
      overlay.innerHTML = `<div class="wrap">
        <div class="hd"><span>유로 직접 그리기 — 크게 보기</span>
        <button class="btn pe-close" style="flex:none;padding:4px 12px">닫기 (Esc)</button></div>
        <canvas width="1024" height="1024"></canvas></div>`;
      document.body.appendChild(overlay);
      const big = overlay.querySelector("canvas");
      big.style.aspectRatio = `${NZ} / ${NY}`;
      canvases.push(big); wire(big); render();
      const esc = e => { if (e.key === "Escape") close(); };
      function close() {
        canvases.splice(canvases.indexOf(big), 1);
        overlay.remove(); overlay = null;
        removeEventListener("keydown", esc);
        render();
      }
      overlay.querySelector(".pe-close").onclick = close;
      overlay.onclick = e => { if (e.target === overlay) close(); };
      addEventListener("keydown", esc);
    };

    // ------------------------------------------------------------------- sync
    function loadFromEngine() {
      if (!lastLand || lastLand.ny !== NY || lastLand.nz !== NZ) return false;
      let changed = false;
      for (let i = 0; i < mask.length; i++) {
        const v = lastLand.m[i] ? 1 : 0;
        if (mask[i] !== v) { mask[i] = v; changed = true; }
      }
      return changed;
    }

    /** Grid changed (electrode size, channel depth): carry the drawing across. */
    function reshape(ny, nz) {
      if (ny === NY && nz === NZ) return;
      const Wy = overlap(ny, NY), Wz = overlap(nz, NZ);
      const out = new Uint8Array(ny * nz);
      for (let j = 0; j < ny; j++) for (let k = 0; k < nz; k++) {
        let f = 0;
        for (let a = 0; a < NY; a++) { if (!Wy[j][a]) continue;
          for (let b = 0; b < NZ; b++) { if (!Wz[k][b]) continue;
            f += Wy[j][a] * Wz[k][b] * mask[a * NZ + b]; } }
        out[j * nz + k] = f >= 0.5 ? 1 : 0;      // area-weighted, not nearest
      }
      mask = out; NY = ny; NZ = nz;
      undo.length = 0; redo.length = 0;          // history is shape-specific
      for (const cv of canvases) cv.style.aspectRatio = `${NZ} / ${NY}`;
      // push the reshaped drawing back, so the canvas and the solver hold the
      // same mask rather than two resolutions of the same picture
      if (P.ff === "custom") scheduleSend();
    }

    render();

    // verification handle (headless: synthetic pointer events, no screenshots)
    g.__peState = () => ({
      NY, NZ, tool, erase, brush, mirror, pending,
      undo: undo.length, redo: redo.length,
      land: Array.from(mask).reduce((a, b) => a + b, 0),
      rows: [...Array(NY).keys()].map(j => {
        let n = 0; for (let k = 0; k < NZ; k++) n += mask[idx(j, k)];
        return n;
      }),
    });

    return {
      sync(st) {
        if (!st) return;
        if (st.grid) { reshape(st.grid.ny, st.grid.nz); cellMM = st.grid.h_mm; }
        if (st.land2d) lastLand = st.land2d;
        if (st.ports) ports = st.ports;
        // While the flow field is a PRESET, the canvas mirrors what is running,
        // so you start from the plate you can see instead of a blank sheet.
        if (P.ff !== "custom" && !drag && !pending) loadFromEngine();
        render();
      },
    };
  };
})(window);
