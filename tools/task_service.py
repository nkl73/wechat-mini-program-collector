"""Shared task API for the local console and Agent CLI."""
import json,os,subprocess,sys,uuid,threading
from pathlib import Path
from datetime import datetime
from wa_engine import load_profile,digest,recognize
from wa_experience import write_json,status
import wa_ocr

TOOLS=Path(__file__).resolve().parent
ROOT=Path(os.environ.get('MINI_COLLECT_HOME',str(TOOLS.parent/'collector-data'))).resolve()
RUNS=ROOT/'runs'
def read(path,default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return default
def task(identifier):
    if not identifier or any(c not in '0123456789abcdef-' for c in identifier):raise ValueError('任务编号无效')
    p=RUNS/identifier
    if not (p/'task.json').exists():raise ValueError('找不到任务')
    return p
def list_tasks():
    return sorted([{**read(p/'task.json',{}),'status':read(p/'status.json',{})} for p in RUNS.glob('*') if (p/'task.json').exists()],key=lambda x:x.get('created',''),reverse=True)
def create(profile_path,collection,offline=None,goal='',limit=20,scope='current'):
    if not collection.strip():raise ValueError('请填写任务名称')
    if not 0<=int(limit)<=200:raise ValueError('采集范围超过上限')
    profile=load_profile(profile_path)
    if scope not in ('current','navigate'):raise ValueError('未知采集范围')
    if offline and scope=='navigate':raise ValueError('静态截图不能执行进入和返回；请选当前页或使用导航测试夹具')
    if offline and not Path(offline).is_dir():raise ValueError('图片目录不存在')
    identifier=uuid.uuid4().hex;out=RUNS/identifier;out.mkdir(parents=True)
    write_json(out/'profile.json',profile)
    config={'id':identifier,'collection':collection,'goal':goal,'offline':str(Path(offline).resolve()) if offline else None,
            'limit':int(limit),'scope':scope,'created':datetime.now().isoformat(timespec='seconds'),'review_limit':3}
    write_json(out/'task.json',config);status(out,'ready',items=0,message='先采一屏，查看提取预览')
    return config
def running():
    lock=ROOT/'worker.lock'
    if not lock.exists():return False
    data=read(lock,{})
    pid=data.get('pid')
    if pid:
        import ctypes
        h=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
        if h:
            code=ctypes.c_ulong();ok=ctypes.windll.kernel32.GetExitCodeProcess(h,ctypes.byref(code));ctypes.windll.kernel32.CloseHandle(h)
            if ok and code.value==259:return True
    # Only the parent releases reservations; a missing PID reservation is active.
    if not pid:return True
    lock.unlink(missing_ok=True);return False
def start(identifier,preview=False):
    out=task(identifier);config=read(out/'task.json');ROOT.mkdir(exist_ok=True,parents=True)
    if running():raise ValueError('已有任务运行，请先暂停或停止')
    if read(out/'status.json',{}).get('phase')=='needs_review':raise ValueError('页面尚未审核，请由 Agent 处理后继续')
    lock=ROOT/'worker.lock'
    try:
        with lock.open('x') as f:json.dump({'task':identifier},f)
    except FileExistsError:raise ValueError('已有任务启动中')
    for name in ('STOP','PAUSE'):(out/name).unlink(missing_ok=True)
    navigating=config.get('scope')=='navigate'
    cmd=[sys.executable,str(TOOLS/('navigation_run.py' if navigating else 'collector.py')),'--profile',str(out/'profile.json'),'--out',str(out),
         '--collection',config['collection']]
    if not navigating:cmd+=['--max-scrolls',str(config['limit'])]
    if config['offline']:cmd+=['--offline-shots',config['offline']]
    if (out/('navigation.json' if navigating else 'state.json')).exists():cmd+=['--resume']
    if preview:cmd+=['--preview']
    status(out,'running',message='正在启动本地采集')
    try:
        with (out/'worker.log').open('a',encoding='utf-8') as log:
            worker=subprocess.Popen(cmd,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        write_json(lock,{'pid':worker.pid,'task':identifier})
    except Exception:
        lock.unlink(missing_ok=True);status(out,'error',message='进程启动失败');raise
    def finish():
        code=worker.wait()
        if read(lock,{}).get('pid')==worker.pid:lock.unlink(missing_ok=True)
        if read(out/'status.json',{}).get('phase')=='running':status(out,'error',message=f'工作进程异常退出：{code}')
    threading.Thread(target=finish,daemon=True).start()
    return {'id':identifier,'pid':worker.pid}
def control(identifier,action):
    out=task(identifier)
    if action not in ('pause','stop'):raise ValueError('未知操作')
    (out/('PAUSE' if action=='pause' else 'STOP')).touch()
    return {'requested':action}
def approve(identifier,candidate_path,note):
    out=task(identifier)
    if running():raise ValueError('等待采集停止后再审核')
    if read(out/'status.json',{}).get('phase')!='needs_review':raise ValueError('任务没有待审核页面')
    old=load_profile(out/'profile.json');new=load_profile(candidate_path)
    for key in ('profile_id','window_title','window_class'):
        if new[key]!=old[key]:raise ValueError('不能通过审核切换到其他小程序；请新建任务')
    ledger=read(out/'reviews.json',[]);config=read(out/'task.json')
    if len(ledger)>=config['review_limit']:raise ValueError('已达到自动审核上限，需要用户处理')
    packet=read(out/'needs_review.json');shot=Path(packet['screenshot'])
    if not shot.is_absolute():shot=out/shot
    shot.resolve().relative_to(out.resolve())
    ocr=wa_ocr.read(shot,out/'ocr')
    from wa_overlays import matching,identity,locate
    overlay=matching(new,ocr)
    if overlay:
        identity(overlay,ocr);locate(overlay,shot)
    elif not recognize(new,ocr)[0]:raise ValueError('新规则仍不匹配待审核截图')
    # Preserve classification of past successful observations.
    for f in read(out/'frames.json',[]):
        if f['status']=='matched' and not recognize(new,wa_ocr.read(f['shot'],out/'ocr'))[0]:
            raise ValueError('新规则无法匹配已采集页面')
    if not note.strip():raise ValueError('请记录页面判断依据')
    old_hash=digest(json.dumps(old,sort_keys=True));new_hash=digest(json.dumps(new,sort_keys=True))
    write_json(out/'review_approval.json',{'previous_profile_hash':old_hash,'profile_hash':new_hash,'frame_hash':ocr['hash']})
    write_json(out/'profile.json',new)
    ledger.append({'time':datetime.now().isoformat(),'note':note,'frame_hash':ocr['hash'],'profile_hash':new_hash})
    write_json(out/'reviews.json',ledger);status(out,'paused',message='审核完成，可以续跑',review_count=len(ledger))
    return {'approved':True,'review_count':len(ledger)}

def main():
    import argparse,time
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['list','create','run','status','approve'])
    ap.add_argument('--id');ap.add_argument('--profile');ap.add_argument('--name');ap.add_argument('--offline');ap.add_argument('--note',default='');ap.add_argument('--preview',action='store_true');ap.add_argument('--scope',choices=['current','navigate'],default='current');ap.add_argument('--goal',default='')
    args=ap.parse_args()
    if args.action=='list':result=list_tasks()
    elif args.action=='create':result=create(args.profile,args.name,args.offline,args.goal,scope=args.scope)
    elif args.action=='status':result={'status':read(task(args.id)/'status.json'),'review':read(task(args.id)/'needs_review.json'),'directory':str(task(args.id))}
    elif args.action=='approve':result=approve(args.id,args.profile,args.note)
    else:
        start(args.id,args.preview)
        while running():time.sleep(.5)
        result={'status':read(task(args.id)/'status.json'),'directory':str(task(args.id))}
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
