# V5.2 EasyOCR location

V6.8 uses `backend/ai_models/easyocr_v5_2/` for the verified V5.2 custom model.

The older `easyocr_finetuned/` directory is retained for compatibility but is
not the active model path.

Place the checkpoint here:

`backend/ai_models/easyocr_v5_2/model/handwriting_finetune_v5_2.pth`

The matching network files are already included under:

`backend/ai_models/easyocr_v5_2/user_network/`
