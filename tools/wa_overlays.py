"""Reviewed overlay rules. No model calls, no fixed screen-coordinate clicking."""
import base64,io,re
import numpy as np
from PIL import Image

SUSPECT=re.compile(r'长按.*(?:关注|扫码)|扫码关注|接收重要.*提醒|隐私.*(?:同意|授权)|允许.*(?:位置|通知)')

def matching(profile,ocr):
    from wa_engine import in_region
    found=[]
    for rule in profile.get('overlays',[]):
        text='\n'.join(x['text'] for x in in_region(ocr['lines'],ocr['size'],rule['region']) if x['conf']>=.80)
        if all(re.search(p,text,re.I) for p in rule['patterns']):found.append(rule)
    if len(found)>1:raise ValueError('多个弹窗规则同时命中，需要复核')
    return found[0] if found else None

def suspected(ocr):
    return bool(SUSPECT.search('\n'.join(x['text'] for x in ocr['lines'])))

def identity(rule,ocr):
    from wa_engine import in_region,norm
    text='\n'.join(x['text'] for x in in_region(ocr['lines'],ocr['size'],rule['identity_region']) if x['conf']>=.80)
    keys={norm(m.group(1)) for m in re.finditer(rule['identity_pattern'],text,re.I)}
    if len(keys)!=1:raise ValueError('弹窗背后的页面标识不唯一，需要复核')
    return keys.pop()

def locate(rule,shot):
    import cv2
    image=Image.open(shot).convert('L');w,h=image.size
    r=rule['close_region'];bounds=(int(r[0]*w),int(r[1]*h),int(r[2]*w),int(r[3]*h))
    area=np.array(image.crop(bounds));template=np.array(Image.open(io.BytesIO(base64.b64decode(rule['close_template_png'],validate=True))).convert('L'))
    if min(template.shape)<8 or max(template.shape)>128 or template.std()<10:raise ValueError('关闭图标模板无效')
    hits=[]
    for scale in (.8,1.,1.25,1.5):
        t=cv2.resize(template,None,fx=scale,fy=scale)
        th,tw=t.shape
        if th>area.shape[0] or tw>area.shape[1]:continue
        score=cv2.matchTemplate(area,t,cv2.TM_CCOEFF_NORMED)
        ys,xs=np.where(score>=.94)
        for x,y in zip(xs,ys):hits.append((float(score[y,x]),x+tw/2,y+th/2,tw,th))
    if not hits:raise ValueError('未找到已校准的关闭图标')
    best=max(hits)
    if any(abs(x-best[1])>best[3]/2 or abs(y-best[2])>best[4]/2 for _,x,y,_,_ in hits):raise ValueError('关闭图标不唯一')
    _,x,y,tw,th=best;x+=bounds[0];y+=bounds[1]
    return [x-tw/2,y-th/2,x+tw/2,y+th/2]

