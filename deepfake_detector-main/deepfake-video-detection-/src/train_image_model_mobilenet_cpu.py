import json
import random
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms
from tqdm import tqdm

from models.mobilenet_v3_detector import MobileNetV3Deepfake

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

TRAIN_DIR = Path("data/processed/faces/train")
VAL_DIR = Path("data/processed/faces/val")
TEST_DIR = Path("data/processed/faces/test")

MODEL_DIR = Path("models")
RESULTS_DIR = Path("results")
MODEL_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_SIZE = 160
BATCH_SIZE = 8
EPOCHS = 5
LR = 5e-5
PATIENCE = 2

USE_SUBSET = True
TRAIN_PER_CLASS = 4000
VAL_PER_CLASS = 500
TEST_PER_CLASS = 500

MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", DEVICE)

train_tf = transforms.Compose([
    transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])

eval_tf = transforms.Compose([
    transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])
def build_balanced_subset(dataset: datasets.ImageFolder, n_per_class: int, seed: int = 42) -> Subset:
    rng = random.Random(seed)
    class_to_indices: Dict[int, List[int]] = {i: [] for i in range(len(dataset.classes))}

    for idx, (_, label) in enumerate(dataset.samples):
        class_to_indices[label].append(idx)

    chosen_indices: List[int] = []
    for class_idx, indices in class_to_indices.items():
        take_n = min(n_per_class, len(indices))
        chosen_indices.extend(rng.sample(indices, take_n))

    rng.shuffle(chosen_indices)
    return Subset(dataset, chosen_indices)


def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module
) -> Tuple[float, float, float, List[int], List[int]]:
    model.eval()
    losses: List[float] = []
    all_labels: List[int] = []
    all_preds: List[int] = []

    with torch.no_grad():
        for images, labels in loader:
            images = images.to(DEVICE)
            labels = labels.to(DEVICE)

            outputs = model(images)
            loss = criterion(outputs, labels)
            preds = torch.argmax(outputs, dim=1)

            losses.append(loss.item())
            all_labels.extend(labels.cpu().numpy().tolist())
            all_preds.extend(preds.cpu().numpy().tolist())

    avg_loss = float(sum(losses) / len(losses)) if losses else 0.0
    acc = float(accuracy_score(all_labels, all_preds)) if all_labels else 0.0
    macro_f1 = float(f1_score(all_labels, all_preds, average="macro", zero_division=0)) if all_labels else 0.0

    return avg_loss, acc, macro_f1, all_labels, all_preds
