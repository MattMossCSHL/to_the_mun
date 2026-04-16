#!/usr/bin/env python3
"""
Render idealized mission images from the saved-run rocket and runner logic.

Outputs:
- expected_trajectory.png: Kerbin ascent profile view
- expected_mun_mission_profile.png: schematic mission timeline/profile to the Mun
- expected_mun_orbital_arcs.png: literal-ish orbital-arcs view from Kerbin orbit to Mun capture

These are intentional diagrams based on the scripted runner phases, not full
physics integrations.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from src.config import load_parts_by_name
from src.filters import calculate_launch_twr, compute_burn_time, get_total_mass

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUN = REPO_ROOT / "data" / "runs" / "run_2026-04-02-172335" / "gen_010.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results" / "plots"

KERBIN_RADIUS_KM = 600.0
KERBIN_PARKING_APOAPSIS_KM = 80.0
KERBIN_PARKING_PERIAPSIS_KM = 70.0
MUN_ORBIT_RADIUS_FROM_KERBIN_KM = 12_000.0
MUN_RADIUS_KM = 200.0
MUN_CAPTURE_ALTITUDE_KM = 20.0
RESOURCE_LOOKUP = {
    "LiquidFuel": {"density": 0.005},
    "Oxidizer": {"density": 0.005},
    "ElectricCharge": {"density": 0.0},
}


def parse_args():
    parser = argparse.ArgumentParser(description="Plot the idealized runner trajectory.")
    parser.add_argument("--generation-file", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--rank", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mission", choices=["kerbin_orbit", "mun_orbit"], default="mun_orbit")
    parser.add_argument("--target-apoapsis", type=float, default=80_000.0)
    parser.add_argument("--target-periapsis", type=float, default=70_000.0)
    parser.add_argument("--turn-start-altitude", type=float, default=250.0)
    parser.add_argument("--turn-end-altitude", type=float, default=45_000.0)
    parser.add_argument("--handoff-altitude", type=float, default=45_000.0)
    parser.add_argument("--mun-orbit-altitude", type=float, default=20_000.0)
    return parser.parse_args()


def load_generation(path: Path) -> dict:
    return json.loads(path.read_text())


def choose_rocket(generation_data: dict, rank: int) -> dict:
    rockets = sorted(
        generation_data["rockets"],
        key=lambda rec: rec["meta"]["score"],
        reverse=True,
    )
    if rank < 1 or rank > len(rockets):
        raise ValueError(f"rank must be between 1 and {len(rockets)}")
    return rockets[rank - 1]


def stage_label(part_id: str, stage_num: int, rocket: dict, parts_by_name: dict) -> str:
    part = next(part for part in rocket["parts"] if part["id"] == part_id)
    title = parts_by_name[part["type"]].get("title", part["type"])
    role = "decoupler" if part_id.startswith("decoupler_") else "engine"
    return f"{part_id} | project stage {stage_num} | {role}\n{title}"


def explicit_stage_annotations(rocket: dict, parts_by_name: dict) -> list[dict]:
    return [
        {
            "part_id": part_id,
            "stage_num": stage_num,
            "label": stage_label(part_id, stage_num, rocket, parts_by_name),
        }
        for part_id, stage_num in sorted(
            rocket["stages"].items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def build_ascent_profile(
    target_apoapsis: float,
    target_periapsis: float,
    turn_start_altitude: float,
    turn_end_altitude: float,
    handoff_altitude: float,
):
    core_finish_start_apoapsis = target_apoapsis * 0.9
    ideal_handoff_altitude = max(handoff_altitude, turn_end_altitude + 23_000.0)
    handoff_apoapsis = max(100_000.0, core_finish_start_apoapsis + 28_000.0)
    final_orbit_altitude = 0.5 * (target_apoapsis + target_periapsis)

    x1 = np.linspace(0.0, 45.0, 140)
    y1 = 8.0 * (x1 / x1.max()) ** 1.25

    x2 = np.linspace(45.0, 200.0, 220)
    u2 = (x2 - x2.min()) / (x2.max() - x2.min())
    y2 = 8.0 + (turn_end_altitude / 1000.0 - 8.0) * (u2 ** 0.8)

    x3 = np.linspace(200.0, 300.0, 110)
    u3 = (x3 - x3.min()) / (x3.max() - x3.min())
    y3 = (turn_end_altitude / 1000.0) + (
        ideal_handoff_altitude / 1000.0 - turn_end_altitude / 1000.0
    ) * (u3 ** 0.9)

    x4 = np.linspace(300.0, 700.0, 260)
    u4 = (x4 - x4.min()) / (x4.max() - x4.min())
    y4 = (ideal_handoff_altitude / 1000.0) + (
        handoff_apoapsis / 1000.0 - ideal_handoff_altitude / 1000.0
    ) * np.sin(0.5 * np.pi * u4)

    x5 = np.linspace(700.0, 900.0, 180)
    u5 = (x5 - x5.min()) / (x5.max() - x5.min())
    y5 = (handoff_apoapsis / 1000.0) - (
        (handoff_apoapsis / 1000.0) - (final_orbit_altitude / 1000.0)
    ) * (u5 ** 1.3)

    return {
        "liftoff_ascent": (x1, y1),
        "gravity_turn": (x2, y2),
        "core_stage_finish": (x3, y3),
        "coast_to_apoapsis": (x4, y4),
        "orbital_insertion": (x5, y5),
        "markers": {
            "liftoff": (x1[0], y1[0]),
            "turn_start": (
                np.interp(turn_start_altitude / 1000.0, y1, x1),
                turn_start_altitude / 1000.0,
            ),
            "turn_end": (x2[-1], y2[-1]),
            "handoff": (x3[-1], y3[-1]),
            "apoapsis": (x4[-1], y4[-1]),
            "orbit_closed": (x5[-1], y5[-1]),
        },
    }


def annotate_stage_parts(ax, annotations: list[dict], stage_positions: dict, text_positions: dict):
    for ann in annotations:
        if ann["part_id"] not in stage_positions:
            continue
        ax.annotate(
            ann["label"],
            xy=stage_positions[ann["part_id"]],
            xytext=text_positions[ann["part_id"]],
            textcoords="data",
            fontsize=9,
            ha="left",
            va="center",
            arrowprops={"arrowstyle": "->", "lw": 1.1, "color": "#3a3a3a"},
            bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "#444444", "alpha": 0.96},
        )


def analyze_rocket_practicality(rocket: dict, parts_by_name: dict) -> dict:
    parts_list = [part["type"] for part in rocket["parts"]]
    wet_mass_t = get_total_mass(parts_list, parts_by_name, RESOURCE_LOOKUP)
    launch_twr = calculate_launch_twr(rocket, parts_list, parts_by_name, RESOURCE_LOOKUP)
    burn_times = compute_burn_time(rocket, parts_list, parts_by_name, RESOURCE_LOOKUP)

    id_to_type = {part["id"]: part["type"] for part in rocket["parts"]}
    stage_items = sorted(rocket["stages"].items(), key=lambda item: (-item[1], item[0]))
    highest_stage = max(rocket["stages"].values())
    upper_engine_id = next(part_id for part_id, stage in stage_items if stage == 0 and part_id.startswith("eng_"))
    booster_engine_id = next(part_id for part_id, stage in stage_items if stage == highest_stage and part_id.startswith("eng_"))
    decoupler_id = next((part_id for part_id, stage in stage_items if stage == highest_stage and part_id.startswith("decoupler_")), None)

    jettison_ids = {decoupler_id} if decoupler_id is not None else set()
    if decoupler_id is not None:
        include = False
        for part in rocket["parts"]:
            if part["id"] == decoupler_id:
                include = True
                continue
            if include:
                jettison_ids.add(part["id"])

    remaining_ids = [part["id"] for part in rocket["parts"] if part["id"] not in jettison_ids]

    def wet_mass_for_ids(part_ids):
        total = 0.0
        for part_id in part_ids:
            part_data = parts_by_name[id_to_type[part_id]]
            total += part_data["mass_t"]
            if part_data["resources"]:
                for resource_name, units in part_data["resources"].items():
                    total += units * RESOURCE_LOOKUP[resource_name]["density"]
        return total

    upper_wet_mass_t = wet_mass_for_ids(remaining_ids)
    upper_dry_mass_t = sum(parts_by_name[id_to_type[part_id]]["mass_t"] for part_id in remaining_ids)
    upper_engine = parts_by_name[id_to_type[upper_engine_id]]["engine"]
    thrust_n = upper_engine["max_thrust_kn"] * 1000.0
    upper_twr = thrust_n / (upper_wet_mass_t * 1000.0 * 9.80665)
    upper_accel_wet = thrust_n / (upper_wet_mass_t * 1000.0)
    upper_accel_dry = thrust_n / (upper_dry_mass_t * 1000.0)
    avg_accel = 0.5 * (upper_accel_wet + upper_accel_dry)

    return {
        "wet_mass_t": wet_mass_t,
        "launch_twr": launch_twr,
        "burn_times": burn_times,
        "booster_engine_id": booster_engine_id,
        "upper_engine_id": upper_engine_id,
        "upper_stage_wet_mass_t": upper_wet_mass_t,
        "upper_stage_dry_mass_t": upper_dry_mass_t,
        "upper_stage_twr": upper_twr,
        "upper_stage_accel_wet": upper_accel_wet,
        "upper_stage_accel_dry": upper_accel_dry,
        "approx_300_ms_burn_s": 300.0 / avg_accel,
        "approx_900_ms_burn_s": 900.0 / avg_accel,
    }


def render_ascent_plot(output: Path, generation_data: dict, rank: int, rocket: dict, meta: dict, annotations: list[dict], args):
    profile = build_ascent_profile(
        args.target_apoapsis,
        args.target_periapsis,
        args.turn_start_altitude,
        args.turn_end_altitude,
        args.handoff_altitude,
    )

    plt.style.use("default")
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.patch.set_facecolor("#eef3f6")
    ax.set_facecolor("#fbfcfd")

    phase_colors = {
        "liftoff_ascent": "#0b6e4f",
        "gravity_turn": "#2a9d8f",
        "core_stage_finish": "#e9c46a",
        "coast_to_apoapsis": "#577590",
        "orbital_insertion": "#bc4749",
    }
    for phase_name, color in phase_colors.items():
        x, y = profile[phase_name]
        ax.plot(x, y, linewidth=4.0, color=color, solid_capstyle="round", label=phase_name.replace("_", " "))

    planet_fill_x = np.linspace(0.0, 920.0, 400)
    ax.fill_between(planet_fill_x, np.full_like(planet_fill_x, -1.2), 0.0, color="#d8e2dc", alpha=0.65)

    ax.axhline(70.0, color="#9e2a2b", linestyle="--", linewidth=1.2, alpha=0.8)
    ax.axhline(80.0, color="#ba181b", linestyle=":", linewidth=1.2, alpha=0.8)
    ax.text(905.0, 70.8, "target periapsis 70 km", fontsize=9, ha="right", color="#9e2a2b")
    ax.text(905.0, 80.8, "target apoapsis 80 km", fontsize=9, ha="right", color="#ba181b")

    markers = profile["markers"]
    for x, y in markers.values():
        ax.scatter([x], [y], s=38, color="#1d3557", zorder=5)

    annotate_stage_parts(
        ax,
        annotations,
        stage_positions={
            "eng_1": markers["liftoff"],
            "decoupler_0": markers["handoff"],
            "eng_0": markers["apoapsis"],
        },
        text_positions={
            "eng_1": (90.0, 18.0),
            "decoupler_0": (360.0, 83.0),
            "eng_0": (760.0, 108.0),
        },
    )

    phase_notes = [
        ("Runner ignites bottom stage", markers["liftoff"], (15.0, 5.0)),
        ("Gravity turn complete\npitch target reaches horizontal", markers["turn_end"], (120.0, 50.0)),
        ("Upper-stage handoff window", markers["handoff"], (430.0, 63.0)),
        ("Coast to apoapsis", markers["apoapsis"], (590.0, 118.0)),
        ("Circularization burn closes orbit", markers["orbit_closed"], (760.0, 78.0)),
    ]
    for text, xy, xytext in phase_notes:
        ax.annotate(
            text,
            xy=xy,
            xytext=xytext,
            fontsize=9,
            ha="left",
            va="center",
            arrowprops={"arrowstyle": "-", "lw": 0.9, "color": "#666666"},
            color="#202020",
        )

    summary = [
        f"Generation {generation_data['generation']} rank {rank} score: {meta['score']:.0f} m/s analytic delta-v",
        f"Stage dv breakdown: {meta.get('stage_dv', {})}",
        "Interpretation: ascent target implied by fly_standard_ascent() under ideal conditions.",
    ]
    ax.text(
        18.0,
        124.0,
        "\n".join(summary),
        fontsize=10,
        ha="left",
        va="top",
        bbox={"boxstyle": "round,pad=0.5", "fc": "white", "ec": "#cad2c5", "alpha": 0.97},
    )

    ax.set_xlim(0.0, 920.0)
    ax.set_ylim(-2.0, 128.0)
    ax.set_xlabel("Downrange distance under ideal ascent guidance (km)")
    ax.set_ylabel("Altitude (km)")
    ax.set_title("Expected Rocket Trajectory Under Ideal Runner Conditions")
    ax.grid(True, linestyle=":", linewidth=0.8, alpha=0.45)
    ax.legend(loc="lower right", frameon=True)
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def render_mission_profile_plot(output: Path, generation_data: dict, rank: int, meta: dict, annotations: list[dict], args, practical: dict):
    fig, ax = plt.subplots(figsize=(15, 8))
    fig.patch.set_facecolor("#f1f5f9")
    ax.set_facecolor("#fcfdfd")

    x = np.array([0.0, 1.2, 2.6, 4.1, 5.5, 6.6, 7.8, 9.0])
    y = np.array([0.0, 68.0, 75.0, 75.0, 11_400.0, 11_900.0, 20.0, 20.0])
    labels = [
        "Liftoff",
        "Upper-stage handoff",
        "Kerbin parking orbit",
        "Wait for Mun window",
        "Mun transfer burn",
        "Enter Mun SOI",
        "Retrograde capture",
        "Final Mun orbit",
    ]
    colors = ["#0b6e4f", "#e9c46a", "#bc4749", "#577590", "#6a4c93", "#355070", "#d00000", "#386641"]

    for i in range(len(x) - 1):
        ax.plot(x[i:i + 2], y[i:i + 2], color=colors[i], linewidth=4.5, solid_capstyle="round")
    ax.scatter(x, y, c=colors, s=70, zorder=5)

    practical_x = np.array([0.0, 1.2, 2.6, 4.25, 5.1])
    practical_y = np.array([0.0, 68.0, 75.0, 75.0, 120.0])
    ax.plot(
        practical_x,
        practical_y,
        color="#222222",
        linewidth=2.8,
        linestyle="--",
        label="practical with current rocket",
    )
    ax.scatter(practical_x, practical_y, color="#222222", s=42, zorder=6)

    label_offsets = {
        "Liftoff": (0.0, 18.0),
        "Upper-stage handoff": (0.0, 18.0),
        "Kerbin parking orbit": (0.0, 18.0),
        "Wait for Mun window": (0.0, 18.0),
        "Mun transfer burn": (0.0, 260.0),
        "Enter Mun SOI": (0.0, 180.0),
        "Retrograde capture": (-0.08, 20.0),
        "Final Mun orbit": (0.10, 18.0),
    }
    for xi, yi, label in zip(x, y, labels):
        dx, dy = label_offsets[label]
        ax.text(xi + dx, yi + dy, label, fontsize=10, ha="center", va="bottom")

    ax.axhline(75.0, color="#ba181b", linestyle="--", linewidth=1.0, alpha=0.75)
    ax.text(8.15, 86.0, "Kerbin parking orbit ~75 km avg", fontsize=9, ha="center", va="bottom", color="#ba181b")

    annotate_stage_parts(
        ax,
        annotations,
        stage_positions={
            "eng_1": (0.0, 0.0),
            "decoupler_0": (1.2, 68.0),
            "eng_0": (4.1, 75.0),
        },
        text_positions={
            "eng_1": (0.4, 900.0),
            "decoupler_0": (1.9, 1800.0),
            "eng_0": (4.55, 3350.0),
        },
    )

    mission_box = [
        "Optimistic: runner-assumed low-thrust mission to Mun",
        "Practical: current rocket likely tops out at Kerbin orbit or a weak finite-burn transfer attempt",
        f"Generation {generation_data['generation']} rank {rank} score: {meta['score']:.0f} m/s analytic delta-v",
        f"Target Mun capture altitude: {args.mun_orbit_altitude/1000.0:.0f} km",
    ]
    ax.text(
        0.18,
        11_700.0,
        "\n".join(mission_box),
        fontsize=10,
        ha="left",
        va="top",
        bbox={"boxstyle": "round,pad=0.45", "fc": "white", "ec": "#cbd5e1", "alpha": 0.98},
    )

    metrics_box = [
        f"Current rocket reality check",
        f"launch TWR: {practical['launch_twr']:.2f}",
        f"upper-stage orbital TWR: {practical['upper_stage_twr']:.3f}",
        f"upper-stage burn time: {practical['burn_times'].get(0, 0):.0f}s",
        f"~300 m/s burn: {practical['approx_300_ms_burn_s']:.0f}s",
        f"~900 m/s burn: {practical['approx_900_ms_burn_s']:.0f}s",
    ]
    ax.text(
        6.05,
        3600.0,
        "\n".join(metrics_box),
        fontsize=9,
        ha="left",
        va="top",
        bbox={"boxstyle": "round,pad=0.45", "fc": "#fff8e7", "ec": "#d4a373", "alpha": 0.98},
    )
    ax.annotate(
        "Practical reading:\nvery low-thrust Ant stage makes clean transfer/capture unlikely",
        xy=(5.1, 120.0),
        xytext=(5.6, 950.0),
        fontsize=9,
        ha="left",
        va="center",
        arrowprops={"arrowstyle": "->", "lw": 1.0, "color": "#222222"},
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "#444444", "alpha": 0.95},
    )

    ax.set_xlim(-0.2, 9.2)
    ax.set_ylim(-150.0, 12_500.0)
    ax.set_xticks([])
    ax.set_ylabel("Altitude above local body (km)")
    ax.set_title("Mun Mission Profile: Optimistic Runner Path vs Practical Current Rocket")
    ax.grid(True, axis="y", linestyle=":", linewidth=0.8, alpha=0.4)
    ax.legend(loc="upper right", frameon=True)
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def circular_arc(radius: float, start_deg: float, end_deg: float, samples: int = 240):
    theta = np.linspace(math.radians(start_deg), math.radians(end_deg), samples)
    return radius * np.cos(theta), radius * np.sin(theta)


def ellipse_arc(a: float, e: float, start_deg: float, end_deg: float, samples: int = 400):
    theta = np.linspace(math.radians(start_deg), math.radians(end_deg), samples)
    r = a * (1.0 - e ** 2) / (1.0 + e * np.cos(theta))
    return r * np.cos(theta), r * np.sin(theta)


def quadratic_bezier(p0, p1, p2, samples: int = 320):
    t = np.linspace(0.0, 1.0, samples)
    x = ((1.0 - t) ** 2) * p0[0] + 2.0 * (1.0 - t) * t * p1[0] + (t ** 2) * p2[0]
    y = ((1.0 - t) ** 2) * p0[1] + 2.0 * (1.0 - t) * t * p1[1] + (t ** 2) * p2[1]
    return x, y


def render_orbital_arcs_plot(output: Path, generation_data: dict, rank: int, meta: dict, annotations: list[dict], args, practical: dict):
    fig, ax = plt.subplots(figsize=(10.5, 10.5))
    fig.patch.set_facecolor("#eef2ff")
    ax.set_facecolor("#f8fafc")

    kerbin = plt.Circle((0.0, 0.0), KERBIN_RADIUS_KM, color="#3a86ff", alpha=0.95)
    ax.add_patch(kerbin)

    parking_r_avg = KERBIN_RADIUS_KM + 0.5 * (
        KERBIN_PARKING_APOAPSIS_KM + KERBIN_PARKING_PERIAPSIS_KM
    )
    parking_x, parking_y = circular_arc(parking_r_avg, -165.0, 20.0)
    ax.plot(parking_x, parking_y, color="#d1495b", linewidth=2.8, label="Kerbin parking orbit")

    mun_center = np.array([MUN_ORBIT_RADIUS_FROM_KERBIN_KM, 0.0])
    mun = plt.Circle(tuple(mun_center), MUN_RADIUS_KM, color="#9c6644", alpha=0.96)
    ax.add_patch(mun)

    transfer_start = (parking_x[-1], parking_y[-1])
    transfer_point = (mun_center[0] - 260.0, 150.0)
    transfer_control = (6500.0, 3200.0)
    transfer_x, transfer_y = quadratic_bezier(transfer_start, transfer_control, transfer_point)
    ax.plot(transfer_x, transfer_y, color="#6a4c93", linewidth=3.3, label="optimistic Mun transfer arc")

    practical_end = (2500.0, 700.0)
    practical_control = (1300.0, 950.0)
    practical_transfer_x, practical_transfer_y = quadratic_bezier(transfer_start, practical_control, practical_end, samples=180)
    ax.plot(
        practical_transfer_x,
        practical_transfer_y,
        color="#222222",
        linewidth=2.6,
        linestyle="--",
        label="practical current-rocket path",
    )

    mun_capture_r = MUN_RADIUS_KM + args.mun_orbit_altitude / 1000.0
    capture_theta = np.linspace(math.radians(120.0), math.radians(345.0), 220)
    capture_x = mun_center[0] + mun_capture_r * np.cos(capture_theta)
    capture_y = mun_center[1] + mun_capture_r * np.sin(capture_theta)
    ax.plot(capture_x, capture_y, color="#386641", linewidth=2.8, label="Final Mun orbit")

    capture_start = (capture_x[0], capture_y[0])
    ax.plot(
        [transfer_point[0], capture_start[0]],
        [transfer_point[1], capture_start[1]],
        color="#d00000",
        linewidth=2.2,
        linestyle="--",
        label="Capture burn region",
    )

    ax.scatter([parking_x[0], parking_x[-1], transfer_point[0], capture_start[0]], [parking_y[0], parking_y[-1], transfer_point[1], capture_start[1]], color="#1d3557", s=35, zorder=6)

    annotate_stage_parts(
        ax,
        annotations,
        stage_positions={
            "eng_1": (KERBIN_RADIUS_KM, 0.0),
            "decoupler_0": (parking_x[-1], parking_y[-1]),
            "eng_0": transfer_point,
        },
        text_positions={
            "eng_1": (-2400.0, -700.0),
            "decoupler_0": (-1200.0, 1600.0),
            "eng_0": (5600.0, 3050.0),
        },
    )

    notes = [
        ("Parking orbit after ascent", (parking_x[-1], parking_y[-1]), (-1700.0, 900.0)),
        ("Mun transfer burn near prograde", (parking_x[-1], parking_y[-1]), (1400.0, 900.0)),
        ("Upper stage carries transfer", transfer_point, (6900.0, 2300.0)),
        ("Enter Mun SOI", transfer_point, (7800.0, 1200.0)),
        ("Retrograde capture to ~20 km orbit", capture_start, (10_200.0, -1100.0)),
        ("Practical with current rocket:\nlikely remains near Kerbin after a long finite burn", practical_end, (2800.0, 1500.0)),
    ]
    for text, xy, xytext in notes:
        ax.annotate(
            text,
            xy=xy,
            xytext=xytext,
            fontsize=9,
            ha="left",
            va="center",
            arrowprops={"arrowstyle": "-", "lw": 0.9, "color": "#666"},
        )

    summary = [
        f"Generation {generation_data['generation']} rank {rank} score: {meta['score']:.0f} m/s analytic delta-v",
        "Purple path: optimistic low-thrust runner interpretation.",
        "Black dashed path: practical current-rocket reading from stage thrust and burn time.",
    ]
    ax.text(
        -2550.0,
        11_350.0,
        "\n".join(summary),
        fontsize=10,
        ha="left",
        va="top",
        bbox={"boxstyle": "round,pad=0.45", "fc": "white", "ec": "#cbd5e1", "alpha": 0.98},
    )
    ax.text(
        6800.0,
        5400.0,
        (
            "Current rocket reality check\n"
            f"upper-stage wet mass: {practical['upper_stage_wet_mass_t']:.2f} t\n"
            f"upper-stage orbital TWR: {practical['upper_stage_twr']:.3f}\n"
            f"~300 m/s burn: {practical['approx_300_ms_burn_s']:.0f}s\n"
            f"~900 m/s burn: {practical['approx_900_ms_burn_s']:.0f}s"
        ),
        fontsize=9,
        ha="left",
        va="top",
        bbox={"boxstyle": "round,pad=0.45", "fc": "#fff8e7", "ec": "#d4a373", "alpha": 0.98},
    )

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-2600.0, 13_400.0)
    ax.set_ylim(-4200.0, 12_000.0)
    ax.set_xlabel("Kerbin-centered X (km)")
    ax.set_ylabel("Kerbin-centered Y (km)")
    ax.set_title("Kerbin-to-Mun Arcs: Optimistic Runner Path vs Practical Current Rocket")
    ax.grid(True, linestyle=":", linewidth=0.8, alpha=0.35)
    ax.legend(loc="lower left", frameon=True)
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def main():
    args = parse_args()
    generation_data = load_generation(args.generation_file)
    selected = choose_rocket(generation_data, args.rank)
    rocket = selected["rocket"]
    meta = selected["meta"]
    parts_by_name = load_parts_by_name()
    annotations = explicit_stage_annotations(rocket, parts_by_name)
    practical = analyze_rocket_practicality(rocket, parts_by_name)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ascent_output = args.output_dir / "expected_trajectory.png"
    render_ascent_plot(ascent_output, generation_data, args.rank, rocket, meta, annotations, args)

    outputs = [ascent_output]
    if args.mission == "mun_orbit":
        mission_profile_output = args.output_dir / "expected_mun_mission_profile.png"
        orbital_arcs_output = args.output_dir / "expected_mun_orbital_arcs.png"
        render_mission_profile_plot(mission_profile_output, generation_data, args.rank, meta, annotations, args, practical)
        render_orbital_arcs_plot(orbital_arcs_output, generation_data, args.rank, meta, annotations, args, practical)
        outputs.extend([mission_profile_output, orbital_arcs_output])

    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
