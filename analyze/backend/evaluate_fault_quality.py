import argparse
import csv
import json
import os
import sys
from pathlib import Path
from statistics import mean
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CURRENT_DIR.parent
DEFAULT_DOWNLOADS = Path.home() / "Downloads"
DEFAULT_WEIGHTS = PROJECT_DIR / "models" / "best.pt"

sys.path.insert(0, str(CURRENT_DIR))

from dotenv import load_dotenv
from fault_analyzer import (
    apply_fault_modifiers,
    detect_events,
    evaluate_car_to_car_fault,
    get_compatible_event_types,
    get_supabase,
    match_accident_type,
)
from yolo_inference import analyze_video_with_yolo


class NoWriteTable:
    def insert(self, payload):
        return self

    def execute(self):
        class Response:
            data = []

        return Response()


class NoWriteDB:
    def table(self, name):
        return NoWriteTable()


def load_label(label_path: Path) -> Dict:
    with label_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return payload["video"]


def collect_pairs(root: Path) -> Dict[str, Tuple[Path, Path]]:
    labels = {}
    videos = {}
    for path in root.rglob("*"):
        if path.suffix.lower() == ".json" and path.name.startswith("bb_"):
            labels[path.stem] = path
        elif path.suffix.lower() in (".mp4", ".avi", ".mov") and path.name.startswith("bb_"):
            videos[path.stem] = path

    return {
        name: (labels[name], videos[name])
        for name in sorted(labels.keys() & videos.keys())
    }


def collect_category_pairs(root: Path, source_folder_name: str) -> Dict[str, Tuple[Path, Path]]:
    label_folder_name = source_folder_name
    if source_folder_name.startswith("VS_"):
        label_folder_name = "VL_" + source_folder_name[3:]
    elif source_folder_name.startswith("TS_"):
        label_folder_name = "TL_" + source_folder_name[3:]

    source_dirs = [
        path for path in root.rglob(source_folder_name)
        if path.is_dir() and "원천데이터" in str(path)
    ]
    label_dirs = [
        path for path in root.rglob(label_folder_name)
        if path.is_dir() and ("라벨링데이터" in str(path) or "라벨데이터" in str(path))
    ]

    labels = {}
    videos = {}
    for label_dir in label_dirs:
        for path in label_dir.rglob("*.json"):
            if path.name.startswith("bb_"):
                labels[path.stem] = path

    for source_dir in source_dirs:
        for path in source_dir.rglob("*"):
            if path.suffix.lower() in (".mp4", ".avi", ".mov") and path.name.startswith("bb_"):
                videos[path.stem] = path

    return {
        name: (labels[name], videos[name])
        for name in sorted(labels.keys() & videos.keys())
    }


def select_balanced_pairs(
    category_pairs: Dict[str, Tuple[Path, Path]],
    category_limit: int,
) -> List[Tuple[str, Tuple[Path, Path]]]:
    """Select deterministic samples while spreading common fault ratios."""
    ratio_groups = defaultdict(list)
    for name, paths in sorted(category_pairs.items()):
        try:
            label = load_label(paths[0])
            ratio = (
                label.get("accident_negligence_rateA"),
                label.get("accident_negligence_rateB"),
            )
        except Exception:
            ratio = (None, None)
        ratio_groups[ratio].append((name, paths))

    ordered_groups = sorted(
        ratio_groups.values(),
        key=lambda group: (-len(group), group[0][0]),
    )
    selected = []
    while ordered_groups and len(selected) < category_limit:
        remaining_groups = []
        for group in ordered_groups:
            if group and len(selected) < category_limit:
                selected.append(group.pop(0))
            if group:
                remaining_groups.append(group)
        ordered_groups = remaining_groups
    return selected


def select_category_pairs(root: Path, folder_names: List[str], category_limit: int) -> Dict[str, Tuple[Path, Path]]:
    selected = {}
    for folder_name in folder_names:
        category_pairs = collect_category_pairs(root, folder_name)
        for name, paths in select_balanced_pairs(category_pairs, category_limit):
            selected[f"{folder_name}:{name}"] = paths
    return selected


def summarize_by_category(rows: List[Dict]) -> Dict[str, Dict]:
    grouped = defaultdict(list)
    for row in rows:
        if row.get("mean_abs_error") == "":
            continue
        grouped[row.get("category_folder", "미분류")].append(row)
    return {
        category: summarize(category_rows)
        for category, category_rows in sorted(grouped.items())
    }


