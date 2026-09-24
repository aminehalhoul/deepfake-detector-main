import torch
import numpy as np
from PIL import Image
import albumentations as A
from albumentations.pytorch import ToTensorV2
import sys
import os
import tkinter as tk
from tkinter import filedialog

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.model import DeepfakeDetector

DEVICE     = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MODEL_PATH = "models/best_model.pth"

transform = A.Compose([
    A.Resize(224, 224),
    A.Normalize(mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]),
    ToTensorV2()
])


def select_image():
    # Ouvrir le file explorer Windows
    root = tk.Tk()
    root.withdraw()  # cacher la fenêtre tkinter
    image_path = filedialog.askopenfilename(
        title="Choisir une image",
        filetypes=[
            ("Images", "*.jpg *.jpeg *.png *.bmp *.webp"),
            ("Tous les fichiers", "*.*")
        ]
    )
    root.destroy()
    return image_path


def predict_image(image_path):
    # Charger le modèle
    model = DeepfakeDetector(pretrained=False).to(DEVICE)
    model.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
    model.eval()

    # Lire et préparer l'image
    image = np.array(Image.open(image_path).convert("RGB"))
    augmented = transform(image=image)
    tensor = augmented["image"].unsqueeze(0).to(DEVICE)

    # Prédiction
    with torch.no_grad():
        output = torch.sigmoid(model(tensor)).item()

    # Résultat
    verdict   = "DEEPFAKE" if output > 0.5 else "RÉEL"
    confiance = output if output > 0.5 else 1 - output

    print(f"\n{'='*40}")
    print(f"Image    : {os.path.basename(image_path)}")
    print(f"Verdict  : {verdict}")
    print(f"Score    : {output:.4f}")
    print(f"Confiance: {confiance*100:.1f}%")
    print(f"{'='*40}\n")

    return verdict, output


if __name__ == "__main__":
    print("Ouverture du sélecteur de fichier...")
    image_path = select_image()

    if image_path:
        predict_image(image_path)
    else:
        print("Aucune image sélectionnée.")