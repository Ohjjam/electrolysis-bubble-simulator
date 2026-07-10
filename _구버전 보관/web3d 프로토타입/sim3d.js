// sim3d.js — real 3-D coupled bubble/flow engine (CPU reference backend).
//
// Euler-Lagrange electrolysis cell, one dimension up from flow2d:
//   * carrier liquid -> incompressible Navier-Stokes on a uniform grid
//                       (Stam "stable fluids": advect -> project), buoyancy from
//                       the local gas void fraction (Boussinesq, beta~1).
//   * gas            -> Lagrangian SPHERICAL parcels nucleated on an electrode
//                       wall at the Faradaic rate (j/nF). A parcel is a
//                       COMPUTATIONAL bubble: it carries a gas volume W so the
//                       tracked count stays sane while total gas is conserved
//                       (tracking every real micro-bubble is the millions-of-
//                       bubbles wall). Parcels ride the SOLVED flow + buoyant
//                       slip and exit the top.
//   * two-way        -> parcels deposit void -> buoyancy force on the fluid ->
//                       recirculation / self-stirring EMERGES (not scripted).
//   * gravity is a VECTOR -> a cell-tilt knob rotates it, so the two facing
//                       electrodes de-gas asymmetrically (the 3-D payoff).
//
// Honest scope: sub-grid parcels (no resolved interfaces -> not VOF), modest grid
// on CPU. Hot loops are flat over typed arrays so a WebGPU backend can mirror them.
// The electrochemistry is NOT reimplemented: j is an INPUT (a boundary condition);
// canonical kinetics stay in the Python kernel and couple in later.

const F = 96485, N_E = 2, R_GAS = 8.314;           // Faraday, electrons/H2, gas const
const RHO_L = 1000, D_RHO = 1000, MU = 1.0e-3;     // liquid density, drho, viscosity
const SIGMA = 0.07, G0 = 9.81;                      // surface tension, gravity
const SPAWN_K = 8000;                               // parcels/s per (A/cm^2) per electrode
                                                    // (more, smaller parcels = denser
                                                    //  fizz; total gas Vdot is unchanged)

export class Sim3D {
  constructor(opts = {}) {
    this.nx = opts.nx ?? 16;
    this.ny = opts.ny ?? 32;
    this.nz = opts.nz ?? 16;
    this.h = opts.h ?? 1.5e-3;                       // 1.5 mm cells -> 24x48x24 mm cell
                                                     // (8k cells: real-time on CPU; M2/WebGPU goes finer)
    this.Lx = this.nx * this.h;
    this.Ly = this.ny * this.h;
    this.Lz = this.nz * this.h;
    this.n = this.nx * this.ny * this.nz;
    this.CAP = opts.cap ?? 5000;                     // max tracked parcels

    const F32 = () => new Float32Array(this.n);
    this.u = F32(); this.v = F32(); this.w = F32();   // velocity field [m/s]
    this.u0 = F32(); this.v0 = F32(); this.w0 = F32(); // scratch
    this.p = F32(); this.div = F32();                 // pressure, divergence
    this.gas = F32();                                 // void fraction per cell [-]

    this.params = {
      j: 0.4,            // current density [A/cm^2]   (INPUT, not solved)
      u_in: 0.0,         // forced through-flow at the bottom [m/s]
      theta: 60,         // contact angle [deg]
      tilt: 0,           // cell tilt about z [deg]: 0 vertical, 90 horizontal
      visScale: 2.0,     // VISUAL parcel-radius exaggeration (render only)
      buoy: 0.6,         // interphase buoyancy coupling (liquid feels drag reaction, <1)
      gasFactorA: 0.5,   // O2 (anode) ~ half the gas of H2 (cathode)
    };

    // nucleation site POSITIONS on each electrode wall (x-faces)
    this.posC = this._sites(0);          // cathode (HER, H2) at i=0
    this.posA = this._sites(this.nx - 1); // anode  (OER, O2) at i=nx-1
    this.bubbles = [];
    this._nextId = 1;
    this.t = 0;
    this.diag = { nBub: 0, thetaC: 0, thetaA: 0, holdup: 0, vmax: 0, up: [0, 1, 0] };
  }

  IX(i, j, k) { return i + this.nx * (j + this.ny * k); }

