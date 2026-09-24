import torch
import torch.nn as nn
import timm

class DeepfakeDetector(nn.Module):
    def __init__(self, model_name='efficientnet_b4', pretrained=True):
        super(DeepfakeDetector, self).__init__()

        # Charger EfficientNet pré-entraîné sur ImageNet
        self.model = timm.create_model(
            model_name,
            pretrained=pretrained,
            num_classes=0  # on enlève la dernière couche
        )

        # Récupérer le nombre de features de sortie
        num_features = self.model.num_features

        # Notre classifieur personnalisé
        self.classifier = nn.Sequential(
            nn.Dropout(p=0.4),
            nn.Linear(num_features, 256),
            nn.ReLU(),
            nn.Dropout(p=0.3),
            nn.Linear(256, 1)  # sortie : 1 neurone (réel ou fake)
        )

    def forward(self, x):
        # Extraire les features avec EfficientNet
        features = self.model(x)
        # Classifier les features
        output = self.classifier(features)
        return output


# Test du modèle
if __name__ == "__main__":
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device utilisé : {device}")

    # Créer le modèle
    model = DeepfakeDetector(pretrained=True).to(device)

    # Test avec un batch fictif
    dummy_input = torch.randn(4, 3, 224, 224).to(device)
    output = model(dummy_input)

    print(f"Shape entrée  : {dummy_input.shape}")
    print(f"Shape sortie  : {output.shape}")
    print(f"Sortie brute  : {output.detach().cpu().numpy()}")
    print(f"\nModele pret pour l'entrainement !")

    # Compter les paramètres
    total_params = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Total paramètres    : {total_params:,}")
    print(f"Paramètres entraînables : {trainable:,}")