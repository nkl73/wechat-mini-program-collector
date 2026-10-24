"""Run status and portable, escaped evidence report."""
import html,json,os,tempfile,time
from pathlib import Path
from datetime import datetime

def human(value):
    return {'finished supplied screenshots':'已有截图处理完毕','preview ready':'预览已准备好，请核对提取内容',
            'paused by user':'任务已暂停，可继续采集','STOP file':'已停止采集','needs_review':'遇到新页面，等待 Agent 判断',
            'scroll limit':'达到本次采集范围，已保存部分结果','time limit':'达到时间上限，已保存部分结果',
            'single page captured':'当前页面已提取','running':'正在采集',
            'unchanged frames; suspected bottom, not proof of completeness':'画面连续未变化，可能到达底部；尚不能确认完整',
            'low_ocr_confidence':'部分文字识别置信度偏低',
            'last_visible_item_may_be_partial':'曾位于屏幕底部，内容可能不完整',
            'weak_identity_possible_duplicate':'缺少可靠编号，可能存在重复'}.get(value,value)

def atomic_text(path,text,encoding='utf-8'):
    path=Path(path)
    with tempfile.NamedTemporaryFile(mode='w',encoding=encoding,dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as f:
        f.write(text);tmp=Path(f.name)
    try:
        for attempt in range(6):
            try:tmp.replace(path);return
            except PermissionError:
                if attempt==5:raise
                # Windows readers/scanners can temporarily hold the destination.
                time.sleep(.025*(2**attempt))
    finally:tmp.unlink(missing_ok=True)

def write_json(path,data):
    atomic_text(path,json.dumps(data,ensure_ascii=False,indent=2))

def status(out,phase,**kwargs):
    p=Path(out)/'status.json'
    try:old=json.loads(p.read_text(encoding='utf-8'))
    except (OSError,ValueError):old={}
    if 'message' in kwargs:kwargs['message']=human(kwargs['message'])
    old.update(kwargs);old.update(phase=phase,updated=datetime.now().isoformat(timespec='seconds'))
    write_json(p,old)

def report(out,items,summary):
    out=Path(out);esc=html.escape
    cards=[]
    for item in items:
        links=[]
        for source in item['sources']:
            path=Path(source['shot'])
            try:relative=path.resolve().relative_to(out.resolve()).as_posix()
            except ValueError:continue
            links.append(f'<a href="{esc(relative,quote=True)}" target="_blank">查看来源截图</a>')
        fields=''.join(f'<dt>{esc(str(k))}</dt><dd>{esc(str(v))}</dd>' for k,v in item['fields'].items())
        if item.get('navigation_path'):fields='<dt>浏览路径</dt><dd>'+esc(' → '.join(item['navigation_path']))+'</dd>'+fields
        issues=[human(x) for x in item.get('issues',[])]
        cards.append(f'<article data-issue="{int(bool(issues))}"><h2>{esc(item["title"])}</h2><dl>{fields}</dl><pre>{esc(item["body"])}</pre><details><summary>核对信息 · {len(issues)} 项</summary><p>{esc("；".join(issues)) or "未标记问题；仍建议抽查"}</p>{" · ".join(links)}</details></article>')
    content='''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>采集结果</title><style>body{max-width:1080px;margin:40px auto;padding:0 24px;background:#f5f7fb;color:#19283a;font:16px system-ui}h1{font-size:32px}header,article{background:white;border:1px solid #dce4ed;border-radius:14px;padding:24px;margin:16px 0}a{color:#165bbb}input{padding:12px;width:55%;border:1px solid #aaa;border-radius:8px}pre{white-space:pre-wrap;font:inherit;color:#455466}dl{display:grid;grid-template-columns:120px 1fr}dd{margin:0}summary{cursor:pointer}button{padding:10px}small{color:#65768a}</style><header><small>本地内容采集 · 可追溯结果</small><h1>已整理 ITEMS 条内容</h1><p>STOP</p><p>这是本次可见内容的部分采集，不代表整个小程序完整覆盖。</p><a href="items.csv" download>下载表格</a> · <a href="items.json" download>下载 JSON</a> · <a href="items.md">查看文本</a></header><input id="q" placeholder="搜索标题、正文或字段"><label><input id="issues" type="checkbox" style="width:auto">只看待核对</label><main>CARDS</main><script>function filter(){let q=document.querySelector('#q').value.toLowerCase(),only=document.querySelector('#issues').checked;document.querySelectorAll('article').forEach(a=>a.hidden=!a.textContent.toLowerCase().includes(q)||(only&&a.dataset.issue==='0'))}document.querySelector('#q').oninput=filter;document.querySelector('#issues').onchange=filter;</script></html>'''
    content=content.replace('ITEMS',str(len(items))).replace('STOP',esc(human(summary['stop_reason']))).replace('CARDS',''.join(cards))
    atomic_text(out/'index.html',content)
