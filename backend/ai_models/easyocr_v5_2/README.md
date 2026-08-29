# Verified EasyOCR V5.2 model

## Required files

model/
  handwriting_finetune_v5_2.pth

user_network/
  handwriting_finetune_v5_2.py
  handwriting_finetune_v5_2.yaml

The `.pth` is intentionally not included in this source archive because the
uploaded V6.7 project did not contain the V5.2 checkpoint. Copy your verified
14.44 MB V5.2 `best_accuracy.pth` here and rename it to
`handwriting_finetune_v5_2.pth`.

Run `python verify_v5_2_model.py` from this directory to verify strict
state-dict compatibility before starting FastAPI.
