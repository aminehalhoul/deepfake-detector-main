# src/predict_video_from_image_model_fixed.py

import argparse
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
import torch
from insightface.app import FaceAnalysis
from torchvision import transforms

from models.mobilenet_v3_detector import MobileNetV3Deepfake

FRAME_STEP = 15
MAX_FRAMES = 24
IMG_SIZE = 160
DET_SIZE = 320
MAX_SIDE = 640
DET_SCORE_THRESHOLD = 0.60
VIDEO_THRESHOLD = 0.50


def init_face_app() -> FaceAnalysis:
    app = FaceAnalysis(
        name="buffalo_l",
        allowed_modules=["detection"],
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(DET_SIZE, DET_SIZE))
    return app


def scale_for_detection(frame):
    h, w = frame.shape[:2]
    max_dim = max(h, w)
    if max_dim > MAX_SIDE:
        scale = MAX_SIDE / max_dim
        resized = cv2.resize(frame, (int(w * scale), int(h * scale)))
        return resized, scale
    return frame, 1.0


def safe_crop(frame, x1: int, y1: int, x2: int, y2: int):
    h, w = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2]
    return crop if crop is not None and crop.size > 0 else None


def build_transform(image_size: int, mean: List[float], std: List[float]):
    return transforms.Compose([
        transforms.ToPILImage(),
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        transforms.Normalize(mean=mean, std=std),
    ])


def extract_face_crops(video_path: Path, app: FaceAnalysis) -> List[np.ndarray]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    crops: List[np.ndarray] = []
    frame_id = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_id % FRAME_STEP == 0:
            det_frame, scale = scale_for_detection(frame)
            faces = app.get(det_frame)
            valid_faces = [f for f in faces if getattr(f, "det_score", 1.0) >= DET_SCORE_THRESHOLD]

            if valid_faces:
                face = max(
                    valid_faces,
                    key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
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
                    crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                    crops.append(crop)

            if len(crops) >= MAX_FRAMES:
                break

        frame_id += 1

    cap.release()
    return crops


def load_model(
    model_path: Path,
    device: torch.device
) -> Tuple[MobileNetV3Deepfake, List[str], dict, int, List[float], List[float]]:
    checkpoint = torch.load(model_path, map_location=device)

    model = MobileNetV3Deepfake(num_classes=2, pretrained=False)

    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        model.load_state_dict(checkpoint["model_state_dict"])
        class_names = checkpoint.get("class_names", ["fake", "real"])
        class_to_idx = checkpoint.get("class_to_idx", {"fake": 0, "real": 1})
        image_size = int(checkpoint.get("image_size", IMG_SIZE))
        mean = checkpoint.get("mean", [0.485, 0.456, 0.406])
        std = checkpoint.get("std", [0.229, 0.224, 0.225])
    else:
        model.load_state_dict(checkpoint)
        class_names = ["fake", "real"]
        class_to_idx = {"fake": 0, "real": 1}
        image_size = IMG_SIZE
        mean = [0.485, 0.456, 0.406]
        std = [0.229, 0.224, 0.225]

    model.to(device)
    model.eval()
    return model, class_names, class_to_idx, image_size, mean, std


def predict_crops(
    crops: List[np.ndarray],
    model: MobileNetV3Deepfake,
    transform,
    device: torch.device,
    class_to_idx: dict
) -> List[float]:
    fake_idx = class_to_idx["fake"]
    fake_scores: List[float] = []

    with torch.no_grad():
        for crop in crops:
            tensor = transform(crop).unsqueeze(0).to(device)
            logits = model(tensor)
            probs = torch.softmax(logits, dim=1)[0].cpu().numpy()
            fake_scores.append(float(probs[fake_idx]))

    return fake_scores


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=str, required=True, help="Path to the video to verify")
    parser.add_argument("--model", type=str, default="models/best_model.pth", help="Path to the trained image model")
    parser.add_argument("--threshold", type=float, default=VIDEO_THRESHOLD, help="Base threshold (default=0.50)")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Device:", device)

    video_path = Path(args.video)
    model_path = Path(args.model)

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    model, class_names, class_to_idx, image_size, mean, std = load_model(model_path, device)
    transform = build_transform(image_size, mean, std)
    app = init_face_app()

    print(f"Loaded classes: {class_names}")
    print(f"Extracting faces from: {video_path}")
    crops = extract_face_crops(video_path, app)

    if len(crops) == 0:
        print("❌ No faces detected in the video.")
        return

    print(f"Faces extracted: {len(crops)}")
    fake_scores = predict_crops(crops, model, transform, device, class_to_idx)

    scores = np.array(fake_scores, dtype=np.float32)

    score_median = float(np.median(scores))
    top_k = min(6, len(scores))
    score_top = float(np.mean(np.sort(scores)[-top_k:]))

    score_fake = 0.6 * score_median + 0.4 * score_top
    score_real = 1.0 - score_fake

    suspicious_count = int(np.sum(scores >= 0.55))
    tendance = "FAKE" if score_fake >= args.threshold else "REAL"

    if score_fake >= 0.58 and suspicious_count >= 4:
        verdict = "FAKE"
        confidence = "HIGH"
    elif score_fake <= 0.42 and suspicious_count <= 2:
        verdict = "REAL"
        confidence = "HIGH"
    else:
        verdict = "UNCERTAIN"
        confidence = "MEDIUM"

    print("\n===== VIDEO RESULT =====")
    print(f"Frames analysed    : {len(crops)}")
    print(f"Score FAKE         : {score_fake:.4f}")
    print(f"Score REAL         : {score_real:.4f}")
    print(f"Median FAKE        : {score_median:.4f}")
    print(f"Top-{top_k} mean   : {score_top:.4f}")
    print(f"Suspicious frames  : {suspicious_count}")
    print(f"Confidence         : {confidence}")
    print(f"Verdict officiel   : {verdict}")
    print(f"Tendance           : {tendance}")


if __name__ == "__main__":
    main()
