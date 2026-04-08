#!/usr/bin/env python3
"""
Run a saved GA rocket in KSP via kRPC.

This script:
1. loads a saved generation JSON
2. selects one rocket (default: best score)
3. converts it to a `.craft`
4. writes the craft into the active save's `Ships/VAB`
5. launches it through kRPC
6. flies a simple standardized ascent with auto-staging

Current assumptions
-------------------
- KSP1 + kRPC server already running
- current target save is `MSandbox`
- linear-stack rockets only
- selection mode defaults to "best"
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import math
import subprocess
import time
from pathlib import Path

import krpc

from src.config import load_parts_by_name
from src.craft import to_craft

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAVE = "MSandbox"
KSP_ROOT = Path(
    "/Users/moss/Library/Application Support/Steam/steamapps/common/"
    "Kerbal Space Program"
)
DEFAULT_RUN = REPO_ROOT / "data" / "runs" / "run_2026-04-02-172335" / "gen_010.json"
RESULTS_ROOT = REPO_ROOT / "results" / "ksp_runs"


def parse_args():
    parser = argparse.ArgumentParser(description="Launch a saved GA rocket in KSP via kRPC.")
    parser.add_argument(
        "--mission",
        choices=["kerbin_orbit", "mun_orbit"],
        default="kerbin_orbit",
        help="Mission profile to fly after launch.",
    )
    parser.add_argument(
        "--generation-file",
        type=Path,
        default=DEFAULT_RUN,
        help="Path to a saved generation JSON.",
    )
    parser.add_argument(
        "--rank",
        type=int,
        default=1,
        help="1-based score rank to select from the generation file.",
    )
    parser.add_argument(
        "--save-name",
        default=DEFAULT_SAVE,
        help="KSP save name whose Ships/VAB folder should receive the generated craft.",
    )
    parser.add_argument(
        "--ship-name",
        default=None,
        help="Optional explicit ship name. Default is derived from generation/rank.",
    )
    parser.add_argument(
        "--target-apoapsis",
        type=float,
        default=80_000,
        help="Target apoapsis in meters for the standardized ascent.",
    )
    parser.add_argument(
        "--turn-start-altitude",
        type=float,
        default=250.0,
        help="Altitude where the gravity turn begins.",
    )
    parser.add_argument(
        "--turn-end-altitude",
        type=float,
        default=45_000.0,
        help="Altitude where the gravity turn reaches horizontal flight.",
    )
    parser.add_argument(
        "--handoff-altitude",
        type=float,
        default=45_000.0,
        help="Minimum altitude before upper-stage orbital handoff is allowed.",
    )
    parser.add_argument(
        "--target-periapsis",
        type=float,
        default=70_000.0,
        help="Target periapsis in meters for considering the orbit closed.",
    )
    parser.add_argument(
        "--periapsis-cutoff",
        type=float,
        default=None,
        help="Optional immediate engine cutoff periapsis in meters. If reached, the runner stops burning without forcing a stage handoff.",
    )
    parser.add_argument(
        "--handoff-fuel-threshold",
        type=float,
        default=25.0,
        help="Maximum remaining monitored lower-stage propellant before upper-stage handoff is allowed.",
    )
    parser.add_argument(
        "--mun-orbit-altitude",
        type=float,
        default=20_000.0,
        help="Target apoapsis altitude for the final Mun capture orbit.",
    )
    parser.add_argument(
        "--mun-transfer-window-tolerance-deg",
        type=float,
        default=5.0,
        help="Allowed phase-angle error in degrees when waiting for a Mun transfer window.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print additional ascent progress.",
    )
    return parser.parse_args()


def load_generation(path: Path):
    with open(path) as f:
        return json.load(f)


def rank_rockets(generation_data):
    return sorted(
        generation_data["rockets"],
        key=lambda rec: rec["meta"]["score"],
        reverse=True,
    )


def choose_rocket(generation_data, rank: int):
    ranked = rank_rockets(generation_data)
    if rank < 1 or rank > len(ranked):
        raise ValueError(f"rank must be between 1 and {len(ranked)}")
    return ranked[rank - 1]


def default_ship_name(generation_data, rank: int):
    return f"gen_{generation_data['generation']:03d}_rank_{rank:03d}"


def write_craft(rocket_dict, parts_by_name, ship_name: str, save_name: str):
    craft_text, meta = to_craft(rocket_dict, parts_by_name, ship_name=ship_name)
    out_dir = KSP_ROOT / "saves" / save_name / "Ships" / "VAB"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{ship_name}.craft"
    out_path.write_text(craft_text)
    return out_path, meta


def make_run_dir(ship_name: str):
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    run_dir = RESULTS_ROOT / f"{stamp}_{ship_name}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_run_record(run_dir: Path, record: dict):
    out_path = run_dir / "run_record.json"
    out_path.write_text(json.dumps(record, indent=2, sort_keys=True))
    return out_path


def format_met(vessel):
    seconds = max(0, int(vessel.met))
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"T+{hours:02d}:{minutes:02d}:{seconds:02d}"


def verbose_log(vessel, label, message):
    print(f"[{format_met(vessel)}] {label}: {message}")


def verbose_log_change(vessel, cache, key, value, label, message):
    if cache.get(key) == value:
        return
    cache[key] = value
    verbose_log(vessel, label, message)


def part_name_counter(vessel):
    return Counter(part.name for part in vessel.parts.all)


def counter_delta(before, after):
    removed = {}
    added = {}
    for name, count in before.items():
        delta = count - after.get(name, 0)
        if delta > 0:
            removed[name] = delta
    for name, count in after.items():
        delta = count - before.get(name, 0)
        if delta > 0:
            added[name] = delta
    return removed, added


def summarize_counter(counter_obj):
    if not counter_obj:
        return "none"
    return ", ".join(f"{name}x{count}" for name, count in sorted(counter_obj.items()))


def vessel_composition_snapshot(vessel):
    counter = part_name_counter(vessel)
    return {
        "part_count": sum(counter.values()),
        "parts": dict(sorted(counter.items())),
        "mass": vessel.mass,
        "available_thrust": vessel.available_thrust,
        "current_stage": vessel.control.current_stage,
    }


def safe_getattr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def engine_runtime_snapshot(vessel):
    snapshots = []
    engines = safe_getattr(safe_getattr(vessel, "parts"), "engines", []) or []
    for engine in engines:
        part = safe_getattr(engine, "part")
        part_title = safe_getattr(part, "title", safe_getattr(part, "name", "unknown"))
        snapshot = {
            "part_title": part_title,
            "part_name": safe_getattr(part, "name"),
            "stage": safe_getattr(part, "stage"),
            "decouple_stage": safe_getattr(part, "decouple_stage"),
            "active": safe_getattr(engine, "active"),
            "available_thrust": safe_getattr(engine, "available_thrust"),
            "thrust": safe_getattr(engine, "thrust"),
            "max_thrust": safe_getattr(engine, "max_thrust"),
            "specific_impulse": safe_getattr(engine, "specific_impulse"),
            "vacuum_specific_impulse": safe_getattr(engine, "vacuum_specific_impulse"),
            "kerbin_sea_level_specific_impulse": safe_getattr(engine, "kerbin_sea_level_specific_impulse"),
            "throttle": safe_getattr(engine, "throttle"),
            "gimballed": safe_getattr(engine, "gimballed"),
            "has_fuel": safe_getattr(engine, "has_fuel"),
        }
        snapshots.append(snapshot)
    return snapshots


def capture_prelaunch_screenshot(run_dir: Path):
    out_path = run_dir / "prelaunch.png"
    subprocess.run(["screencapture", "-x", str(out_path)], check=True)
    return out_path


def connect():
    return krpc.connect(name="to_the_mun run_saved_rocket")


def wait_for_active_vessel(sc, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        vessel = sc.active_vessel
        if vessel is not None:
            return vessel
        time.sleep(0.1)
    raise RuntimeError("active vessel did not become available after launch")


def project_stage_to_ksp_stage(project_stage: int) -> int:
    return 0 if project_stage == 0 else 2 * project_stage


def infer_stage_propellants(rocket_dict, parts_by_name):
    stage_propellants = {}
    for part_id, project_stage in rocket_dict["stages"].items():
        if not part_id.startswith("eng_"):
            continue
        part = next(part for part in rocket_dict["parts"] if part["id"] == part_id)
        engine_data = parts_by_name[part["type"]]["engine"]
        propellants = tuple(engine_data["propellants"].keys())
        stage_propellants[project_stage_to_ksp_stage(project_stage)] = propellants
    return stage_propellants


def monitored_propellants(stage_propellants):
    names = set()
    for propellants in stage_propellants.values():
        names.update(propellants)
    return tuple(sorted(names))


def stage_resource_amount(vessel, ksp_stage, propellants, cumulative=True):
    resources = vessel.resources_in_decouple_stage(ksp_stage, cumulative=cumulative)
    total = 0.0
    for resource_name in propellants:
        if resources.has_resource(resource_name):
            total += resources.amount(resource_name)
    return total


def stage_resource_breakdown(vessel, ksp_stage, propellants, cumulative=True):
    resources = vessel.resources_in_decouple_stage(ksp_stage, cumulative=cumulative)
    breakdown = {}
    for resource_name in propellants:
        breakdown[resource_name] = resources.amount(resource_name) if resources.has_resource(resource_name) else 0.0
    return breakdown


def vessel_resource_breakdown(vessel, propellants):
    resources = vessel.resources
    breakdown = {}
    for resource_name in propellants:
        breakdown[resource_name] = resources.amount(resource_name) if resources.has_resource(resource_name) else 0.0
    return breakdown


def current_fueled_stage(vessel, propellants, empty_threshold=0.1, max_stage=None):
    control = vessel.control
    max_stage = control.current_stage if max_stage is None else max_stage
    for ksp_stage in range(max_stage, -1, -1):
        amount = stage_resource_amount(vessel, ksp_stage, propellants)
        if amount > empty_threshold:
            return ksp_stage
    return None


def debug_stage_resources(vessel, propellants, max_stage):
    snapshot = {}
    for ksp_stage in range(max_stage, -1, -1):
        snapshot[ksp_stage] = {
            "cumulative": stage_resource_amount(vessel, ksp_stage, propellants, cumulative=True),
            "exclusive": stage_resource_amount(vessel, ksp_stage, propellants, cumulative=False),
        }
    return snapshot


def maybe_stage(vessel, propellants, state, empty_threshold=0.1, min_stage_gap=0.75):
    control = vessel.control
    now = time.time()
    monitored_stage = state.get("monitored_stage")
    if monitored_stage is None:
        monitored_stage = current_fueled_stage(vessel, propellants, empty_threshold)
        state["monitored_stage"] = monitored_stage
    if monitored_stage is None:
        return False

    remaining = stage_resource_amount(vessel, monitored_stage, propellants)
    if remaining > empty_threshold:
        return False
    if control.current_stage <= 0:
        return False
    if now - state.get("last_stage_time", 0.0) < min_stage_gap:
        return False

    before_parts = part_name_counter(vessel)
    control.activate_next_stage()
    state["last_stage_time"] = now
    state["monitored_stage"] = current_fueled_stage(vessel, propellants, empty_threshold)
    after_parts = part_name_counter(vessel)
    removed_parts, added_parts = counter_delta(before_parts, after_parts)
    snapshot = propulsion_snapshot(vessel, propellants, state, empty_threshold=empty_threshold)
    state.setdefault("events", []).append({
        "time": now,
        "kind": "auto_stage_fuel_empty",
        "new_current_stage": control.current_stage,
        "new_monitored_stage": state["monitored_stage"],
        "removed_parts": removed_parts,
        "added_parts": added_parts,
        "propulsion_snapshot": snapshot,
    })
    return True


def has_lower_fueled_stage(vessel, propellants, empty_threshold=0.1):
    control = vessel.control
    if control.current_stage <= 0:
        return False
    next_fueled_stage = current_fueled_stage(
        vessel,
        propellants,
        empty_threshold=empty_threshold,
        max_stage=control.current_stage - 1,
    )
    return next_fueled_stage is not None


def propulsion_snapshot(vessel, propellants, stage_state, empty_threshold=0.1):
    control = vessel.control
    monitored_stage = stage_state.get("monitored_stage")
    current_stage = control.current_stage
    lower_fueled_stage = current_fueled_stage(
        vessel,
        propellants,
        empty_threshold=empty_threshold,
        max_stage=current_stage,
    )
    snapshot = {
        "current_stage": current_stage,
        "monitored_stage": monitored_stage,
        "lower_fueled_stage": lower_fueled_stage,
        "available_thrust": vessel.available_thrust,
        "actual_thrust": vessel.thrust,
        "throttle": control.throttle,
        "apoapsis": vessel.orbit.apoapsis_altitude,
        "periapsis": vessel.orbit.periapsis_altitude,
        "mass": vessel.mass,
        "vessel_resource_breakdown": vessel_resource_breakdown(vessel, propellants),
        "engine_runtime": engine_runtime_snapshot(vessel),
    }
    if monitored_stage is not None:
        snapshot["monitored_stage_resources"] = stage_resource_amount(vessel, monitored_stage, propellants)
        snapshot["monitored_stage_breakdown"] = stage_resource_breakdown(vessel, monitored_stage, propellants)
    if lower_fueled_stage is not None:
        snapshot["lower_fueled_stage_resources"] = stage_resource_amount(vessel, lower_fueled_stage, propellants)
        snapshot["lower_fueled_stage_breakdown"] = stage_resource_breakdown(vessel, lower_fueled_stage, propellants)
    if current_stage is not None and current_stage >= 0:
        snapshot["current_stage_breakdown"] = stage_resource_breakdown(vessel, current_stage, propellants)
    return snapshot


def angular_speed(vessel):
    wx, wy, wz = vessel.angular_velocity(vessel.surface_reference_frame)
    components = (float(wx), float(wy), float(wz))
    if not all(math.isfinite(component) for component in components):
        return float("inf")
    try:
        return math.hypot(*components)
    except OverflowError:
        return float("inf")


def vector_norm(vec):
    return math.sqrt(sum(float(component) ** 2 for component in vec))


def normalize_angle(angle):
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def phase_angle(vessel, target_body, central_body):
    frame = central_body.non_rotating_reference_frame
    vessel_pos = vessel.position(frame)
    target_pos = target_body.position(frame)
    # KSP's non-rotating body frame uses X/Z for the equatorial orbital plane.
    # Using Y here makes the phase angle jump around the +/-180deg boundary.
    vessel_angle = math.atan2(vessel_pos[2], vessel_pos[0])
    target_angle = math.atan2(target_pos[2], target_pos[0])
    return normalize_angle(target_angle - vessel_angle)


def set_velocity_frame_attitude(vessel, ap, forward=True, verbose=False, label="velocity_target"):
    ap.reference_frame = vessel.surface_velocity_reference_frame
    ap.target_direction = (0, 1, 0) if forward else (0, -1, 0)
    if verbose:
        direction = "prograde" if forward else "retrograde"
        print(
            f"{label}: reference_frame=surface_velocity mode={direction} "
            f"body={vessel.orbit.body.name} apo={vessel.orbit.apoapsis_altitude:.0f} "
            f"peri={vessel.orbit.periapsis_altitude:.0f}"
        )


def set_orbital_velocity_attitude(vessel, ap, forward=True, verbose=False, label="orbital_target"):
    ap.reference_frame = vessel.orbital_reference_frame
    ap.target_direction = (0, 1, 0) if forward else (0, -1, 0)
    if verbose:
        direction = "prograde" if forward else "retrograde"
        print(
            f"{label}: reference_frame=orbital mode={direction} "
            f"body={vessel.orbit.body.name} apo={vessel.orbit.apoapsis_altitude:.0f} "
            f"peri={vessel.orbit.periapsis_altitude:.0f}"
        )


def stabilize_after_stage(
    vessel,
    ap,
    target_pitch,
    target_heading=90,
    settle_time=1.5,
    max_angular_speed=0.15,
    timeout=8.0,
):
    ap.engage()
    ap.target_roll = float("nan")
    ap.target_pitch_and_heading(target_pitch, target_heading)
    time.sleep(settle_time)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if angular_speed(vessel) <= max_angular_speed:
            return True
        time.sleep(0.1)
    return False


def stabilize_vehicle(
    vessel,
    ap,
    target_pitch,
    target_heading=90,
    verbose=False,
    label="stabilize_only",
    post_stage_mode="pitch_heading",
):
    control = vessel.control
    before_spin = angular_speed(vessel)
    if post_stage_mode == "orbit_target":
        set_orbital_insertion_attitude(vessel, ap, verbose=verbose, label=label)
    else:
        ap.engage()
        ap.target_roll = float("nan")
        ap.target_pitch_and_heading(target_pitch, target_heading)

    stable = stabilize_after_stage(vessel, ap, target_pitch, target_heading=target_heading)
    after_spin = angular_speed(vessel)
    control.throttle = 0.0

    if verbose:
        print(
            f"{label}: complete stable={stable} angular_speed_before={before_spin:.3f} "
            f"angular_speed_after={after_spin:.3f} peri={vessel.orbit.periapsis_altitude:.0f} "
            f"throttle={control.throttle:.2f}"
        )
    return stable


def set_orbital_insertion_attitude(vessel, ap, verbose=False, label="orbit_target"):
    """Point the vessel at orbital prograde for vacuum orbital maneuvers."""
    set_orbital_velocity_attitude(vessel, ap, forward=True, verbose=verbose, label=label)


def set_retrograde_attitude(vessel, ap, verbose=False, label="retrograde_target"):
    set_orbital_velocity_attitude(vessel, ap, forward=False, verbose=verbose, label=label)


def stage_with_stability(
    vessel,
    ap,
    stage_state,
    target_pitch,
    target_heading=90,
    throttle_resume=0.1,
    pre_stage_throttle=0.0,
    verbose=False,
    label="stage_transition",
    post_stage_mode="pitch_heading",
):
    control = vessel.control
    original_throttle = control.throttle
    before_stage = control.current_stage
    before_spin = angular_speed(vessel)
    if verbose:
        removed_parts = stage_state["events"][-1].get("removed_parts", {})
        snapshot = vessel_composition_snapshot(vessel)
        verbose_log(
            vessel,
            label,
            f"{label}: begin current_stage={before_stage} throttle={original_throttle:.2f} "
            f"angular_speed={before_spin:.3f} target_pitch={target_pitch:.1f}",
        )
    control.throttle = pre_stage_throttle
    time.sleep(0.5)
    fired = ensure_thrust_available(vessel, stage_state)
    if not fired:
        if verbose:
            print(f"{label}: no stage fired")
        return False
    if post_stage_mode == "orbit_target":
        set_orbital_insertion_attitude(vessel, ap, verbose=verbose, label=label)
    stable = stabilize_after_stage(vessel, ap, target_pitch, target_heading=target_heading)
    after_spin = angular_speed(vessel)
    if stable:
        control.throttle = min(max(original_throttle, throttle_resume), 1.0)
    else:
        control.throttle = 0.0
    stage_state.setdefault("events", []).append({
        "time": time.time(),
        "kind": "post_stage_stabilized" if stable else "post_stage_unstable_timeout",
        "angular_speed_before": before_spin,
        "angular_speed_after": after_spin,
        "target_pitch": target_pitch,
        "target_heading": target_heading,
        "label": label,
        "post_stage_mode": post_stage_mode,
        "stage_before": before_stage,
        "stage_after": control.current_stage,
    })
    if verbose:
        removed_parts = stage_state["events"][-1].get("removed_parts", {})
        snapshot = vessel_composition_snapshot(vessel)
        verbose_log(
            vessel,
            label,
            f"{label}: complete stage_before={before_stage} stage_after={control.current_stage} "
            f"stable={stable} angular_speed_after={after_spin:.3f} "
            f"peri={vessel.orbit.periapsis_altitude:.0f} throttle={control.throttle:.2f} "
            f"removed={summarize_counter(removed_parts)} remaining={summarize_counter(snapshot['parts'])}",
        )
    return True


def hold_orbital_insertion_guidance(vessel, ap, verbose=False, label="coast_hold"):
    set_orbital_insertion_attitude(vessel, ap, verbose=verbose, label=label)
    ap.target_roll = float("nan")


def hold_retrograde_guidance(vessel, ap, verbose=False, label="retro_hold"):
    set_retrograde_attitude(vessel, ap, verbose=verbose, label=label)
    ap.target_roll = float("nan")


def ensure_thrust_available(vessel, stage_state, min_stage_gap=0.75):
    control = vessel.control
    if vessel.available_thrust > 1e-3:
        return False
    if control.current_stage <= 0:
        return False
    now = time.time()
    if now - stage_state.get("last_stage_time", 0.0) < min_stage_gap:
        return False
    before_parts = part_name_counter(vessel)
    control.activate_next_stage()
    stage_state["last_stage_time"] = now
    after_parts = part_name_counter(vessel)
    removed_parts, added_parts = counter_delta(before_parts, after_parts)
    snapshot = vessel_composition_snapshot(vessel)
    stage_state.setdefault("events", []).append({
        "time": now,
        "kind": "auto_stage_ensure_thrust",
        "new_current_stage": control.current_stage,
        "new_monitored_stage": stage_state.get("monitored_stage"),
        "removed_parts": removed_parts,
        "added_parts": added_parts,
        "vessel_snapshot": snapshot,
    })
    return True


def handoff_to_upper_stage(vessel, stage_state, propellants, min_stage_gap=0.75):
    control = vessel.control
    if control.current_stage <= 0:
        return False
    now = time.time()
    if now - stage_state.get("last_stage_time", 0.0) < min_stage_gap:
        return False
    before_parts = part_name_counter(vessel)
    control.activate_next_stage()
    stage_state["last_stage_time"] = now
    stage_state["monitored_stage"] = current_fueled_stage(vessel, propellants)
    after_parts = part_name_counter(vessel)
    removed_parts, added_parts = counter_delta(before_parts, after_parts)
    snapshot = propulsion_snapshot(vessel, propellants, stage_state)
    stage_state.setdefault("events", []).append({
        "time": now,
        "kind": "phase_handoff_stage",
        "new_current_stage": control.current_stage,
        "new_monitored_stage": stage_state["monitored_stage"],
        "removed_parts": removed_parts,
        "added_parts": added_parts,
        "propulsion_snapshot": snapshot,
    })
    return True


def ignite_next_stage_if_needed(vessel, stage_state, verbose=False, label="ignite_next_stage"):
    control = vessel.control
    if vessel.available_thrust > 1e-3:
        return False
    if control.current_stage <= 0:
        return False
    before_parts = part_name_counter(vessel)
    before_stage = control.current_stage
    control.activate_next_stage()
    stage_state["last_stage_time"] = time.time()
    after_parts = part_name_counter(vessel)
    removed_parts, added_parts = counter_delta(before_parts, after_parts)
    snapshot = vessel_composition_snapshot(vessel)
    propulsion = propulsion_snapshot(vessel, ("LiquidFuel", "Oxidizer"), stage_state)
    stage_state.setdefault("events", []).append({
        "time": stage_state["last_stage_time"],
        "kind": "explicit_ignite_next_stage",
        "stage_before": before_stage,
        "stage_after": control.current_stage,
        "removed_parts": removed_parts,
        "added_parts": added_parts,
        "snapshot": snapshot,
        "propulsion_snapshot": propulsion,
    })
    if verbose:
        verbose_log(
            vessel,
            label,
            f"stage_before={before_stage} stage_after={control.current_stage} "
            f"removed={summarize_counter(removed_parts)} added={summarize_counter(added_parts)} "
            f"remaining={summarize_counter(snapshot['parts'])} thrust={snapshot['available_thrust']:.1f} "
            f"mass={snapshot['mass']:.1f} resources={propulsion.get('current_stage_breakdown', {})}",
        )
    return True


def set_turn_pitch(vessel, turn_start_altitude, turn_end_altitude):
    altitude = vessel.flight().mean_altitude
    if altitude <= turn_start_altitude:
        pitch = 90.0
    elif altitude >= turn_end_altitude:
        pitch = 0.0
    else:
        fraction = (altitude - turn_start_altitude) / (turn_end_altitude - turn_start_altitude)
        pitch = 90.0 * (1.0 - fraction)
    vessel.auto_pilot.target_pitch_and_heading(pitch, 90)


def set_core_finish_guidance(vessel):
    apoapsis = vessel.orbit.apoapsis_altitude
    if apoapsis >= 130_000.0:
        pitch = 3.0
    elif apoapsis >= 110_000.0:
        pitch = 5.0
    elif apoapsis >= 90_000.0:
        pitch = 7.0
    else:
        pitch = 10.0
    vessel.auto_pilot.target_pitch_and_heading(pitch, 90)
    return pitch


def desired_rails_warp_for_seconds(seconds_until_event):
    if seconds_until_event > 3600:
        return 7
    if seconds_until_event > 1200:
        return 6
    if seconds_until_event > 300:
        return 5
    if seconds_until_event > 90:
        return 4
    if seconds_until_event > 30:
        return 3
    if seconds_until_event > 10:
        return 2
    return 0


def desired_rails_warp_for_apoapsis_coast(seconds_until_apoapsis):
    if seconds_until_apoapsis > 1800:
        return 6
    if seconds_until_apoapsis > 600:
        return 5
    if seconds_until_apoapsis > 180:
        return 3
    if seconds_until_apoapsis > 90:
        return 2
    if seconds_until_apoapsis > 45:
        return 1
    return 0


def desired_rails_warp_for_phase_error(error_deg):
    if error_deg > 60:
        return 6
    if error_deg > 25:
        return 5
    if error_deg > 10:
        return 3
    if error_deg > 5:
        return 1
    return 0


def set_rails_warp(sc, factor, verbose=False, label="warp"):
    factor = int(max(0, factor))
    if sc.rails_warp_factor == factor:
        return
    sc.rails_warp_factor = factor
    if verbose:
        print(f"{label}: rails_warp_factor={factor}")


def clear_rails_warp(sc, verbose=False, label="warp"):
    set_rails_warp(sc, 0, verbose=verbose, label=label)


def launch_from_vab(sc, ship_name: str):
    sc.launch_vessel_from_vab(ship_name)
    time.sleep(1.0)
    return wait_for_active_vessel(sc)


def fly_standard_ascent(
    rocket_dict,
    parts_by_name,
    vessel,
    sc=None,
    target_apoapsis=80_000,
    target_periapsis=70_000,
    periapsis_cutoff=None,
    turn_start_altitude=250.0,
    turn_end_altitude=45_000.0,
    handoff_altitude=45_000.0,
    handoff_fuel_threshold=25.0,
    verbose=False,
):
    body = vessel.orbit.body
    stage_propellants = infer_stage_propellants(rocket_dict, parts_by_name)
    propellants = monitored_propellants(stage_propellants)
    stage_state = {
        "monitored_stage": None,
        "last_stage_time": 0.0,
        "events": [],
    }
    diagnostics = {
        "designed_stage_propellants": {str(k): list(v) for k, v in stage_propellants.items()},
    }
    core_finish_start_apoapsis = target_apoapsis * 0.9
    preferred_handoff_periapsis_min = -50_000.0
    preferred_handoff_periapsis_max = 10_000.0
    preferred_handoff_apoapsis_min = 90_000.0
    preferred_handoff_apoapsis_max = 120_000.0
    safety_handoff_apoapsis = 140_000.0
    safety_handoff_periapsis_floor = -100_000.0

    control = vessel.control
    ap = vessel.auto_pilot
    control.stage_lock = False
    control.sas = False
    ap.engage()
    ap.target_roll = float("nan")
    ap.target_pitch_and_heading(90, 90)
    control.throttle = 1.0
    control.activate_next_stage()
    stage_state["last_stage_time"] = time.time()
    time.sleep(0.5)
    stage_state["monitored_stage"] = current_fueled_stage(vessel, propellants)

    if verbose:
        print(f"designed stage propellants: {stage_propellants}")
    initial_resources = debug_stage_resources(
        vessel,
        propellants,
        max(control.current_stage, max(stage_propellants.keys(), default=0)),
    )
    diagnostics["initial_stage_resources"] = initial_resources
    diagnostics["initial_vessel_resources"] = vessel_resource_breakdown(vessel, propellants)
    if verbose:
        print("initial stage resources:", initial_resources)
        print("initial vessel resources:", diagnostics["initial_vessel_resources"])

    phase = "liftoff_ascent"
    stage_state.setdefault("events", []).append({
        "time": time.time(),
        "kind": "phase_enter",
        "phase": phase,
    })
    handed_off = False
    log_cache = {}
    while True:
        altitude = vessel.flight().mean_altitude
        apoapsis = vessel.orbit.apoapsis_altitude
        periapsis = vessel.orbit.periapsis_altitude
        if phase == "liftoff_ascent":
            set_turn_pitch(vessel, turn_start_altitude, turn_end_altitude)
            control.throttle = 1.0
            if apoapsis >= core_finish_start_apoapsis:
                phase = "core_stage_finish"
                stage_state.setdefault("events", []).append({
                    "time": time.time(),
                    "kind": "phase_enter",
                    "phase": phase,
                    "altitude": altitude,
                    "apoapsis": apoapsis,
                    "periapsis": periapsis,
                })
                if verbose:
                    verbose_log(
                        vessel,
                        "phase_change",
                        f"phase change -> {phase} alt={altitude:.0f} apo={apoapsis:.0f} "
                        f"peri={periapsis:.0f}",
                    )

        if phase == "core_stage_finish":
            set_core_finish_guidance(vessel)
            if apoapsis >= 110_000.0:
                control.throttle = 0.05
            elif apoapsis >= 90_000.0:
                control.throttle = 0.20
            else:
                control.throttle = 0.50

        if periapsis_cutoff is not None and periapsis >= periapsis_cutoff:
            if verbose:
                print(
                    f"peri cutoff reached alt={altitude:.0f} apo={apoapsis:.0f} "
                    f"peri={periapsis:.0f}; cutting throttle without handoff"
                )
            control.throttle = 0.0
            stage_state.setdefault("events", []).append({
                "time": time.time(),
                "kind": "periapsis_cutoff",
                "altitude": altitude,
                "apoapsis": apoapsis,
                "periapsis": periapsis,
                "current_stage": control.current_stage,
                "monitored_stage": stage_state["monitored_stage"],
            })
            break

        current_pitch = ap.target_pitch
        staged = maybe_stage(vessel, propellants, stage_state)
        if staged:
            time.sleep(1.0)
            control.throttle = max(control.throttle, 0.25)
            stage_with_stability(
                vessel,
                ap,
                stage_state,
                current_pitch,
                verbose=verbose,
                label="fuel_empty_stage",
            )
            stage_state["monitored_stage"] = current_fueled_stage(vessel, propellants)

        remaining = None
        if stage_state["monitored_stage"] is not None:
            remaining = stage_resource_amount(vessel, stage_state["monitored_stage"], propellants)

        near_empty = (
            remaining is not None
            and remaining <= handoff_fuel_threshold
        )
        in_preferred_handoff_window = (
            preferred_handoff_periapsis_min <= periapsis <= preferred_handoff_periapsis_max
            and preferred_handoff_apoapsis_min <= apoapsis <= preferred_handoff_apoapsis_max
        )
        in_safety_handoff_region = (
            apoapsis >= safety_handoff_apoapsis
            and periapsis >= safety_handoff_periapsis_floor
        )
        should_handoff = (
            phase == "core_stage_finish"
            and altitude >= handoff_altitude
            and control.current_stage > 0
            and (in_preferred_handoff_window or near_empty or in_safety_handoff_region)
        )
        if should_handoff:
            if in_preferred_handoff_window:
                handoff_reason = "preferred_window"
            elif near_empty:
                handoff_reason = "fuel_near_empty"
            else:
                handoff_reason = "safety_window"
            if verbose:
                verbose_log(
                    vessel,
                    "handoff",
                    f"handoff gate reached alt={altitude:.0f} apo={apoapsis:.0f} "
                    f"peri={periapsis:.0f} remaining={remaining} "
                    f"reason={handoff_reason}; handing off to the next phase/stage",
                )
            control.throttle = 0.0
            if stage_state["monitored_stage"] is not None and vessel.control.current_stage > 0:
                stage_state.setdefault("events", []).append({
                    "time": time.time(),
                    "kind": "phase_handoff_trigger",
                    "reason": handoff_reason,
                    "altitude": altitude,
                    "apoapsis": apoapsis,
                    "periapsis": periapsis,
                    "remaining": remaining,
                    "current_stage": control.current_stage,
                    "monitored_stage": stage_state["monitored_stage"],
                })
                handoff_to_upper_stage(vessel, stage_state, propellants)
                time.sleep(1.0)
                phase = "coast_to_apoapsis"
                stage_state.setdefault("events", []).append({
                    "time": time.time(),
                    "kind": "phase_enter",
                    "phase": phase,
                    "altitude": vessel.flight().mean_altitude,
                    "apoapsis": vessel.orbit.apoapsis_altitude,
                    "periapsis": vessel.orbit.periapsis_altitude,
                })
                stable = stabilize_vehicle(
                    vessel,
                    ap,
                    0.0,
                    verbose=verbose,
                    label="phase_handoff",
                    post_stage_mode="orbit_target",
                )
                stage_state.setdefault("events", []).append({
                    "time": time.time(),
                    "kind": "phase_handoff_stabilized" if stable else "phase_handoff_unstable_timeout",
                    "angular_speed_after": angular_speed(vessel),
                    "target_pitch": 0.0,
                })
                if verbose:
                    handoff_event = stage_state["events"][-2] if len(stage_state["events"]) >= 2 else {}
                    snapshot = vessel_composition_snapshot(vessel)
                    propulsion = propulsion_snapshot(vessel, propellants, stage_state)
                    verbose_log(
                        vessel,
                        "phase_handoff",
                        f"phase_handoff: post-stage current_stage={control.current_stage} "
                        f"angular_speed={angular_speed(vessel):.3f} "
                        f"apo={vessel.orbit.apoapsis_altitude:.0f} "
                        f"peri={vessel.orbit.periapsis_altitude:.0f} "
                        f"throttle={control.throttle:.2f} "
                        f"removed={summarize_counter(handoff_event.get('removed_parts', {}))} "
                        f"remaining={summarize_counter(snapshot['parts'])} "
                        f"resources={propulsion.get('current_stage_breakdown', {})} "
                        f"engines={propulsion.get('engine_runtime', [])}",
                    )
            handed_off = True
            break

        if verbose:
            ascent_band = (
                phase,
                int(apoapsis // 10_000),
                int(periapsis // 10_000),
                control.current_stage,
                round(control.throttle, 2),
            )
            verbose_log_change(
                vessel,
                log_cache,
                "ascent_status",
                ascent_band,
                "ascent",
                f"ascent alt={altitude:8.0f}m apo={apoapsis:8.0f}m peri={periapsis:8.0f}m "
                f"phase={phase:>17s} pitch={vessel.auto_pilot.target_pitch:5.1f} "
                f"stage={control.current_stage} fuel_stage={stage_state['monitored_stage']} "
                f"fuel={remaining} throttle={control.throttle:.2f}",
            )
        time.sleep(0.1)
    control.throttle = 0.0

    if handed_off:
        missed_apoapsis = False
        prev_time_to_apoapsis = None
        coast_log_cache = {}
        while vessel.orbit.time_to_apoapsis > 20:
            hold_orbital_insertion_guidance(vessel, ap)
            maybe_stage(vessel, propellants, stage_state)
            time_to_apoapsis = vessel.orbit.time_to_apoapsis
            if (
                prev_time_to_apoapsis is not None
                and prev_time_to_apoapsis < 600
                and time_to_apoapsis > prev_time_to_apoapsis + 60
            ):
                missed_apoapsis = True
                stage_state.setdefault("events", []).append({
                    "time": time.time(),
                    "kind": "orbital_insertion_missed_apoapsis",
                    "previous_time_to_apoapsis": prev_time_to_apoapsis,
                    "time_to_apoapsis": time_to_apoapsis,
                    "apoapsis": vessel.orbit.apoapsis_altitude,
                    "periapsis": vessel.orbit.periapsis_altitude,
                })
                if verbose:
                    verbose_log(
                        vessel,
                        "coast",
                        f"coast missed apoapsis previous_ttAp={prev_time_to_apoapsis:.1f}s "
                        f"ttAp={time_to_apoapsis:.1f}s apo={vessel.orbit.apoapsis_altitude:.0f} "
                        f"peri={vessel.orbit.periapsis_altitude:.0f}",
                    )
                break
            if sc is not None:
                set_rails_warp(
                    sc,
                    desired_rails_warp_for_apoapsis_coast(time_to_apoapsis),
                    verbose=verbose,
                    label="coast_warp",
                )
            if verbose:
                coast_band = (
                    int(vessel.orbit.apoapsis_altitude // 10_000),
                    int(vessel.orbit.periapsis_altitude // 10_000),
                    int(time_to_apoapsis // 60),
                    control.current_stage,
                )
                verbose_log_change(
                    vessel,
                    coast_log_cache,
                    "coast_status",
                    coast_band,
                    "coast",
                    f"coast apo={vessel.orbit.apoapsis_altitude:8.0f}m "
                    f"peri={vessel.orbit.periapsis_altitude:8.0f}m "
                    f"ttAp={time_to_apoapsis:6.1f}s "
                    f"stage={control.current_stage}",
                )
            prev_time_to_apoapsis = time_to_apoapsis
            time.sleep(0.5)
        if sc is not None:
            clear_rails_warp(sc, verbose=verbose, label="coast_warp")

        if not missed_apoapsis:
            phase = "orbital_insertion"
            stage_state.setdefault("events", []).append({
                "time": time.time(),
                "kind": "phase_enter",
                "phase": phase,
                "apoapsis": vessel.orbit.apoapsis_altitude,
                "periapsis": vessel.orbit.periapsis_altitude,
                "time_to_apoapsis": vessel.orbit.time_to_apoapsis,
            })
            hold_orbital_insertion_guidance(vessel, ap, verbose=verbose, label="orbital_insertion")
            if verbose:
                verbose_log(
                    vessel,
                    "orbital_insertion_setup",
                    f"snapshot={vessel_composition_snapshot(vessel)} "
                    f"propulsion={propulsion_snapshot(vessel, propellants, stage_state)}",
                )
            ignite_next_stage_if_needed(
                vessel,
                stage_state,
                verbose=verbose,
                label="orbital_insertion_ignite",
            )
            insertion_start = time.time()
            control.throttle = 1.0
            insertion_log_cache = {}
            while vessel.orbit.periapsis_altitude < target_periapsis:
                hold_orbital_insertion_guidance(vessel, ap)
                maybe_stage(vessel, propellants, stage_state)
                if vessel.available_thrust < 1e-3 and has_lower_fueled_stage(vessel, propellants):
                    stage_with_stability(
                        vessel,
                        ap,
                        stage_state,
                        0.0,
                        throttle_resume=0.2,
                        verbose=verbose,
                        label="orbital_insertion_stage",
                        post_stage_mode="orbit_target",
                    )
                periapsis = vessel.orbit.periapsis_altitude
                apoapsis = vessel.orbit.apoapsis_altitude
                if verbose:
                    insertion_band = (
                        int(periapsis // 10_000),
                        int(apoapsis // 10_000),
                        int(vessel.orbit.time_to_apoapsis // 10),
                        control.current_stage,
                        round(control.throttle, 2),
                    )
                    verbose_log_change(
                        vessel,
                        insertion_log_cache,
                        "insertion_status",
                        insertion_band,
                        "insertion",
                        f"insertion peri={periapsis:8.0f}m apo={apoapsis:8.0f}m "
                        f"ttAp={vessel.orbit.time_to_apoapsis:6.1f}s "
                        f"stage={control.current_stage} throttle={control.throttle:.2f}",
                    )
                if vessel.orbit.time_to_apoapsis < -5:
                    break
                if time.time() - insertion_start > 240:
                    stage_state.setdefault("events", []).append({
                        "time": time.time(),
                        "kind": "orbital_insertion_timeout",
                        "periapsis": vessel.orbit.periapsis_altitude,
                        "apoapsis": vessel.orbit.apoapsis_altitude,
                    })
                    break
                if periapsis > target_periapsis * 0.9:
                    control.throttle = 0.25
                if periapsis > target_periapsis * 0.98:
                    control.throttle = 0.1
                time.sleep(0.1)
            control.throttle = 0.0

    return {
        "final_apoapsis": vessel.orbit.apoapsis_altitude,
        "final_periapsis": vessel.orbit.periapsis_altitude,
        "situation": str(vessel.situation),
        "stage_events": stage_state["events"],
        "diagnostics": diagnostics,
    }


def wait_for_transfer_window(
    sc,
    vessel,
    target_body,
    central_body,
    required_phase,
    tolerance_rad,
    verbose=False,
    timeout=7200.0,
):
    start = time.time()
    log_cache = {}
    previous_error = None
    previous_error_deg = None
    while time.time() - start < timeout:
        current_phase = phase_angle(vessel, target_body, central_body)
        error = normalize_angle(current_phase - required_phase)
        error_deg = abs(math.degrees(error))
        if sc is not None:
            set_rails_warp(
                sc,
                desired_rails_warp_for_phase_error(error_deg),
                verbose=verbose,
                label="transfer_window_warp",
            )
        if verbose:
            phase_band = (
                round(error_deg),
                -1 if error < 0 else 1,
                sc.rails_warp_factor if sc is not None else 0,
            )
            verbose_log_change(
                vessel,
                log_cache,
                "transfer_window",
                phase_band,
                "transfer_window",
                f"transfer_window target={target_body.name} "
                f"phase={math.degrees(current_phase):6.2f}deg "
                f"required={math.degrees(required_phase):6.2f}deg "
                f"error={math.degrees(error):6.2f}deg",
            )
        if abs(error) <= tolerance_rad:
            if sc is not None:
                clear_rails_warp(sc, verbose=verbose, label="transfer_window_warp")
            return {
                "phase_deg": math.degrees(current_phase),
                "required_phase_deg": math.degrees(required_phase),
                "error_deg": math.degrees(error),
                "window_capture": "within_tolerance",
            }
        crossed_window = (
            previous_error is not None
            and error * previous_error < 0.0
            and previous_error_deg is not None
            and min(error_deg, previous_error_deg) <= max(15.0, math.degrees(tolerance_rad) * 2.0)
        )
        if crossed_window:
            if sc is not None:
                clear_rails_warp(sc, verbose=verbose, label="transfer_window_warp")
            chosen_error = error if error_deg <= previous_error_deg else previous_error
            return {
                "phase_deg": math.degrees(current_phase),
                "required_phase_deg": math.degrees(required_phase),
                "error_deg": math.degrees(chosen_error),
                "window_capture": "crossed_window",
                "previous_error_deg": math.degrees(previous_error),
                "current_error_deg": math.degrees(error),
            }
        previous_error = error
        previous_error_deg = error_deg
        time.sleep(2.0)
    if sc is not None:
        clear_rails_warp(sc, verbose=verbose, label="transfer_window_warp")
    return None


def burn_until_apoapsis(
    vessel,
    ap,
    stage_state,
    propellants,
    target_apoapsis,
    verbose=False,
    label="transfer_burn",
    timeout=240.0,
):
    control = vessel.control
    start = time.time()
    log_cache = {}
    start_snapshot = propulsion_snapshot(vessel, propellants, stage_state)
    no_actual_thrust_start = None
    set_orbital_insertion_attitude(vessel, ap, verbose=verbose, label=label)
    if verbose:
        verbose_log(vessel, label, f"start_snapshot={start_snapshot}")
    control.throttle = 1.0
    while vessel.orbit.apoapsis_altitude < target_apoapsis:
        hold_orbital_insertion_guidance(vessel, ap)
        maybe_stage(vessel, propellants, stage_state)
        if vessel.available_thrust < 1e-3 and has_lower_fueled_stage(vessel, propellants):
            stage_with_stability(
                vessel,
                ap,
                stage_state,
                0.0,
                throttle_resume=0.2,
                verbose=verbose,
                label=f"{label}_stage",
                post_stage_mode="orbit_target",
            )
        elif vessel.available_thrust < 1e-3:
            control.throttle = 0.0
            failure_snapshot = propulsion_snapshot(vessel, propellants, stage_state)
            if verbose:
                verbose_log(vessel, label, f"no thrust available snapshot={failure_snapshot}")
            return {
                "ok": False,
                "reason": "no_thrust_available",
                "start_snapshot": start_snapshot,
                "failure_snapshot": failure_snapshot,
            }
        apoapsis = vessel.orbit.apoapsis_altitude
        actual_thrust = vessel.thrust
        fuel_breakdown = vessel_resource_breakdown(vessel, propellants)
        if verbose:
            burn_band = (
                int(apoapsis // 100_000),
                control.current_stage,
                round(control.throttle, 2),
                int(vessel.available_thrust > 1e-3),
                int(actual_thrust > 1e-3),
            )
            verbose_log_change(
                vessel,
                log_cache,
                "burn_status",
                burn_band,
                label,
                f"{label} apo={apoapsis:8.0f}m "
                f"target={target_apoapsis:8.0f}m stage={control.current_stage} "
                f"throttle={control.throttle:.2f} available_thrust={vessel.available_thrust:.1f} "
                f"actual_thrust={actual_thrust:.1f} resources={fuel_breakdown}",
            )
        if control.throttle > 0.5 and vessel.available_thrust > 1e-3 and actual_thrust < 1e-3:
            if no_actual_thrust_start is None:
                no_actual_thrust_start = time.time()
            elif time.time() - no_actual_thrust_start > 5.0:
                control.throttle = 0.0
                failure_snapshot = propulsion_snapshot(vessel, propellants, stage_state)
                if verbose:
                    verbose_log(vessel, label, f"no actual thrust snapshot={failure_snapshot}")
                return {
                    "ok": False,
                    "reason": "no_actual_thrust",
                    "start_snapshot": start_snapshot,
                    "failure_snapshot": failure_snapshot,
                }
        else:
            no_actual_thrust_start = None
        if time.time() - start > timeout:
            control.throttle = 0.0
            return {
                "ok": False,
                "reason": "timeout",
                "start_snapshot": start_snapshot,
                "failure_snapshot": propulsion_snapshot(vessel, propellants, stage_state),
            }
        if apoapsis > target_apoapsis * 0.9:
            control.throttle = 0.25
        if apoapsis > target_apoapsis * 0.98:
            control.throttle = 0.1
        time.sleep(0.1)
    control.throttle = 0.0
    return {
        "ok": True,
        "reason": "target_reached",
        "start_snapshot": start_snapshot,
        "final_snapshot": propulsion_snapshot(vessel, propellants, stage_state),
    }


def wait_for_body_change(sc, vessel, body_name, verbose=False, timeout=21600.0):
    start = time.time()
    log_cache = {}
    while time.time() - start < timeout:
        current_name = vessel.orbit.body.name
        if sc is not None:
            seconds_until_event = max(vessel.orbit.time_to_soi_change, 0.0)
            set_rails_warp(
                sc,
                desired_rails_warp_for_seconds(seconds_until_event),
                verbose=verbose,
                label="soi_coast_warp",
            )
        if verbose:
            coast_band = (
                current_name,
                sc.rails_warp_factor if sc is not None else 0,
                int(vessel.orbit.time_to_soi_change // 60) if vessel.orbit.time_to_soi_change > 0 else 0,
            )
            verbose_log_change(
                vessel,
                log_cache,
                "soi_coast",
                coast_band,
                "coast_to_soi",
                f"coast_to_soi current_body={current_name} "
                f"apo={vessel.orbit.apoapsis_altitude:.0f} peri={vessel.orbit.periapsis_altitude:.0f}",
            )
        if current_name == body_name:
            if sc is not None:
                clear_rails_warp(sc, verbose=verbose, label="soi_coast_warp")
            return True
        time.sleep(5.0)
    if sc is not None:
        clear_rails_warp(sc, verbose=verbose, label="soi_coast_warp")
    return False


def capture_at_body(
    sc,
    vessel,
    ap,
    stage_state,
    propellants,
    body_name,
    target_apoapsis_altitude,
    verbose=False,
    timeout=2400.0,
):
    control = vessel.control
    start = time.time()
    log_cache = {}
    while vessel.orbit.body.name == body_name and vessel.orbit.time_to_periapsis > 30:
        if sc is not None:
            set_rails_warp(
                sc,
                desired_rails_warp_for_seconds(vessel.orbit.time_to_periapsis),
                verbose=verbose,
                label="capture_coast_warp",
            )
        if verbose:
            coast_band = (
                int(vessel.orbit.periapsis_altitude // 10_000),
                int(vessel.orbit.apoapsis_altitude // 10_000),
                int(vessel.orbit.time_to_periapsis // 60),
            )
            verbose_log_change(
                vessel,
                log_cache,
                "capture_coast",
                coast_band,
                "mun_coast",
                f"mun_coast peri={vessel.orbit.periapsis_altitude:8.0f}m "
                f"apo={vessel.orbit.apoapsis_altitude:8.0f}m "
                f"ttPe={vessel.orbit.time_to_periapsis:6.1f}s",
            )
        time.sleep(1.0)
    if sc is not None:
        clear_rails_warp(sc, verbose=verbose, label="capture_coast_warp")

    hold_retrograde_guidance(vessel, ap, verbose=verbose, label="mun_capture")
    control.throttle = 1.0
    target_apoapsis = vessel.orbit.body.equatorial_radius + target_apoapsis_altitude
    capture_log_cache = {}
    while time.time() - start < timeout:
        hold_retrograde_guidance(vessel, ap)
        maybe_stage(vessel, propellants, stage_state)
        if vessel.available_thrust < 1e-3 and has_lower_fueled_stage(vessel, propellants):
            stage_with_stability(
                vessel,
                ap,
                stage_state,
                0.0,
                throttle_resume=0.2,
                verbose=verbose,
                label="mun_capture_stage",
                post_stage_mode="orbit_target",
            )
            hold_retrograde_guidance(vessel, ap)
        eccentricity = vessel.orbit.eccentricity
        apoapsis = vessel.orbit.apoapsis
        apoapsis_altitude = vessel.orbit.apoapsis_altitude
        periapsis_altitude = vessel.orbit.periapsis_altitude
        if verbose:
            capture_band = (
                round(eccentricity, 2),
                int(apoapsis_altitude // 10_000),
                int(periapsis_altitude // 10_000),
                control.current_stage,
                round(control.throttle, 2),
            )
            verbose_log_change(
                vessel,
                capture_log_cache,
                "mun_capture",
                capture_band,
                "mun_capture",
                f"mun_capture ecc={eccentricity:6.3f} apo={apoapsis_altitude:8.0f}m "
                f"peri={periapsis_altitude:8.0f}m ttPe={vessel.orbit.time_to_periapsis:6.1f}s "
                f"stage={control.current_stage} throttle={control.throttle:.2f}",
            )
        if eccentricity < 1.0 and apoapsis <= target_apoapsis:
            control.throttle = 0.0
            return True
        if eccentricity < 1.0 and apoapsis_altitude <= target_apoapsis_altitude * 1.1:
            control.throttle = 0.25
        if eccentricity < 1.0 and apoapsis_altitude <= target_apoapsis_altitude * 1.02:
            control.throttle = 0.1
        time.sleep(0.1)
    control.throttle = 0.0
    return False


def fly_mun_mission(
    rocket_dict,
    parts_by_name,
    vessel,
    sc=None,
    target_apoapsis=80_000,
    target_periapsis=70_000,
    periapsis_cutoff=None,
    turn_start_altitude=250.0,
    turn_end_altitude=45_000.0,
    handoff_altitude=45_000.0,
    handoff_fuel_threshold=25.0,
    mun_orbit_altitude=20_000.0,
    mun_transfer_window_tolerance_deg=5.0,
    verbose=False,
):
    result = fly_standard_ascent(
        rocket_dict,
        parts_by_name,
        vessel,
        sc=sc,
        target_apoapsis=target_apoapsis,
        target_periapsis=target_periapsis,
        periapsis_cutoff=periapsis_cutoff,
        turn_start_altitude=turn_start_altitude,
        turn_end_altitude=turn_end_altitude,
        handoff_altitude=handoff_altitude,
        handoff_fuel_threshold=handoff_fuel_threshold,
        verbose=verbose,
    )

    stage_propellants = infer_stage_propellants(rocket_dict, parts_by_name)
    propellants = monitored_propellants(stage_propellants)
    stage_state = {
        "monitored_stage": current_fueled_stage(vessel, propellants),
        "last_stage_time": 0.0,
        "events": list(result["stage_events"]),
    }

    kerbin = vessel.orbit.body
    mun = next((body for body in kerbin.satellites if body.name == "Mun"), None)
    if mun is None:
        result["mission_phase"] = "mun_missing"
        result["stage_events"] = stage_state["events"]
        return result

    r1 = vector_norm(vessel.position(kerbin.non_rotating_reference_frame))
    r2 = mun.orbit.semi_major_axis
    transfer_a = 0.5 * (r1 + r2)
    transfer_time = math.pi * math.sqrt((transfer_a ** 3) / kerbin.gravitational_parameter)
    mun_mean_motion = math.sqrt(kerbin.gravitational_parameter / (r2 ** 3))
    required_phase = normalize_angle(math.pi - mun_mean_motion * transfer_time)

    window = wait_for_transfer_window(
        sc,
        vessel,
        mun,
        kerbin,
        required_phase,
        math.radians(mun_transfer_window_tolerance_deg),
        verbose=verbose,
    )
    if window is None:
        result["mission_phase"] = "mun_transfer_window_timeout"
        result["stage_events"] = stage_state["events"]
        return result
    stage_state["events"].append({
        "time": time.time(),
        "kind": "mun_transfer_window",
        **window,
    })
    transfer_start_snapshot = propulsion_snapshot(vessel, propellants, stage_state)
    result["transfer_start_snapshot"] = transfer_start_snapshot
    if verbose:
        verbose_log(vessel, "mun_transfer_setup", f"snapshot={transfer_start_snapshot}")
        verbose_log(
            vessel,
            "mun_transfer_vehicle",
            f"snapshot={vessel_composition_snapshot(vessel)}",
        )
    ignite_next_stage_if_needed(
        vessel,
        stage_state,
        verbose=verbose,
        label="mun_transfer_ignite",
    )
    transfer_start_snapshot = propulsion_snapshot(vessel, propellants, stage_state)
    result["transfer_start_snapshot"] = transfer_start_snapshot
    if verbose:
        verbose_log(vessel, "mun_transfer_setup_post_ignite", f"snapshot={transfer_start_snapshot}")

    transfer_apoapsis = r2 - kerbin.equatorial_radius
    transfer_result = burn_until_apoapsis(
        vessel,
        vessel.auto_pilot,
        stage_state,
        propellants,
        transfer_apoapsis,
        verbose=verbose,
        label="mun_transfer_burn",
    )
    result["mun_transfer_burn"] = transfer_result
    if not transfer_result["ok"]:
        result["mission_phase"] = f"mun_transfer_burn_{transfer_result['reason']}"
        result["stage_events"] = stage_state["events"]
        return result

    soi_ok = wait_for_body_change(sc, vessel, "Mun", verbose=verbose)
    if not soi_ok:
        result["mission_phase"] = "mun_soi_timeout"
        result["stage_events"] = stage_state["events"]
        return result
    stage_state["events"].append({
        "time": time.time(),
        "kind": "entered_mun_soi",
        "apoapsis": vessel.orbit.apoapsis_altitude,
        "periapsis": vessel.orbit.periapsis_altitude,
    })

    captured = capture_at_body(
        sc,
        vessel,
        vessel.auto_pilot,
        stage_state,
        propellants,
        "Mun",
        mun_orbit_altitude,
        verbose=verbose,
    )
    result["stage_events"] = stage_state["events"]
    result["mission_phase"] = "mun_orbit" if captured else "mun_capture_incomplete"
    result["final_body"] = vessel.orbit.body.name
    result["final_apoapsis"] = vessel.orbit.apoapsis_altitude
    result["final_periapsis"] = vessel.orbit.periapsis_altitude
    result["situation"] = str(vessel.situation)
    result["mun_transfer_required_phase_deg"] = math.degrees(required_phase)
    return result


def main():
    args = parse_args()
    parts_by_name = load_parts_by_name()
    generation_data = load_generation(args.generation_file)
    selected = choose_rocket(generation_data, args.rank)
    ship_name = args.ship_name or default_ship_name(generation_data, args.rank)
    run_dir = make_run_dir(ship_name)

    out_path, craft_meta = write_craft(selected["rocket"], parts_by_name, ship_name, args.save_name)
    print(f"wrote craft: {out_path}")
    print(f"craft meta: {craft_meta}")
    print(f"selected score: {selected['meta']['score']:.1f}")

    conn = connect()
    sc = conn.space_center
    print(f"launchable: {ship_name in sc.launchable_vessels('VAB')}")
    screenshot_path = capture_prelaunch_screenshot(run_dir)
    print(f"prelaunch screenshot: {screenshot_path}")

    vessel = launch_from_vab(sc, ship_name)
    print(f"launched active vessel: {vessel.name}")

    if args.mission == "mun_orbit":
        result = fly_mun_mission(
            selected["rocket"],
            parts_by_name,
            vessel,
            sc=sc,
            target_apoapsis=args.target_apoapsis,
            target_periapsis=args.target_periapsis,
            periapsis_cutoff=args.periapsis_cutoff,
            turn_start_altitude=args.turn_start_altitude,
            turn_end_altitude=args.turn_end_altitude,
            handoff_altitude=args.handoff_altitude,
            handoff_fuel_threshold=args.handoff_fuel_threshold,
            mun_orbit_altitude=args.mun_orbit_altitude,
            mun_transfer_window_tolerance_deg=args.mun_transfer_window_tolerance_deg,
            verbose=args.verbose,
        )
    else:
        result = fly_standard_ascent(
            selected["rocket"],
            parts_by_name,
            vessel,
            sc=sc,
            target_apoapsis=args.target_apoapsis,
            target_periapsis=args.target_periapsis,
            periapsis_cutoff=args.periapsis_cutoff,
            turn_start_altitude=args.turn_start_altitude,
            turn_end_altitude=args.turn_end_altitude,
            handoff_altitude=args.handoff_altitude,
            handoff_fuel_threshold=args.handoff_fuel_threshold,
            verbose=args.verbose,
        )
    print(f"result: {result}")

    record = {
        "timestamp": datetime.now().isoformat(),
        "generation_file": str(args.generation_file),
        "rank": args.rank,
        "ship_name": ship_name,
        "save_name": args.save_name,
        "craft_path": str(out_path),
        "prelaunch_screenshot": str(screenshot_path),
        "selected_meta": selected["meta"],
        "craft_meta": craft_meta,
        "runner_config": {
            "mission": args.mission,
            "target_apoapsis": args.target_apoapsis,
            "target_periapsis": args.target_periapsis,
            "periapsis_cutoff": args.periapsis_cutoff,
            "turn_start_altitude": args.turn_start_altitude,
            "turn_end_altitude": args.turn_end_altitude,
            "handoff_altitude": args.handoff_altitude,
            "handoff_fuel_threshold": args.handoff_fuel_threshold,
            "mun_orbit_altitude": args.mun_orbit_altitude,
            "mun_transfer_window_tolerance_deg": args.mun_transfer_window_tolerance_deg,
        },
        "rocket_dict": selected["rocket"],
        "flight_result": result,
    }
    record_path = write_run_record(run_dir, record)
    print(f"run record: {record_path}")


if __name__ == "__main__":
    main()
