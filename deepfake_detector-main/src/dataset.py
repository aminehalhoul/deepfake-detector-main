import os
import torch
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import albumentations as A
from albumentations.pytorch import ToTensorV2
import numpy as np
import random

DATA_PATH = r"C:\Users\ASUS\Downloads\4IASDR8\deepfake_detector\data\real_vs_fake\real-vs-fake"

train_transform = A.Compose([
    A.Resize(224, 224),
    A.HorizontalFlip(p=0.5),
    A.RandomBrightnessContrast(p=0.3),
    A.ImageCompression(quality_lower=60, quality_upper=100, p=0.3),
    A.Normalize(mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]),
    ToTensorV2()
])

val_transform = A.Compose([
    A.Resize(224, 224),
    A.Normalize(mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]),
    ToTensorV2()
])

class DeepfakeDataset(Dataset):

    def __init__(self, split="train", transform=None, max_samples=None):
        self.transform = transform
        self.images = []
        self.labels = []

        fake_path = os.path.join(DATA_PATH, split, "fake")
        for img_name in os.listdir(fake_path):
            self.images.append(os.path.join(fake_path, img_name))
            self.labels.append(1)

        real_path = os.path.join(DATA_PATH, split, "real")
        for img_name in os.listdir(real_path):
            self.images.append(os.path.join(real_path, img_name))
            self.labels.append(0)

        combined = list(zip(self.images, self.labels))
        random.shuffle(combined)
        self.images, self.labels = zip(*combined)
        self.images = list(self.images)
        self.labels = list(self.labels)

        if max_samples:
            self.images = self.images[:max_samples]
            self.labels = self.labels[:max_samples]

        n_fake = sum(self.labels)
        n_real = len(self.labels) - n_fake
        print(f"Dataset {split} : {len(self.images)} images "
              f"({n_fake} fake, {n_real} real)")

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        image = np.array(Image.open(self.images[idx]).convert("RGB"))

        if self.transform:
            augmented = self.transform(image=image)
            image = augmented["image"]

        label = torch.tensor(self.labels[idx], dtype=torch.float32)
        return image, label


def get_dataloaders(batch_size=64):
    train_dataset = DeepfakeDataset("train", transform=train_transform,
                                    max_samples=10000)
    val_dataset   = DeepfakeDataset("valid", transform=val_transform,
                                    max_samples=2000)
    test_dataset  = DeepfakeDataset("test",  transform=val_transform,
                                    max_samples=2000)

    train_loader = DataLoader(train_dataset, batch_size=batch_size,
                              shuffle=True,  num_workers=0, pin_memory=True)
    val_loader   = DataLoader(val_dataset,   batch_size=batch_size,
                              shuffle=False, num_workers=0, pin_memory=True)
    test_loader  = DataLoader(test_dataset,  batch_size=batch_size,
                              shuffle=False, num_workers=0, pin_memory=True)

    return train_loader, val_loader, test_loader


if __name__ == "__main__":
    train_loader, val_loader, test_loader = get_dataloaders(batch_size=64)
    images, labels = next(iter(train_loader))
    print(f"Shape batch images : {images.shape}")
    print(f"Shape batch labels : {labels.shape}")
    print(f"Exemple labels     : {labels[:8]}")
    print("\nDataset pret pour l'entrainement !")