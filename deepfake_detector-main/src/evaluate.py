import torch
import torch.nn as nn
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import (roc_auc_score, f1_score, accuracy_score,
                             confusion_matrix, roc_curve)
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dataset import get_dataloaders
from src.model import DeepfakeDetector

DEVICE    = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MODEL_PATH = "models/best_model.pth"

os.makedirs("results", exist_ok=True)


def evaluate_model(model, loader):
    model.eval()
    all_labels, all_probs = [], []

    with torch.no_grad():
        for images, labels in loader:
            images = images.to(DEVICE)
            outputs = torch.sigmoid(model(images))
            all_probs.extend(outputs.cpu().numpy())
            all_labels.extend(labels.numpy())

    return np.array(all_labels), np.array(all_probs)


def plot_confusion_matrix(y_true, y_pred, save_path):
    cm = confusion_matrix(y_true, y_pred)
    plt.figure(figsize=(8, 6))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                xticklabels=['Réel', 'Fake'],
                yticklabels=['Réel', 'Fake'])
    plt.title('Matrice de Confusion', fontsize=14)
    plt.ylabel('Vraie classe')
    plt.xlabel('Classe prédite')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"Matrice de confusion sauvegardée : {save_path}")


def plot_roc_curve(y_true, y_probs, auc, save_path):
    fpr, tpr, _ = roc_curve(y_true, y_probs)
    plt.figure(figsize=(8, 6))
    plt.plot(fpr, tpr, color='blue', lw=2,
             label=f'ROC curve (AUC = {auc:.4f})')
    plt.plot([0, 1], [0, 1], color='gray', linestyle='--', label='Random')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('Courbe ROC — Détection de Deepfakes', fontsize=14)
    plt.legend(loc='lower right')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"Courbe ROC sauvegardée : {save_path}")


def main():
    print(f"Device : {DEVICE}")
    print(f"Chargement du modèle depuis : {MODEL_PATH}\n")

    # Charger les données de test
    _, _, test_loader = get_dataloaders(batch_size=64)

    # Charger le meilleur modèle
    model = DeepfakeDetector(pretrained=False).to(DEVICE)
    model.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
    print("Modèle chargé avec succès !\n")

    # Évaluer
    print("Évaluation sur le jeu de test...")
    y_true, y_probs = evaluate_model(model, test_loader)
    y_pred = (y_probs > 0.5).astype(int)

    # Métriques
    auc      = roc_auc_score(y_true, y_probs)
    f1       = f1_score(y_true, y_pred)
    accuracy = accuracy_score(y_true, y_pred)

    print("\n========== RÉSULTATS FINAUX ==========")
    print(f"AUC-ROC  : {auc:.4f}")
    print(f"F1-Score : {f1:.4f}")
    print(f"Accuracy : {accuracy*100:.2f}%")
    print("======================================\n")

    # Générer les graphiques
    plot_confusion_matrix(y_true, y_pred,
                          "results/confusion_matrix.png")
    plot_roc_curve(y_true, y_probs, auc,
                   "results/roc_curve.png")

    print("\nTous les résultats sauvegardés dans results/")
    print("Prêt pour GitHub !")


if __name__ == "__main__":
    main()