def predict_fault(video_path: Path, weights_path: Path) -> Dict:
    yolo_result = analyze_video_with_yolo(
        str(video_path),
        {"통합": str(weights_path)},
        video_id=f"EVAL_{video_path.stem[:20]}",
    )
    records = yolo_result["records"]
    fps = yolo_result.get("fps", 5.0)
    events, violation_map = detect_events(NoWriteDB(), -1, records, fps=fps)

    supabase = get_supabase()
    accident_type = match_accident_type(supabase, events, records)
    accident_type_id = accident_type["accident_type_id"] if accident_type else None
    base_a = accident_type["base_fault_a"] if accident_type else 50
    base_b = accident_type["base_fault_b"] if accident_type else 50

    if accident_type_id:
        fault_a, fault_b, modifier_desc = apply_fault_modifiers(
            supabase, accident_type_id, events, base_a, base_b
        )
    else:
        fault_a, fault_b, modifier_desc = base_a, base_b, []

    fault_a, fault_b, modifier_desc = evaluate_car_to_car_fault(
        event_types=events,
        records=records,
        violation_map=violation_map,
        base_a=fault_a,
        base_b=fault_b,
        modifier_desc=modifier_desc,
        accident_type=accident_type,
    )

    return {
        "predicted_a": int(fault_a),
        "predicted_b": int(fault_b),
        "events": get_compatible_event_types(events),
        "internal_events": events,
        "accident_type": accident_type["accident_name"] if accident_type else "불명확",
        "modifiers": modifier_desc,
    }


def evaluate_pair(name: str, label_path: Path, video_path: Path, weights_path: Path) -> Dict:
    label = load_label(label_path)
    expected_a = int(label.get("accident_negligence_rateA", 50))
    expected_b = int(label.get("accident_negligence_rateB", 50))
    prediction = predict_fault(video_path, weights_path)
    err_a = abs(prediction["predicted_a"] - expected_a)
    err_b = abs(prediction["predicted_b"] - expected_b)
    swapped_err_a = abs(prediction["predicted_b"] - expected_a)
    swapped_err_b = abs(prediction["predicted_a"] - expected_b)
    direct_mae = (err_a + err_b) / 2
    swapped_mae = (swapped_err_a + swapped_err_b) / 2
    best_orientation = "direct" if direct_mae <= swapped_mae else "swapped"

    return {
        "video_name": name,
        "expected_a": expected_a,
        "expected_b": expected_b,
        "predicted_a": prediction["predicted_a"],
        "predicted_b": prediction["predicted_b"],
        "err_a": err_a,
        "err_b": err_b,
        "mean_abs_error": round(direct_mae, 2),
        "swapped_mean_abs_error": round(swapped_mae, 2),
        "best_orientation": best_orientation,
        "orientation_mismatch": best_orientation == "swapped",
        "within_10": err_a <= 10 and err_b <= 10,
        "exact": err_a == 0 and err_b == 0,
        "within_10_allow_swap": min(direct_mae, swapped_mae) <= 10,
        "exact_allow_swap": min(direct_mae, swapped_mae) == 0,
        "events": ",".join(prediction["events"]),
        "internal_events": ",".join(prediction["internal_events"]),
        "accident_type": prediction["accident_type"],
        "label_type": label.get("traffic_accident_type") or label.get("accident_type"),
        "vehicle_a_progress_info": label.get("vehicle_a_progress_info"),
        "vehicle_b_progress_info": label.get("vehicle_b_progress_info"),
        "label_path": str(label_path),
        "video_path": str(video_path),
    }


def summarize(rows: List[Dict]) -> Dict:
    if not rows:
        return {
            "count": 0,
            "exact_accuracy": 0,
            "within_10_accuracy": 0,
            "mean_abs_error": None,
        }
    return {
        "count": len(rows),
        "exact_accuracy": round(sum(row["exact"] for row in rows) / len(rows), 4),
        "within_10_accuracy": round(sum(row["within_10"] for row in rows) / len(rows), 4),
        "mean_abs_error": round(mean(row["mean_abs_error"] for row in rows), 2),
        "mean_abs_error_allow_swap": round(
            mean(min(row["mean_abs_error"], row["swapped_mean_abs_error"]) for row in rows),
            2,
        ),
        "within_10_accuracy_allow_swap": round(
            sum(row["within_10_allow_swap"] for row in rows) / len(rows),
            4,
        ),
        "orientation_mismatch_rate": round(
            sum(row["orientation_mismatch"] for row in rows) / len(rows),
            4,
        ),
    }


