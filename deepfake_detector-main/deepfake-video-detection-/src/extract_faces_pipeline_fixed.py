import os
from pathlib import Path
import cv2
import pandas as pd
from insightface.app import FaceAnalysis

# =========================================================
# CONFIG
# =========================================================
BASE_VIDEO_DIR = Path("data/raw/ffpp")
CSV_DIR = Path("data/metadata")
OUTPUT_DIR = Path("data/processed/faces")

FRAME_STEP = 30
MAX_FRAMES = 16
IMG_SIZE = 160
DET_SIZE = 320
MAX_SIDE = 640
DET_SCORE_THRESHOLD = 0.70

# Put None for full extraction
TRAIN_LIMIT = None
VAL_LIMIT = None
TEST_LIMIT = None


# =========================================================
# INIT INSIGHTFACE
# =========================================================
def init_face_app() -> FaceAnalysis:
    app = FaceAnalysis(
        name="buffalo_l",
        allowed_modules=["detection"],
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(DET_SIZE, DET_SIZE))
    return app


# =========================================================
# HELPERS
# =========================================================
def get_limit(split_name: str):
    return {
        "train": TRAIN_LIMIT,
        "val": VAL_LIMIT,
        "test": TEST_LIMIT,
    }.get(split_name)


def ensure_output_dirs() -> None:
    for split in ["train", "val", "test"]:
        for label in ["real", "fake"]:
            (OUTPUT_DIR / split / label).mkdir(parents=True, exist_ok=True)


def find_column(df: pd.DataFrame, candidates: list[str]) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(f"Missing expected columns. Available: {df.columns.tolist()}")


def parse_label(raw_label) -> str:
    raw = str(raw_label).strip().upper()
    if raw in {"REAL", "0"}:
        return "real"
    if raw in {"FAKE", "1"}:
        return "fake"
    raise ValueError(f"Unknown label: {raw_label}")


def scale_for_detection(frame):
    h, w = frame.shape[:2]
    max_dim = max(h, w)
    if max_dim > MAX_SIDE:
        scale = MAX_SIDE / max_dim
        resized = cv2.resize(frame, (int(w * scale), int(h * scale)))
        return resized, scale
    return frame, 1.0


def safe_crop(frame, x1, y1, x2, y2):
    h, w = frame.shape[:2]
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2]
    if crop is None or crop.size == 0:
        return None
    return crop


def extract_face_crops(video_path: Path, app: FaceAnalysis):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"❌ Cannot open video: {video_path}")
        return []

    crops = []
    frame_id = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_id % FRAME_STEP == 0:
            det_frame, scale = scale_for_detection(frame)
            try:
                faces = app.get(det_frame)
            except Exception as exc:
                print(f"⚠️ Detection error for {video_path.name}: {exc}")
                break

            valid_faces = [
                f for f in faces
                if getattr(f, "det_score", 1.0) >= DET_SCORE_THRESHOLD
            ]

            if valid_faces:
                face = max(
                    valid_faces,
                    key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
                )
                x1, y1, x2, y2 = face.bbox.astype(int)
                x1, y1, x2, y2 = (
                    int(x1 / scale),
                    int(y1 / scale),
                    int(x2 / scale),
                    int(y2 / scale),
                )
                crop = safe_crop(frame, x1, y1, x2, y2)
                if crop is not None:
                    crop = cv2.resize(crop, (IMG_SIZE, IMG_SIZE))
                    crops.append(crop)

            if len(crops) >= MAX_FRAMES:
                break

        frame_id += 1

    cap.release()
    return crops


# =========================================================
# PROCESSING
# =========================================================
def process_split(split_name: str, app: FaceAnalysis) -> None:
    csv_path = CSV_DIR / f"{split_name}.csv"
    if not csv_path.exists():
        print(f"❌ CSV not found: {csv_path}")
        return

    df = pd.read_csv(csv_path)
    video_col = find_column(df, ["video_path", "File Path", "file_path", "path"])
    label_col = find_column(df, ["label", "Label", "target"])

    limit = get_limit(split_name)
    if limit is not None:
        df = df.head(limit).copy()

    print(f"\n📂 Processing {split_name.upper()} : {len(df)} videos")

    for _, row in df.iterrows():
        rel_path = str(row[video_col]).strip()
        try:
            label = parse_label(row[label_col])
        except ValueError as exc:
            print(f"⚠️ {exc} — skipped")
            continue

        video_path = BASE_VIDEO_DIR / rel_path
        if not video_path.exists():
            print(f"❌ Missing video: {video_path}")
            continue

        video_name = Path(rel_path).stem
        save_dir = OUTPUT_DIR / split_name / label
        save_dir.mkdir(parents=True, exist_ok=True)

        existing = list(save_dir.glob(f"{video_name}_*.jpg"))
        if len(existing) >= MAX_FRAMES:
            print(f"⏭️ Already extracted: {video_name}")
            continue

        crops = extract_face_crops(video_path, app)
        saved = 0
        for i, crop in enumerate(crops[:MAX_FRAMES]):
            out_path = save_dir / f"{video_name}_{i}.jpg"
            ok = cv2.imwrite(str(out_path), crop)
            if ok:
                saved += 1

        print(f"✅ [{split_name}] {video_name} -> {saved} faces")

    print(f"✅ {split_name} done")


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    ensure_output_dirs()
    app = init_face_app()
    process_split("train", app)
    process_split("val", app)
    process_split("test", app)
    print("\n🎉 FACE EXTRACTION FINISHED")


if __name__ == "__main__":
    main()
