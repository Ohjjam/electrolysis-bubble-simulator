"""Bubble-management mesh interlayer: measurable inputs -> channel factors.

The former implementation converted mesh geometry to a hand-made ``wick``
score using ``L_ref=2 mm`` and three fitted-looking multipliers.  That made all
openings below 2 mm equivalent and did not use the electrode contact angle at
all.  This module instead keeps the mechanisms separate and dimensionless:

1. A representative departure-bubble diameter is calculated with the same
   force balance used by the bubble simulator (Fritz anchor + near-wall shear).
2. For a bubble centre uniformly distributed over the projected mesh unit cell,
   the zero-standoff upper-bound chance that the growing bubble reaches a strand
   is

       P_contact = 1 - phi max(1-d_b/L_x, 0) max(1-d_b/L_y, 0).

   The ``phi`` term includes centres projected under a strand; the shrunken-open
   rectangle is the only region that avoids contact.  This assumes negligible
   mesh/electrode standoff, so it is explicitly an upper bound.  There is no
   arbitrary reference opening and no hard 2 mm plateau.
3. The thermodynamic preference for gas to move from electrode to mesh is
   derived from Young's equation using water contact angles measured through
   the liquid phase.  Gas affinity is proportional to ``1-cos(theta)``.  The
   normalized positive driving force is

       P_wet = max(0, (cos(theta_e)-cos(theta_m))/(1+cos(theta_e))).

   It is zero when the mesh is not more hydrophobic than the electrode.  This
   is a driving-score, not a claim that contact-angle hysteresis/kinetics are
   resolved.  ``capture = P_contact * P_wet`` is therefore the modelled upper
   fraction of electrode-covering bubbles transferred to the mesh.
   The experiment UI accepts submerged gas-bubble contact angles and converts
   them before calling this model with ``theta_water = 180 deg - theta_bubble``.
4. The mesh solid occupies ``obstruction=(1-phi)t_m/d_ch`` of the local channel
   volume.  Continuity gives ``u_boost=1/(1-obstruction)`` and residence-time
   scaling gives ``retention=1/u_boost``.  A laminar parallel-gap estimate gives
   ``dP_ratio=u_boost**3``.  This solid-volume fraction is *not* converted into
   catalyst-area blockage: that requires the mesh/electrode spacing,
   compression and lateral electrolyte access, none of which is specified.

``hydraulic=False`` selects the Mesh 2 isolation experiment.  It retains the
measured geometry for contact probability and the entered contact angles for
the Young driving force, but sets obstruction to zero and all hydraulic
multipliers to one.  Mesh thickness is therefore catalog metadata only; it
cannot narrow the channel or alter velocity, residence time, or pressure loss.

The model still does not resolve dynamic contact-angle hysteresis, capillary
bridging, or a woven-mesh CFD pressure loss.  Those need measurements; the
returned diagnostics keep that limitation visible.
"""
from dataclasses import replace
import math

from .bubbles.forces import departure_radius


# The solver uses apparent water contact angles through the liquid.  These
# defaults are converted from this experiment's measured submerged gas-bubble
# angles: catalyst/NF 145.1 deg and bare PP mesh 101.2 deg.
DEFAULT_ELECTRODE_ANGLE = 34.9   # 180 - 145.1 deg
DEFAULT_PP_ANGLE = 78.8          # 180 - 101.2 deg
DP_WARN = 3.0                    # engineering warning only; not used in voltage
DP_SEVERE = 10.0


def effective_departure_diameter_mm(op, props, j, d_ch_mm):
    """Representative near-wall departure diameter for the mesh model [mm].

    The bulk channel velocity is not applied directly to a micron-scale bubble:
    inside the wall shear layer the velocity scales approximately with distance
    from the wall.  This mirrors ``bubblesim3d.parcels`` and caps the diameter at
    the channel depth (geometric confinement).
    """
    d_ch_m = max(1e-9, float(d_ch_mm) * 1e-3)
    j = max(1e-9, float(j))
    r_stag = departure_radius(replace(op, u_flow=0.0), props, j)
    u_bulk = max(0.0, float(getattr(op, "u_flow", 0.0)))
    u_wall = u_bulk * min(1.0, r_stag / max(0.5 * d_ch_m, 1e-12))
    r_eff = departure_radius(replace(op, u_flow=u_wall), props, j)
    return 2.0 * min(r_eff, 0.5 * d_ch_m) * 1e3


def _clip_angle(value):
    return min(179.0, max(1.0, float(value)))


