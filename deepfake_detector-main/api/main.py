from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import torch
import numpy as np
from PIL import Image
import albumentations as A
from albumentations.pytorch import ToTensorV2
import io
import sys
import os
import base64
from datetime import datetime
from bson import ObjectId

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.model import DeepfakeDetector

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
MONGO_URL = "mongodb://localhost:27017"
client    = AsyncIOMotorClient(MONGO_URL)
db        = client["deepfake_detector"]
collection = db["analyses"]

DEVICE     = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MODEL_PATH = "models/best_model.pth"

model = DeepfakeDetector(pretrained=False).to(DEVICE)
model.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
model.eval()

transform = A.Compose([
    A.Resize(224, 224),
    A.Normalize(mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]),
    ToTensorV2()
])


@app.get("/")
def home():
    return {"message": "Deepfake Detector API", "status": "running"}


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    contents = await file.read()

    # Prédiction
    image = np.array(Image.open(io.BytesIO(contents)).convert("RGB"))
    augmented = transform(image=image)
    tensor = augmented["image"].unsqueeze(0).to(DEVICE)

    with torch.no_grad():
        output = torch.sigmoid(model(tensor)).item()

    verdict   = "DEEPFAKE" if output > 0.5 else "RÉEL"
    confiance = output if output > 0.5 else 1 - output

    # Convertir image en base64 pour MongoDB
    image_base64 = base64.b64encode(contents).decode("utf-8")

    # Sauvegarder dans MongoDB
    document = {
        "filename"  : file.filename,
        "verdict"   : verdict,
        "score"     : round(output, 4),
        "confiance" : round(confiance * 100, 1),
        "date"      : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image"     : image_base64,        # image complète sauvegardée
        "image_type": file.content_type
    }
    await collection.insert_one(document)

    return {
        "verdict"  : verdict,
        "score"    : round(output, 4),
        "confiance": round(confiance * 100, 1)
    }

@app.delete("/history/{item_id}")
async def delete_one(item_id: str):
    await collection.delete_one({"_id": ObjectId(item_id)})
    return {"message": "Analyse supprimée"}

@app.get("/history")
async def get_history():
    analyses = []
    cursor = collection.find().sort("date", -1).limit(20)
    async for doc in cursor:
        analyses.append({
            "id"       : str(doc["_id"]),
            "filename" : doc["filename"],
            "verdict"  : doc["verdict"],
            "score"    : doc["score"],
            "confiance": doc["confiance"],
            "date"     : doc["date"],
            "image"    : doc["image"],      # image en base64
            "type"     : doc["image_type"]
        })
    return analyses


@app.delete("/history")
async def clear_history():
    await collection.delete_many({})
    return {"message": "Historique supprimé"}