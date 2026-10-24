"""Local CPU OCR, content-addressed cache; no remote/model API."""
import hashlib, json, time
from pathlib import Path
from PIL import Image
import numpy as np

_engine = None

def read(path, cache_dir=None):
    global _engine
    im = Image.open(path).convert('RGB')
    key = hashlib.sha256(im.tobytes() + str(im.size).encode()).hexdigest()
    cache = Path(cache_dir) / (key + '.json') if cache_dir else None
    if cache and cache.exists():
        result = json.loads(cache.read_text(encoding='utf-8'))
        result['cache_hit'] = True
        return result
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    start = time.monotonic()
    rows, _ = _engine(np.asarray(im))
    lines = []
    for polygon, text, confidence in rows or []:
        xs, ys = zip(*polygon)
        lines.append({'text': text, 'conf': float(confidence),
                      'box': [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))]})
    lines.sort(key=lambda x: (round(x['box'][1] / 10), x['box'][0]))
    result = {'engine': 'rapidocr-onnxruntime', 'hash': key, 'size': list(im.size),
              'seconds': round(time.monotonic()-start, 3), 'cache_hit': False, 'lines': lines}
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