def write_csv(rows: List[Dict], output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "category_folder",
        "video_name",
        "expected_a",
        "expected_b",
        "predicted_a",
        "predicted_b",
        "err_a",
        "err_b",
        "mean_abs_error",
        "swapped_mean_abs_error",
        "best_orientation",
        "orientation_mismatch",
        "within_10",
        "exact",
        "within_10_allow_swap",
        "exact_allow_swap",
        "events",
        "internal_events",
        "accident_type",
        "label_type",
        "vehicle_a_progress_info",
        "vehicle_b_progress_info",
        "label_path",
        "video_path",
    ]
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Evaluate fault-ratio quality against labeled videos.")
    parser.add_argument("--root", default=str(DEFAULT_DOWNLOADS), help="Dataset root to search.")
    parser.add_argument("--weights", default=str(DEFAULT_WEIGHTS), help="YOLO weights path.")
    parser.add_argument("--names", nargs="*", help="Specific video names without extension.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of pairs to evaluate.")
    parser.add_argument(
        "--category-folders",
        nargs="*",
        help="Source folder names to sample from, such as TS_차대차_영상_회전교차로.",
    )
    parser.add_argument(
        "--category-limit",
        type=int,
        default=10,
        help="Maximum number of pairs to evaluate from each category folder.",
    )
    parser.add_argument("--output", default=str(PROJECT_DIR / "fault_quality_report.csv"))
    args = parser.parse_args()

    load_dotenv(CURRENT_DIR / ".env")
    root = Path(args.root)
    if args.category_folders:
        pairs = select_category_pairs(root, args.category_folders, args.category_limit)
    else:
        pairs = collect_pairs(root)

    if args.names:
        selected_names = [
            key
            for key in pairs
            if key in args.names or key.split(":", 1)[-1] in args.names
        ]
    elif args.category_folders:
        selected_names = list(pairs)
    else:
        selected_names = list(pairs)[: args.limit]

    if args.limit and not args.names and not args.category_folders:
        selected_names = selected_names[: args.limit]

    rows = []
    for index, name in enumerate(selected_names, start=1):
        label_path, video_path = pairs[name]
        display_name = name.split(":", 1)[-1]
        print(f"[{index}/{len(selected_names)}] {display_name}")
        try:
            row = evaluate_pair(display_name, label_path, video_path, Path(args.weights))
            if ":" in name:
                row["category_folder"] = name.split(":", 1)[0]
            rows.append(row)
        except Exception as exc:
            rows.append(
                {
                    "video_name": display_name,
                    "category_folder": name.split(":", 1)[0] if ":" in name else "",
                    "expected_a": "",
                    "expected_b": "",
                    "predicted_a": "",
                    "predicted_b": "",
                    "err_a": "",
                    "err_b": "",
                    "mean_abs_error": "",
                    "swapped_mean_abs_error": "",
                    "best_orientation": "",
                    "orientation_mismatch": "",
                    "within_10": False,
                    "exact": False,
                    "within_10_allow_swap": False,
                    "exact_allow_swap": False,
                    "events": "",
                    "internal_events": "",
                    "accident_type": f"ERROR: {exc}",
                    "label_type": "",
                    "vehicle_a_progress_info": "",
                    "vehicle_b_progress_info": "",
                    "label_path": str(label_path),
                    "video_path": str(video_path),
                }
            )
            print(f"[ERROR] {name}: {exc}")

    write_csv(rows, Path(args.output))
    valid_rows = [row for row in rows if row.get("mean_abs_error") != ""]
    report = {
        "overall": summarize(valid_rows),
        "categories": summarize_by_category(valid_rows),
    }
    summary_path = Path(args.output).with_name(
        Path(args.output).stem + "_summary.json"
    )
    summary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[SAVE] {args.output}")
    print(f"[SAVE] {summary_path}")


if __name__ == "__main__":
    main()