def mesh_factors(hole_mm, open_frac, t_mm, d_ch_mm, *, bubble_d_mm=0.0,
                 electrode_angle_deg=DEFAULT_ELECTRODE_ANGLE,
                 mesh_angle_deg=DEFAULT_PP_ANGLE,
                 hole_x_mm=None, hole_y_mm=None, hydraulic=True):
    """Return mesh factors from explicit geometry, bubble size, and wettability.

    ``hole_mm`` remains the backward-compatible mean opening.  Catalog entries
    pass ``hole_x_mm`` and ``hole_y_mm`` so rectangular openings are evaluated
    directly.  Angles are apparent water contact angles in degrees, measured
    through the liquid phase.  ``hydraulic=False`` is the Mesh 2 isolation
    experiment: physical thickness remains reported but cannot shrink the
    channel, boost velocity, change residence time, or add pressure loss.
    """
    db = max(0.0, float(bubble_d_mm))
    theta_e = _clip_angle(electrode_angle_deg)
    theta_m = _clip_angle(mesh_angle_deg)
    lx = max(0.001, float(hole_x_mm if hole_x_mm is not None else hole_mm))
    ly = max(0.001, float(hole_y_mm if hole_y_mm is not None else hole_mm))
    neutral = dict(
        fits=True, warn="", bubble_d_mm=db,
        hole_x_mm=lx, hole_y_mm=ly,
        electrode_angle_deg=theta_e, mesh_angle_deg=theta_m,
        contact_prob=0.0, wetting_drive=0.0, capture_eff=0.0,
        obstruction=0.0, flow_open_frac=1.0, u_boost=1.0, dp_ratio=1.0,
        theta_factor=1.0, retention_factor=1.0, blocking_fraction=0.0,
        active_area_blocking_mode="not_modelled",
        hydraulic_mode="physical" if hydraulic else "hydrophobic_only",
    )
    if t_mm <= 0.0 or hole_mm <= 0.0:
        return neutral

    d = max(1e-6, float(d_ch_mm))
    t = max(0.0, float(t_mm))
    if hydraulic and t >= d:
        out = dict(neutral)
        out["fits"] = False
        out["warn"] = "mesh 두께가 채널 깊이 이상이라 장착할 수 없음"
        return out

    phi = min(0.99, max(0.01, float(open_frac)))

    # Zero-standoff projected upper bound.  The only no-contact region is the
    # open aperture shrunken by one bubble radius on every edge.  Its unit-cell
    # area fraction is phi*(1-db/Lx)*(1-db/Ly).
    free_x = max(0.0, 1.0 - db / lx)
    free_y = max(0.0, 1.0 - db / ly)
    p_contact = 1.0 - phi * free_x * free_y

    ce = math.cos(math.radians(theta_e))
    cm = math.cos(math.radians(theta_m))
    p_wet = max(0.0, min(1.0, (ce - cm) / max(1e-9, 1.0 + ce)))
    capture = p_contact * p_wet

    obstruction = (min(0.99, max(0.0, (1.0 - phi) * (t / d)))
                   if hydraulic else 0.0)
    flow_open = 1.0 - obstruction
    u_boost = 1.0 / flow_open
    dp_ratio = u_boost ** 3
    warn = ""
    if dp_ratio >= DP_SEVERE:
        warn = f"mesh 고체 체적으로 인한 층류 압력강하 추정치가 기준 채널의 {dp_ratio:.1f}배"
    elif dp_ratio >= DP_WARN:
        warn = f"mesh 고체 체적으로 인한 층류 압력강하 추정치가 기준 채널의 {dp_ratio:.1f}배"
    if p_wet <= 0.0:
        wet_note = "PP가 전극보다 더 소수성이 아니어서 접촉각 기반 기포 전달 구동력은 0"
        warn = f"{warn}; {wet_note}" if warn else wet_note

    return dict(
        fits=True, warn=warn, bubble_d_mm=db,
        hole_x_mm=lx, hole_y_mm=ly,
        electrode_angle_deg=theta_e, mesh_angle_deg=theta_m,
        contact_prob=p_contact, wetting_drive=p_wet, capture_eff=capture,
        obstruction=obstruction, flow_open_frac=flow_open,
        u_boost=u_boost, dp_ratio=dp_ratio,
        theta_factor=1.0 - capture,
        retention_factor=flow_open,
        # Geometry alone cannot identify catalyst-area loss.  Keep it at zero
        # in the voltage model and expose the solid-volume obstruction
        # separately as a hydraulic diagnostic.
        blocking_fraction=0.0,
        active_area_blocking_mode="not_modelled",
        hydraulic_mode="physical" if hydraulic else "hydrophobic_only",
    )


def operating_mesh_factors(op, props, j):
    """Evaluate ``mesh_factors`` from one solver Operating/context pair."""
    d_ch_mm = max(0.05, float(getattr(op, "chan_depth_mm", 1.0)))
    db = effective_departure_diameter_mm(op, props, j, d_ch_mm)
    hole = float(getattr(op, "mesh_hole_mm", 0.0))
    hx = float(getattr(op, "mesh_hole_x_mm", 0.0)) or hole
    hy = float(getattr(op, "mesh_hole_y_mm", 0.0)) or hole
    return mesh_factors(
        hole, float(getattr(op, "mesh_open", 1.0)),
        float(getattr(op, "mesh_t_mm", 0.0)), d_ch_mm,
        bubble_d_mm=db,
        electrode_angle_deg=float(getattr(op, "contact_angle", DEFAULT_ELECTRODE_ANGLE)),
        mesh_angle_deg=float(getattr(op, "mesh_contact_angle", DEFAULT_PP_ANGLE)),
        hole_x_mm=hx, hole_y_mm=hy,
        hydraulic=str(getattr(op, "mesh_mode", "physical")) != "hydrophobic",
    )


def path_mask(m, cover, pos):
    """Boolean mask over path points covered by the mesh."""
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
    else:
        lo, hi = m - n, m
    for i in range(max(0, lo), min(m, hi)):
        mask[i] = True
    return mask
