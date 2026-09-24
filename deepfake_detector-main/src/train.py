import torch
import torch.nn as nn
from torch.optim.lr_scheduler import CosineAnnealingLR
import numpy as np
from sklearn.metrics import roc_auc_score
import time
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dataset import get_dataloaders
from src.model import DeepfakeDetector

# Configuration
EPOCHS     = 20
BATCH_SIZE = 32
LR         = 1e-4
DEVICE     = torch.device("cuda" if torch.cuda.is_available() else "cpu")
SAVE_PATH  = "models/best_model.pth"

os.makedirs("models", exist_ok=True)

from tqdm import tqdm

def train_one_epoch(model, loader, criterion, optimizer):
    model.train()
    total_loss = 0
    all_labels, all_preds = [], []

    # Ajout de tqdm ici
    pbar = tqdm(loader, desc="Training", leave=False)

    for images, labels in pbar:
        images = images.to(DEVICE)
        labels = labels.to(DEVICE).unsqueeze(1)

        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        total_loss += loss.item()
        probs = torch.sigmoid(outputs).detach().cpu().numpy()
        all_preds.extend(probs)
        all_labels.extend(labels.cpu().numpy())

        # Afficher la loss en temps réel
        pbar.set_postfix(loss=f"{loss.item():.4f}")

    avg_loss = total_loss / len(loader)
    auc = roc_auc_score(all_labels, all_preds)
    return avg_loss, auc


def evaluate(model, loader, criterion):
    model.eval()
    total_loss = 0
    all_labels, all_preds = [], []

    with torch.no_grad():
        for images, labels in loader:
            images = images.to(DEVICE)
            labels = labels.to(DEVICE).unsqueeze(1)

            outputs = model(images)
            loss = criterion(outputs, labels)

            total_loss += loss.item()
            probs = torch.sigmoid(outputs).cpu().numpy()
            all_preds.extend(probs)
            all_labels.extend(labels.cpu().numpy())

    avg_loss = total_loss / len(loader)
    auc = roc_auc_score(all_labels, all_preds)
    return avg_loss, auc


def main():
    print(f"Device : {DEVICE}")
    print(f"GPU    : {torch.cuda.get_device_name(0)}\n")

    # Charger les données
    print("Chargement des données...")
    train_loader, val_loader, _ = get_dataloaders(BATCH_SIZE)

    # Créer le modèle
    print("Création du modèle...")
    model = DeepfakeDetector(pretrained=True).to(DEVICE)

    # Fonction de coût, optimiseur, scheduler
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    scheduler = CosineAnnealingLR(optimizer, T_max=EPOCHS)

    best_auc   = 0.0
    train_losses, val_losses = [], []
    train_aucs,   val_aucs   = [], []

    print("\nDémarrage de l'entraînement...\n")
    print(f"{'Epoch':<8}{'Train Loss':<14}{'Train AUC':<14}"
          f"{'Val Loss':<14}{'Val AUC':<14}{'Temps'}")
    print("─" * 70)

    for epoch in range(1, EPOCHS + 1):
        start = time.time()

        train_loss, train_auc = train_one_epoch(
            model, train_loader, criterion, optimizer)
        val_loss, val_auc = evaluate(
            model, val_loader, criterion)

        scheduler.step()
        elapsed = time.time() - start

        train_losses.append(train_loss)
        val_losses.append(val_loss)
        train_aucs.append(train_auc)
        val_aucs.append(val_auc)

        # Sauvegarder le meilleur modèle
        if val_auc > best_auc:
            best_auc = val_auc
            torch.save(model.state_dict(), SAVE_PATH)
            saved = "✓ sauvegardé"
        else:
            saved = ""

        print(f"{epoch:<8}{train_loss:<14.4f}{train_auc:<14.4f}"
              f"{val_loss:<14.4f}{val_auc:<14.4f}"
              f"{elapsed:.0f}s  {saved}")

    print(f"\nMeilleur AUC validation : {best_auc:.4f}")
    print(f"Modèle sauvegardé dans  : {SAVE_PATH}")


if __name__ == "__main__":
    main()