def main() -> None:
    if not TRAIN_DIR.exists() or not VAL_DIR.exists() or not TEST_DIR.exists():
        raise FileNotFoundError("Les dossiers faces n'existent pas. Lance d'abord l'extraction.")

    train_ds_full = datasets.ImageFolder(TRAIN_DIR, transform=train_tf)
    val_ds_full = datasets.ImageFolder(VAL_DIR, transform=eval_tf)
    test_ds_full = datasets.ImageFolder(TEST_DIR, transform=eval_tf)

    print("Classes:", train_ds_full.classes)
    print("Class to idx:", train_ds_full.class_to_idx)
    print("Train images (full):", len(train_ds_full))
    print("Val images   (full):", len(val_ds_full))
    print("Test images  (full):", len(test_ds_full))

    if USE_SUBSET:
        train_ds = build_balanced_subset(train_ds_full, TRAIN_PER_CLASS, seed=SEED)
        val_ds = build_balanced_subset(val_ds_full, VAL_PER_CLASS, seed=SEED)
        test_ds = build_balanced_subset(test_ds_full, TEST_PER_CLASS, seed=SEED)

        print("\nSubset mode enabled")
        print("Train images (subset):", len(train_ds))
        print("Val images   (subset):", len(val_ds))
        print("Test images  (subset):", len(test_ds))
    else:
        train_ds, val_ds, test_ds = train_ds_full, val_ds_full, test_ds_full

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    model = MobileNetV3Deepfake(num_classes=2, pretrained=True).to(DEVICE)

    for param in model.model.features.parameters():
        param.requires_grad = False

    for param in model.model.features[-3:].parameters():
        param.requires_grad = True

    for param in model.model.classifier.parameters():
        param.requires_grad = True

    print("Last MobileNet blocks + classifier unfrozen")

    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
    optimizer = torch.optim.AdamW(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=LR,
        weight_decay=1e-4
    )
    scheduler = ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=1)

    history = {
        "train_loss": [],
        "val_loss": [],
        "train_acc": [],
        "val_acc": [],
        "train_macro_f1": [],
        "val_macro_f1": [],
    }

    best_val_f1 = -1.0
    early_stop_counter = 0
    best_model_path = MODEL_DIR / "best_model.pth"

    for epoch in range(EPOCHS):
        model.train()
        train_losses: List[float] = []
        train_labels: List[int] = []
        train_preds: List[int] = []

        loop = tqdm(train_loader, desc=f"Epoch {epoch + 1}/{EPOCHS}")
        for images, labels in loop:
            images = images.to(DEVICE)
            labels = labels.to(DEVICE)

            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            preds = torch.argmax(outputs, dim=1)
            train_losses.append(loss.item())
            train_labels.extend(labels.cpu().numpy().tolist())
            train_preds.extend(preds.cpu().numpy().tolist())

            loop.set_postfix(loss=f"{loss.item():.4f}")

        train_loss = float(sum(train_losses) / len(train_losses)) if train_losses else 0.0
        train_acc = float(accuracy_score(train_labels, train_preds)) if train_labels else 0.0
        train_macro_f1 = float(f1_score(train_labels, train_preds, average="macro", zero_division=0)) if train_labels else 0.0

        val_loss, val_acc, val_macro_f1, _, _ = evaluate(model, val_loader, criterion)
        scheduler.step(val_macro_f1)

        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)
        history["train_acc"].append(train_acc)
        history["val_acc"].append(val_acc)
        history["train_macro_f1"].append(train_macro_f1)
        history["val_macro_f1"].append(val_macro_f1)

        print(f"\nEpoch {epoch + 1}")
        print(f"Train Loss: {train_loss:.4f} | Train Acc: {train_acc:.4f} | Train Macro-F1: {train_macro_f1:.4f}")
        print(f"Val   Loss: {val_loss:.4f} | Val   Acc: {val_acc:.4f} | Val   Macro-F1: {val_macro_f1:.4f}")

        if val_macro_f1 > best_val_f1:
            best_val_f1 = val_macro_f1
            early_stop_counter = 0
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "class_names": train_ds_full.classes,
                    "class_to_idx": train_ds_full.class_to_idx,
                    "image_size": IMAGE_SIZE,
                    "mean": MEAN,
                    "std": STD,
                    "best_val_macro_f1": best_val_f1,
                },
                best_model_path,
            )
            print("✅ Best model saved")
        else:
            early_stop_counter += 1
            print(f"Early stopping counter: {early_stop_counter}/{PATIENCE}")
            if early_stop_counter >= PATIENCE:
                print("⏹️ Early stopping triggered")
                break

    checkpoint = torch.load(best_model_path, map_location=DEVICE)
    model.load_state_dict(checkpoint["model_state_dict"])

    test_loss, test_acc, test_macro_f1, test_labels, test_preds = evaluate(model, test_loader, criterion)

    print("\n===== FINAL TEST RESULTS =====")
    print(f"Test Loss     : {test_loss:.4f}")
    print(f"Test Acc      : {test_acc:.4f}")
    print(f"Test Macro-F1 : {test_macro_f1:.4f}")
    print("\nConfusion matrix:")
    print(confusion_matrix(test_labels, test_preds))
    print("\nDetailed report:")
    print(classification_report(test_labels, test_preds, target_names=train_ds_full.classes, zero_division=0))

    with open(RESULTS_DIR / "history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    with open(RESULTS_DIR / "final_metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "test_loss": test_loss,
                "test_acc": test_acc,
                "test_macro_f1": test_macro_f1,
                "class_names": train_ds_full.classes,
                "class_to_idx": train_ds_full.class_to_idx,
            },
            f,
            indent=2,
        )

    print("\n✅ Training finished")
    print(f"Model saved in   : {best_model_path}")
    print(f"History saved in : {RESULTS_DIR / 'history.json'}")
    print(f"Metrics saved in : {RESULTS_DIR / 'final_metrics.json'}")


if __name__ == "__main__":
    main()
