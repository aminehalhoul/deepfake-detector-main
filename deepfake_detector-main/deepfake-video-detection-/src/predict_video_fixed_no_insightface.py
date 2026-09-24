# predict_video_fixed_no_insightface.py
# Version sans insightface — utilise facenet-pytorch

import argparse
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
import torch
from facenet_pytorch import MTCNN
from torchvision import transforms

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from mobilenet_v3_detector import MobileNetV3Deepfake

FRAME_STEP   = 15
MAX_FRAMES   = 24
IMG_SIZE     = 160
VIDEO_THRESHOLD = 0.50


# ── Détection visages avec MTCNN ──
def init_face_detector(device):
    return MTCNN(
        image_size=IMG_SIZE,
        margin=20,
        keep_all=False,
        device=device,
        post_process=False
    )


def extract_face_crops(video_path: Path, mtcnn, device) -> List[np.ndarray]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    crops = []
    frame_id = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_id % FRAME_STEP == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            try:
                face_tensor = mtcnn(rgb)
                if face_tensor is not None:
                    # Convertir tensor -> numpy array
                    face_np = face_tensor.permute(1, 2, 0).byte().numpy()
                    crops.append(face_np)
            except Exception as e:
                print(f"⚠️ Detection error frame {frame_id}: {e}")

            if len(crops) >= MAX_FRAMES:
                break

        frame_id += 1

    cap.release()
    return crops


# ── Transformation ──
def build_transform(image_size, mean, std):
    return transforms.Compose([
        transforms.ToPILImage(),
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        transforms.Normalize(mean=mean, std=std),
    ])


# ── Chargement modèle ──
def load_model(model_path: Path, device):
    checkpoint = torch.load(model_path, map_location=device)

    model = MobileNetV3Deepfake(num_classes=2, pretrained=False)

    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        model.load_state_dict(checkpoint["model_state_dict"])
        class_names  = checkpoint.get("class_names", ["fake", "real"])
        class_to_idx = checkpoint.get("class_to_idx", {"fake": 0, "real": 1})
        image_size   = int(checkpoint.get("image_size", IMG_SIZE))
        mean         = checkpoint.get("mean", [0.485, 0.456, 0.406])
        std          = checkpoint.get("std",  [0.229, 0.224, 0.225])
    else:
        model.load_state_dict(checkpoint)
        class_names  = ["fake", "real"]
        class_to_idx = {"fake": 0, "real": 1}
        image_size   = IMG_SIZE
        mean         = [0.485, 0.456, 0.406]
        std          = [0.229, 0.224, 0.225]

    model.to(device).eval()
    return model, class_names, class_to_idx, image_size, mean, std


# ── Prédiction ──
def predict_crops(crops, model, transform, device, class_to_idx):
    fake_idx = class_to_idx["fake"]
    fake_scores = []

    with torch.no_grad():
        for crop in crops:
            tensor = transform(crop).unsqueeze(0).to(device)
            logits = model(tensor)
            probs  = torch.softmax(logits, dim=1)[0].cpu().numpy()
            fake_scores.append(float(probs[fake_idx]))

    return fake_scores


# ── Main ──
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video",     type=str, required=True)
    parser.add_argument("--model",     type=str, default="deepfake-video-detection-/models/best_model.pth")
    parser.add_argument("--threshold", type=float, default=VIDEO_THRESHOLD)
    args = parser.parse_args()

    device     = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Device:", device)

    video_path = Path(args.video)
    model_path = Path(args.model)

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    model, class_names, class_to_idx, image_size, mean, std = load_model(model_path, device)
    transform = build_transform(image_size, mean, std)
    mtcnn     = init_face_detector(device)

    print(f"Classes : {class_names}")
    print(f"Extracting faces from : {video_path}")
    crops = extract_face_crops(video_path, mtcnn, device)

    if len(crops) == 0:
        print("❌ No faces detected in the video.")
        return

    print(f"Faces extracted : {len(crops)}")
    fake_scores = predict_crops(crops, model, transform, device, class_to_idx)

    scores       = np.array(fake_scores, dtype=np.float32)
    score_median = float(np.median(scores))
    top_k        = min(6, len(scores))
    score_top    = float(np.mean(np.sort(scores)[-top_k:]))
    score_fake   = 0.6 * score_median + 0.4 * score_top
    score_real   = 1.0 - score_fake
    suspicious   = int(np.sum(scores >= 0.55))

    if score_fake >= 0.58 and suspicious >= 4:
        verdict    = "FAKE"
        confidence = "HIGH"
    elif score_fake <= 0.42 and suspicious <= 2:
        verdict    = "REAL"
        confidence = "HIGH"
    else:
        verdict    = "UNCERTAIN"
        confidence = "MEDIUM"

    print("\n===== VIDEO RESULT =====")
    print(f"Frames analysed    : {len(crops)}")
    print(f"Score FAKE         : {score_fake:.4f}")
    print(f"Score REAL         : {score_real:.4f}")
    print(f"Median FAKE        : {score_median:.4f}")
    print(f"Top-{top_k} mean   : {score_top:.4f}")
    print(f"Suspicious frames  : {suspicious}")
    print(f"Confidence         : {confidence}")
    print(f"Verdict            : {verdict}")


if __name__ == "__main__":
    main()