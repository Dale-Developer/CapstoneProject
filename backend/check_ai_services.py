"""ESSCAN V7.3 AI diagnostics. Run from backend: python check_ai_services.py"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env')

BACKEND = Path(__file__).resolve().parent

def resolve(value: str) -> Path:
    p=Path(value)
    return p if p.is_absolute() else (BACKEND / p).resolve()

print('=== ESSCAN V7.3 AI SERVICE CHECK ===')
print('Backend:', BACKEND)

# EasyOCR package and exact custom model
try:
    import easyocr
    print(f'\nEasyOCR package: OK ({getattr(easyocr, "__version__", "version unknown")})')
except Exception as exc:
    print(f'\nEasyOCR package: ERROR - {type(exc).__name__}: {exc}')
    print('Fix: python -m pip install -r requirements.txt')

model_dir=resolve(os.getenv('EASYOCR_MODEL_DIR','./ai_models/easyocr_v5_2/model'))
user_dir=resolve(os.getenv('EASYOCR_USER_NETWORK_DIR','./ai_models/easyocr_v5_2/user_network'))
name=os.getenv('EASYOCR_RECOG_NETWORK','handwriting_finetune_v5_2')
model=model_dir/f'{name}.pth'; yaml=user_dir/f'{name}.yaml'; py=user_dir/f'{name}.py'
print('\nEasyOCR V5.2 files:')
for label,path in [('PTH',model),('YAML',yaml),('PY',py)]:
    print(f'  {label}: {path} -> {"OK" if path.is_file() else "MISSING"}')

if model.is_file() and yaml.is_file() and py.is_file():
    try:
        import sys
        sys.path.insert(0,str(BACKEND))
        from services.ocr_match import easyocr_available, easyocr_error
        ok=easyocr_available()
        print('EasyOCR V5.2 model load:', 'OK' if ok else 'ERROR')
        if not ok: print('  Error:', easyocr_error())
    except Exception as exc:
        print(f'EasyOCR V5.2 model load: ERROR - {type(exc).__name__}: {exc}')
else:
    print('EasyOCR V5.2 model load: SKIPPED because one or more files are missing.')

# Ollama
try:
    import requests
    base=os.getenv('OLLAMA_BASE_URL','http://localhost:11434').rstrip('/')
    target=os.getenv('OLLAMA_VISION_MODEL','qwen2.5vl:3b')
    try:
        r=requests.get(f'{base}/api/tags',timeout=4)
        print(f'\nOllama endpoint: HTTP {r.status_code} at {base}')
        if r.ok:
            names=[m.get('name','') for m in r.json().get('models',[])]
            print('Installed models:', ', '.join(names) if names else '(none)')
            ok=target in names or any(n.startswith(target+':') for n in names)
            print(f"Vision model '{target}':", 'OK' if ok else 'MISSING')
            if not ok: print(f'  Fix: ollama pull {target}')
        else:
            print('Ollama response body:', r.text[:500])
    except Exception as exc:
        print(f'\nOllama endpoint: ERROR - {type(exc).__name__}: {exc}')
        print('  Fix: start/relaunch the Ollama Windows application, then test http://localhost:11434/api/tags')
except Exception as exc:
    print(f'\nPython requests package: ERROR - {type(exc).__name__}: {exc}')
    print('Fix: python -m pip install requests')

print('\n=== END DIAGNOSTIC ===')