  _sites(iWall) {
    const s = []; s.acc = 0;
    for (let j = 2; j < this.ny - 2; j += 3)
      for (let k = 1; k < this.nz - 1; k += 3)
        s.push({ iWall, y: (j + 0.5) * this.h, z: (k + 0.5) * this.h });
    return s;
  }

  setParams(p) { Object.assign(this.params, p); }

  // unit vector parcels rise along = -g_hat. tilt rotates gravity about +z:
  //   0  -> g=(0,-1,0)  up=(0,1,0)   (vertical)
  //   90 -> g=(-1,0,0)  up=(1,0,0)   (horizontal: electrodes become floor/ceiling)
  _up() {
    const a = this.params.tilt * Math.PI / 180;
    return [Math.sin(a), Math.cos(a), 0];             // = -g_hat
  }

  // Faradaic gas VOLUME rate for one electrode [m^3/s] (Faraday + ideal gas).
  _gasRate(gf) {
    const T = 333.15, P = 1.0e5;
    const jA = Math.max(0, this.params.j) * 1.0e4;    // A/cm^2 -> A/m^2
    const A = this.Ly * this.Lz;                       // electrode wall area
    return gf * (jA * A / (N_E * F)) * R_GAS * T / P;
  }

  _slip(r) {                                          // buoyant terminal speed [m/s]
    return Math.min((2 / 9) * D_RHO * G0 * r * r / MU, 0.25);
  }

  trilerp(fld, x, y, z) {
    const h = this.h;
    let gx = x / h - 0.5, gy = y / h - 0.5, gz = z / h - 0.5;
    let i = Math.floor(gx), j = Math.floor(gy), k = Math.floor(gz);
    const fx = gx - i, fy = gy - j, fz = gz - k;
    i = Math.max(0, Math.min(this.nx - 2, i));
    j = Math.max(0, Math.min(this.ny - 2, j));
    k = Math.max(0, Math.min(this.nz - 2, k));
    const IX = (a, b, c) => a + this.nx * (b + this.ny * c);
    const c000 = fld[IX(i, j, k)], c100 = fld[IX(i + 1, j, k)];
    const c010 = fld[IX(i, j + 1, k)], c110 = fld[IX(i + 1, j + 1, k)];
    const c001 = fld[IX(i, j, k + 1)], c101 = fld[IX(i + 1, j, k + 1)];
    const c011 = fld[IX(i, j + 1, k + 1)], c111 = fld[IX(i + 1, j + 1, k + 1)];
    const lx0 = c000 + (c100 - c000) * fx, lx1 = c010 + (c110 - c010) * fx;
    const lx2 = c001 + (c101 - c001) * fx, lx3 = c011 + (c111 - c011) * fx;
    const ly0 = lx0 + (lx1 - lx0) * fy, ly1 = lx2 + (lx3 - lx2) * fy;
    return ly0 + (ly1 - ly0) * fz;
  }

