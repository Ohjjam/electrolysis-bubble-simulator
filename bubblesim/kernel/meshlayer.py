"""Bubble-management mesh interlayer: geometry -> bubble-physics factors.

A hydrophobic (aerophilic) polymer mesh (e.g. polypropylene) laid on the
electrode surface inside the flow channel changes how gas leaves the surface.
This module maps the mesh GEOMETRY -- opening size L_h, open-area fraction phi,
thickness t_m -- plus the channel depth d_ch onto the reduced bubble knobs the
channel solver already has. The mapping is fixed A PRIORI from the mechanisms
below; its constants are NOT fitted to any mesh experiment, so mesh predictions
stay blind (the point of the exercise).

Mechanisms (each -> one factor):

1. WICKING / early detachment. PP is hydrophobic => aerophilic: gas wets the
   strands preferentially, so a bubble that touches a strand transfers to it
   and drains along the strand network instead of blanketing the catalyst.
   Strand area fraction is (1 - phi); how often a growing/sliding bubble meets
   a strand scales inversely with the opening size, saturating once openings
   are finer than the bubble path spacing (L_REF):
       wick = (1 - phi) * min(1, L_REF / L_h)            in [0, 1)
   -> coverage relief:      theta_factor   = 1 - C_THETA * wick
   -> local holdup relief:  retention part = 1 - C_RET * wick
   (retention_factor multiplies the LOCAL wall holdup in covered segments
   only -- gas volume is conserved along the channel; the mesh organizes it
   into the fast core flow instead of letting it linger on the wall.)

2. CHANNEL ENCROACHMENT. The mesh sits in the channel, so the liquid
   cross-section shrinks from d_ch to (d_ch - t_m): continuity speeds the
   local flow by u_boost = d_ch / (d_ch - t_m). Faster sweep thins the
   local holdup further (retention / sqrt(u_boost), weaker than linear
   because the gas rides near the wall). u_boost is also the honest
   pressure-drop warning proxy (dP ~ u^2).

3. LIQUID-ACCESS BLOCKING. The strands mask (1 - phi) of the face and the
   mesh volume displaces electrolyte: fresh liquid reaches the catalyst
   through a torturous path, which acts like a floor of extra coverage
       theta_add = C_BLOCK * (1 - phi) * (t_m / d_ch)
   This is the DOWNSIDE term -- a dense/thick mesh hurts more than it helps.

Fit rule: the mesh must leave a liquid path (t_m < d_ch); nearly-filling
meshes (t_m > FIT_WARN * d_ch) get a warning (huge dP, u_boost capped).

All constants below are order-of-magnitude physical choices made before any
mesh polarization data was consulted (documented blind-prediction protocol).
Pure python; no external deps.
"""

L_REF = 2.0       # [mm] opening size below which a strand line intercepts most
                  # of the sliding/growing bubble paths (bubbles are 0.05-0.5 mm;
                  # their travel spacing on the wall is O(mm))
C_THETA = 0.6     # max fractional blanketing relief at wick=1 (some film always remains)
C_RET = 0.5       # max fractional retention cut from wicking alone
C_BLOCK = 0.3     # blocking penalty scale (theta-equivalent per strand+thickness)
FIT_WARN = 0.6    # t_m/d_ch above this = "fits but chokes the channel" warning
U_BOOST_CAP = 4.0 # encroachment speed-up cap (beyond this the model's
                  # 1-D picture is not credible; also flags huge dP)


def mesh_factors(hole_mm, open_frac, t_mm, d_ch_mm):
    """Mesh geometry -> reduced factors for the channel solver.

    Returns a dict:
      fits             mesh physically mountable (t_m < d_ch)
      warn             "" | human-readable caution (near-filling, capped boost)
      wick             0..1 gas-wicking strength (diagnostic)
      u_boost          local velocity multiplier from encroachment (>= 1)
      theta_factor     multiplier on the coverage closure amplitude (<= 1)
      retention_factor multiplier on per-segment gas retention (<= 1)
      theta_add        additive coverage floor from liquid blocking (>= 0)
    Neutral factors (no mesh) when t_mm <= 0 or hole_mm <= 0.
    """
    neutral = dict(fits=True, warn="", wick=0.0, u_boost=1.0,
                   theta_factor=1.0, retention_factor=1.0, theta_add=0.0)
    if t_mm <= 0.0 or hole_mm <= 0.0:
        return neutral
    d = max(1e-6, float(d_ch_mm))
    t = float(t_mm)
    if t >= d:
        out = dict(neutral)
        out["fits"] = False
        out["warn"] = "mesh thicker than the channel depth: cannot mount"
        return out

    phi = min(1.0, max(0.05, float(open_frac)))
    strand = 1.0 - phi
    fine = min(1.0, L_REF / max(0.05, float(hole_mm)))
    wick = strand * fine

    u_boost = d / max(d - t, 1e-6)
    warn = ""
    if u_boost > U_BOOST_CAP:
        u_boost = U_BOOST_CAP
        warn = "mesh nearly fills the channel: velocity boost capped, expect large dP"
    elif t > FIT_WARN * d:
        warn = "mesh takes >60% of the channel depth: high pressure drop"

    return dict(
        fits=True, warn=warn, wick=wick, u_boost=u_boost,
        theta_factor=1.0 - C_THETA * wick,
        retention_factor=(1.0 - C_RET * wick) / (u_boost ** 0.5),
        theta_add=C_BLOCK * strand * (t / d),
    )


def path_mask(m, cover, pos):
    """Boolean mask over m path points: which stretch of the channel run is
    covered by mesh. cover in [0,1] is the covered fraction (1.0 = the whole
    path, whatever pos says); pos anchors a partial cover at the inlet end,
    the outlet end, or the middle of the run (unknown pos -> outlet, where
    gas accumulates most)."""
    cover = min(1.0, max(0.0, float(cover)))
    n = int(round(m * cover))
    mask = [False] * m
    if n <= 0:
        return mask
    if pos == "inlet":
        lo, hi = 0, n
    elif pos == "middle":
        lo = (m - n) // 2
        hi = lo + n
    else:                                   # "outlet" (default anchor)
        lo, hi = m - n, m
    for i in range(max(0, lo), min(m, hi)):
        mask[i] = True
    return mask
