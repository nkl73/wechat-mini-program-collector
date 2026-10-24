"""Live entry point for reviewed navigation profiles."""
import argparse,json
from pathlib import Path
from wa_engine import load_profile
from wa_navigation import Navigator,LiveDriver
from wa_experience import status,write_json

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--profile',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--collection',required=True);ap.add_argument('--resume',action='store_true');ap.add_argument('--preview',action='store_true')
    ap.add_argument('--max-seconds',type=float,default=240);args=ap.parse_args()
    profile=load_profile(args.profile);out=Path(args.out);out.mkdir(exist_ok=True,parents=True)
    if (out/'STOP').exists() or (out/'PAUSE').exists():return 0
    import guard,wa_core
    try:
        candidates=guard.find_candidates(profile['window_class'],profile['window_title'])
        if len(candidates)!=1:raise ValueError('请保持一个目标小程序窗口打开且未最小化')
        core=wa_core.Core(candidates[0]['hwnd'])
        if not core.focus_once():raise ValueError('无法置前目标窗口')
        if not profile.get('navigation',{}).get('enabled'):
            driver=LiveDriver(core,out);observed=driver.observe(0)
            from collector import outputs
            outputs(out,[],[{'shot':observed['shot'],'hash':observed['ocr']['hash'],'status':'needs_review'}],'尚未校准此页面的导航入口')
            write_json(out/'needs_review.json',{'reason':'需要 Agent 校准只读导航入口、目标页识别、条目标识和返回方式','screenshot':observed['shot'],'ocr':observed['ocr'],'collection':args.collection,'last_action':'capture'})
            from wa_engine import digest
            write_json(out/'state.json',{'profile_id':profile['profile_id'],'profile_hash':digest(json.dumps(profile,sort_keys=True)),'collection':args.collection,'last_frame':observed['ocr']['hash']})
            status(out,'needs_review',items=0,frames=1,message='尚未校准导航：已保存当前页，请 Agent 判断入口')
            return 2
        nav=profile['navigation']
        runner=Navigator(profile,LiveDriver(core,out),out,args.collection,nav['max_actions'],args.max_seconds,nav['max_depth'],args.resume)
        return runner.run(args.preview)
    except Exception as e:
        status(out,'error',message=str(e));(out/'error.txt').write_text(str(e),encoding='utf-8');return 3
if __name__=='__main__':raise SystemExit(main())
