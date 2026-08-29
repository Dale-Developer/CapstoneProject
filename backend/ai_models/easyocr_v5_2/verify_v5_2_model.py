"""
Verify the user's V5.2 checkpoint against the bundled custom EasyOCR network.

Run from backend:
    python ai_models/easyocr_v5_2/verify_v5_2_model.py
"""
from collections import OrderedDict
import os
import sys
import torch

BASE = os.path.dirname(os.path.abspath(__file__))
USER_NETWORK = os.path.join(BASE, "user_network")
MODEL_DIR = os.path.join(BASE, "model")
CHECKPOINT = os.path.join(MODEL_DIR, "handwriting_finetune_v5_2.pth")

if USER_NETWORK not in sys.path:
    sys.path.insert(0, USER_NETWORK)

from handwriting_finetune_v5_2 import Model

print("V5.2 checkpoint:", CHECKPOINT)

if not os.path.isfile(CHECKPOINT):
    raise FileNotFoundError(
        "Missing V5.2 checkpoint. Copy best_accuracy.pth to:\n"
        + CHECKPOINT
    )

model = Model(
    num_class=97,
    input_channel=1,
    output_channel=256,
    hidden_size=256,
)

state = torch.load(
    CHECKPOINT,
    map_location="cpu",
    weights_only=False,
)

if not all(k.startswith("module.") for k in state):
    raise RuntimeError(
        "Unexpected checkpoint format: expected DataParallel "
        "'module.' prefixes."
    )

state = OrderedDict(
    (k[7:], v) for k, v in state.items()
)

model.load_state_dict(state, strict=True)

with torch.no_grad():
    dummy = torch.randn(1, 1, 64, 600)
    output = model(dummy, None)

print("V5.2 model loaded successfully.")
print("Output shape:", tuple(output.shape))
print("Expected output: (1, sequence_length, 97)")
print("Architecture: None-VGG-BiLSTM-CTC")