  _setBndVel() {
    const { nx, ny, nz, u, v, w } = this;
    const IX = (a, b, c) => a + nx * (b + ny * c);
    for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) {
      u[IX(0, j, k)] = -u[IX(1, j, k)]; u[IX(nx - 1, j, k)] = -u[IX(nx - 2, j, k)];
    }
    for (let k = 0; k < nz; k++) for (let i = 0; i < nx; i++) {
      v[IX(i, 0, k)] = -v[IX(i, 1, k)]; v[IX(i, ny - 1, k)] = -v[IX(i, ny - 2, k)];
    }
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      w[IX(i, j, 0)] = -w[IX(i, j, 1)]; w[IX(i, j, nz - 1)] = -w[IX(i, j, nz - 2)];
    }
  }
  _setBndScalar(s) {
    const { nx, ny, nz } = this;
    const IX = (a, b, c) => a + nx * (b + ny * c);
    for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) {
      s[IX(0, j, k)] = s[IX(1, j, k)]; s[IX(nx - 1, j, k)] = s[IX(nx - 2, j, k)];
    }
    for (let k = 0; k < nz; k++) for (let i = 0; i < nx; i++) {
      s[IX(i, 0, k)] = s[IX(i, 1, k)]; s[IX(i, ny - 1, k)] = s[IX(i, ny - 2, k)];
    }
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      s[IX(i, j, 0)] = s[IX(i, j, 1)]; s[IX(i, j, nz - 1)] = s[IX(i, j, nz - 2)];
    }
  }

  _project(iters = 30) {
    const { nx, ny, nz, u, v, w, p, div, h } = this;
    const IX = (a, b, c) => a + nx * (b + ny * c);
    for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++)
      for (let i = 1; i < nx - 1; i++) {
        const c = IX(i, j, k);
        div[c] = 0.5 * ((u[IX(i + 1, j, k)] - u[IX(i - 1, j, k)]) +
                        (v[IX(i, j + 1, k)] - v[IX(i, j - 1, k)]) +
                        (w[IX(i, j, k + 1)] - w[IX(i, j, k - 1)])) / h;
        p[c] = 0;
      }
    this._setBndScalar(div); this._setBndScalar(p);
    const hh = h * h;
    for (let it = 0; it < iters; it++) {
      for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++)
        for (let i = 1; i < nx - 1; i++) {
          const c = IX(i, j, k);
          p[c] = (p[IX(i - 1, j, k)] + p[IX(i + 1, j, k)] +
                  p[IX(i, j - 1, k)] + p[IX(i, j + 1, k)] +
                  p[IX(i, j, k - 1)] + p[IX(i, j, k + 1)] - hh * div[c]) / 6;
        }
      this._setBndScalar(p);
    }
    for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++)
      for (let i = 1; i < nx - 1; i++) {
        const c = IX(i, j, k);
        u[c] -= 0.5 * (p[IX(i + 1, j, k)] - p[IX(i - 1, j, k)]) / h;
        v[c] -= 0.5 * (p[IX(i, j + 1, k)] - p[IX(i, j - 1, k)]) / h;
        w[c] -= 0.5 * (p[IX(i, j, k + 1)] - p[IX(i, j, k - 1)]) / h;
      }
    this._setBndVel();
  }

  _advect(dt) {
    const { nx, ny, nz, u, v, w, u0, v0, w0, h } = this;
    u0.set(u); v0.set(v); w0.set(w);
    const IX = (a, b, c) => a + nx * (b + ny * c);
    for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++)
      for (let i = 1; i < nx - 1; i++) {
        const c = IX(i, j, k);
        const x = (i + 0.5) * h - dt * u0[c];
        const y = (j + 0.5) * h - dt * v0[c];
        const z = (k + 0.5) * h - dt * w0[c];
        u[c] = this.trilerp(u0, x, y, z);
        v[c] = this.trilerp(v0, x, y, z);
        w[c] = this.trilerp(w0, x, y, z);
      }
    this._setBndVel();
  }

  _depositGas() {
    const { gas, h, nx, ny, nz } = this;
    gas.fill(0);
    const vcell = h * h * h;
    const IX = (a, b, c) => a + nx * (b + ny * c);
    // smear each parcel's gas over a 3x3x3 block: a 0.5 mm parcel in a 1 mm cell
    // would otherwise spike one cell to ~50% void (-> runaway buoyancy jets).
    // Spreading over ~27 cells gives the physical few-% void fraction.
    for (const b of this.bubbles) {
      const ci = Math.floor(b.x / h), cj = Math.floor(b.y / h), ck = Math.floor(b.z / h);
      const share = b.w / vcell / 27;
      for (let dk = -1; dk <= 1; dk++)
        for (let dj = -1; dj <= 1; dj++)
          for (let di = -1; di <= 1; di++) {
            const i = Math.min(nx - 1, Math.max(0, ci + di));
            const j = Math.min(ny - 1, Math.max(0, cj + dj));
            const k = Math.min(nz - 1, Math.max(0, ck + dk));
            gas[IX(i, j, k)] += share;
          }
    }
  }

  _addForces(dt) {
    const { nx, ny, nz, u, v, w, gas } = this;
    const up = this._up();
    const gb = G0 * this.params.buoy;
    const damp = Math.max(0, 1 - 3.0 * dt);            // viscous/wall losses
    for (let c = 0; c < this.n; c++) {
      const f = gb * gas[c] * dt;                      // accel along 'up'
      u[c] = u[c] * damp + f * up[0];
      v[c] = v[c] * damp + f * up[1];
      w[c] = w[c] * damp + f * up[2];
    }
    const uin = this.params.u_in;
    if (uin > 0) {
      const IX = (a, b, c) => a + nx * (b + ny * c);
      for (let k = 0; k < nz; k++) for (let i = 0; i < nx; i++)
        v[IX(i, 1, k)] += (uin - v[IX(i, 1, k)]) * Math.min(1, dt * 20);
    }
    this._setBndVel();
  }

  // spawn parcels at the Faradaic rate; each carries gas W so total gas = j/nF.
  _spawn(dt) {
    const j = Math.max(0, this.params.j);
    for (const [sites, gf] of [[this.posC, 1.0], [this.posA, this.params.gasFactorA]]) {
      const rate = SPAWN_K * j * gf;                   // parcels/s
      if (rate < 1e-6) { sites.acc = 0; continue; }
      const W = this._gasRate(gf) / rate;              // m^3 gas/parcel (conserves Vdot)
      const r = Math.cbrt(3 * W / (4 * Math.PI));      // parcel equivalent radius
      let acc = sites.acc + rate * dt;
      while (acc >= 1 && this.bubbles.length < this.CAP) {
        const p = sites[(Math.random() * sites.length) | 0];
        const x = p.iWall === 0 ? r + 0.2 * this.h : this.Lx - r - 0.2 * this.h;
        this.bubbles.push({ id: this._nextId++, x, y: p.y, z: p.z, r, w: W,
                            side: p.iWall === 0 ? 0 : 1 });
        acc -= 1;
      }
      sites.acc = acc;
    }
  }

  _moveBubbles(dt) {
    const up = this._up();
    const keep = [];
    let vmax = 0, holdV = 0;
    const totV = this.n * this.h ** 3;
    for (const b of this.bubbles) {
      const uf = this.trilerp(this.u, b.x, b.y, b.z);
      const vf = this.trilerp(this.v, b.x, b.y, b.z);
      const wf = this.trilerp(this.w, b.x, b.y, b.z);
      const vs = this._slip(b.r);
      b.x += (uf + vs * up[0]) * dt;
      b.y += (vf + vs * up[1]) * dt;
      b.z += (wf + vs * up[2]) * dt;
      const m = b.r + 0.2 * this.h;
      // electrodes (x faces) and side walls (z faces) are SOLID -> reflect.
      if (b.x < m) b.x = m; else if (b.x > this.Lx - m) b.x = this.Lx - m;
      if (b.z < m) b.z = m; else if (b.z > this.Lz - m) b.z = this.Lz - m;
      if (b.y < m) b.y = m;                            // reflect off the floor
      const sp = Math.hypot(uf, vf, wf); if (sp > vmax) vmax = sp;
      holdV += b.w;
      // gas vents ONLY at the cell's fixed top outlet (y=Ly). When the cell is
      // tilted, buoyancy points at an electrode wall instead of the outlet, so
      // gas can't reach it and accumulates -> the horizontal-cell trapping problem.
      if (b.y <= this.Ly - m) keep.push(b);
    }
    this.bubbles = keep;
    this.diag.vmax = vmax;
    this.diag.holdup = holdV / totV;
    this.diag.up = up;
  }

  // qualitative wall coverage: near-wall gas column fraction (rises with j, falls
  // with flow). M1 proxy -- the canonical theta will come from the Python kernel.
  _coverage() {
    const slab = 2 * this.h, denom = this.Ly * this.Lz * slab;
    let wC = 0, wA = 0;
    for (const b of this.bubbles) {
      if (b.x < slab) wC += b.w; else if (b.x > this.Lx - slab) wA += b.w;
    }
    this.diag.thetaC = Math.min(1, 25 * wC / denom);
    this.diag.thetaA = Math.min(1, 25 * wA / denom);
  }

  step(dt) {
    dt = Math.min(dt, 0.01);
    this._depositGas();
    this._addForces(dt);
    this._project(14);
    this._advect(dt);
    this._project(14);
    this._spawn(dt);
    this._moveBubbles(dt);
    this._coverage();
    this.diag.nBub = this.bubbles.length;
    this.t += dt;
  }

  reset() {
    this.u.fill(0); this.v.fill(0); this.w.fill(0); this.gas.fill(0);
    this.bubbles = [];
    this.posC.acc = 0; this.posA.acc = 0;
    this.t = 0;
  }

  // flat snapshot for the renderer: [x, y, z, r_render, side, ...] in METRES,
  // side 0 = cathode/H2, 1 = anode/O2.
  bubbleSnapshot() {
    const vs = this.params.visScale, out = [];
    for (const b of this.bubbles) out.push(b.x, b.y, b.z, b.r * vs, b.side);
    return out;
  }
}
