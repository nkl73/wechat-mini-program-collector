"""Deterministic navigation tests; fake UI/OCR, no real desktop interaction."""
import copy,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from PIL import Image
from wa_navigation import Navigator
from wa_engine import digest,load_profile

def profile():
    base={'profile_id':'test_courses','window_title':'test','window_class':'test','identity_texts':['课程中心'],'scroll_notches':-2,'scroll_at':[.5,.6],
          'navigation':{'enabled':True,'max_depth':5,'max_actions':50,'max_scrolls_per_page':3}}
    def page(id,kind,pattern,capture=True):return {'id':id,'kind':kind,'region':[0,.1,1,.95],'required_patterns':[pattern],
        'reject_patterns':[],'fields':[{'name':'title','pattern':r'标题:(.+)'}],'allow_scroll':False,'capture':capture}
    root=page('menu','menu','全部栏目',False);listing=page('list','list','课程目录',False)
    listing.update(item_start=r'课程 (\d+)',min_items=1)
    detail=page('detail','detail',r'课程编号:\d+')
    root['routes']=[{'id':'category','selector':'课程分类','region':[0,.1,1,.9],'target_page':'list','relation':'child','mode':'once','purpose':'read_only',
        'review_evidence':'Synthetic fixture: opens category without account mutation','return_control':{'type':'text','text':'返回'}}]
    listing['routes']=[{'id':'item','selector':r'课程 (\d+)','region':[0,.1,1,.9],'target_page':'detail','relation':'child','mode':'each','purpose':'read_only',
        'review_evidence':'Synthetic fixture: opens detail','target_key_pattern':r'课程编号:(\d+)','target_key_region':[0,.1,1,.25],'return_control':{'type':'text','text':'返回'}}]
    detail['routes']=[{'id':'expand','selector':'展开介绍','region':[0,.1,1,.9],'target_page':'detail','relation':'expand','mode':'once','purpose':'read_only',
        'review_evidence':'Synthetic fixture: expands text only','verify_pattern':'完整介绍'}]
    base['pages']=[root,listing,detail];return base

class FakeDriver:
    def __init__(self,out,wrong=False,pause=False,danger=False):
        self.out=Path(out);self.node='root';self.actions=[];self.wrong=wrong;self.pause=pause;self.danger=danger
    def observe(self,index):
        content={'root':['全部栏目','课程分类'], 'list':['课程目录','返回','课程 101','课程 102'],
            'd101':['课程编号:101','标题:第一课','展开介绍','返回'],
            'd101x':['课程编号:101','标题:第一课','完整介绍','返回'],
            'd102':['课程编号:102','标题:第二课','返回']}[self.node]
        if self.danger and self.node=='root':content=['全部栏目','绑定学校']
        lines=[{'text':'课程中心','conf':.99,'box':[5,5,100,25]}]
        for i,text in enumerate(content):lines.append({'text':text,'conf':.99,'box':[20,100+i*65,220,130+i*65]})
        shot=self.out/'evidence'/f'{index}.png';shot.parent.mkdir(exist_ok=True)
        Image.new('RGB',(400,700),'white').save(shot)
        return {'shot':str(shot),'ocr':{'size':[400,700],'lines':lines,'hash':digest(self.node)}}
    def act(self,kind,**kw):
        text=kw.get('text');self.actions.append((kind,text))
        if kind=='back':self.node='list' if self.node.startswith('d') else 'root'
        elif text=='课程分类':self.node='list'
        elif text=='课程 101':self.node='d102' if self.wrong else 'd101'
        elif text=='课程 102':self.node='d102'
        elif text=='展开介绍':self.node='d101x'
        else:raise AssertionError((kind,text))
        if self.pause:self.pause=False;(self.out/'PAUSE').touch()

class NavigationTests(unittest.TestCase):
    def test_atomic_checkpoint_retries_transient_windows_lock(self):
        from unittest.mock import patch
        from wa_experience import write_json
        original=Path.replace;calls=[]
        def sometimes(path,target):
            calls.append(1)
            if len(calls)<=2:raise PermissionError('temporary reader lock')
            return original(path,target)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'checkpoint.json'
            with patch.object(Path,'replace',sometimes):write_json(p,{'saved':True})
            self.assertEqual(json.loads(p.read_text()),{'saved':True});self.assertEqual(len(calls),3)
    def test_changed_screen_before_input_does_not_replay_pending_click(self):
        from wa_navigation import BeforeInputChanged
        class Changed(FakeDriver):
            def act(self,kind,**kwargs):raise BeforeInputChanged(self.observe(500))
        with tempfile.TemporaryDirectory() as d:
            driver=Changed(d);n=Navigator(profile(),driver,d,'test');self.assertEqual(n.run(),2)
            self.assertIsNone(n.pending);self.assertEqual(driver.actions,[])
    def test_unknown_detail_review_then_resume_does_not_reclick(self):
        with tempfile.TemporaryDirectory() as d:
            p=profile();p['pages'][2]['required_patterns']=['UNKNOWN_UNTIL_INSPECTED']
            driver=FakeDriver(d);n=Navigator(p,driver,d,'test');self.assertEqual(n.run(),2)
            from wa_experience import write_json
            fixed=profile()
            write_json(Path(d)/'review_approval.json',{'previous_profile_hash':digest(json.dumps(p,sort_keys=True)),
                'profile_hash':digest(json.dumps(fixed,sort_keys=True)),'frame_hash':digest('d101')})
            n2=Navigator(fixed,driver,d,'test',resume=True);self.assertEqual(n2.run(),0)
            self.assertEqual(driver.actions.count(('click','课程 101')),1);self.assertEqual(len(n2.items),2)
    def test_return_to_wrong_position_stops(self):
        class MovedDriver(FakeDriver):
            def act(self,kind,**kwargs):
                super().act(kind,**kwargs)
                if kind=='back' and self.node=='list':self.node='root'
        with tempfile.TemporaryDirectory() as d:
            driver=MovedDriver(d);n=Navigator(profile(),driver,d,'test');self.assertEqual(n.run(),2)
            self.assertIn('返回后',n.reason);self.assertNotIn(('click','课程 102'),driver.actions)
    def test_list_scrolls_after_returning_from_multiple_details(self):
        class PagedDriver(FakeDriver):
            def observe(self,index):
                snapshot=super().observe(index)
                if self.node=='list' and getattr(self,'next_page',False):
                    snapshot['ocr']['lines']=[x for x in snapshot['ocr']['lines'] if x['text']!='课程 102']
                    for line in snapshot['ocr']['lines']:
                        if line['text']=='课程 101':line['text']='课程 103'
                    snapshot['ocr']['hash']=digest('list2')
                if self.node=='d102' and getattr(self,'third_detail',False):
                    for line in snapshot['ocr']['lines']:
                        if line['text']=='课程编号:102':line['text']='课程编号:103'
                        if line['text']=='标题:第二课':line['text']='标题:第三课'
                    snapshot['ocr']['hash']=digest('d103')
                return snapshot
            def act(self,kind,**kwargs):
                if kind=='scroll':self.actions.append(('scroll',None));self.next_page=True;return
                if kwargs.get('text')=='课程 103':self.actions.append(('click','课程 103'));self.node='d102';self.third_detail=True;return
                super().act(kind,**kwargs)
        with tempfile.TemporaryDirectory() as d:
            p=profile();p['pages'][1]['allow_scroll']=True
            driver=PagedDriver(d);n=Navigator(p,driver,d,'test');result=n.run();self.assertEqual(result,0,n.reason)
            self.assertIn(('click','课程 103'),driver.actions);self.assertEqual(len(n.items),3)
    def test_schema_and_nested_flow(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'profile.json';p.write_text(json.dumps(profile()),encoding='utf-8');load_profile(p)
            driver=FakeDriver(d);n=Navigator(profile(),driver,d,'test');self.assertEqual(n.run(),0)
            self.assertEqual(driver.node,'root');self.assertEqual(len(n.items),2)
            self.assertIn('完整介绍',n.items[0]['body']);self.assertEqual(len(n.visited),4)
            self.assertEqual(driver.actions.count(('click','课程 101')),1)
            self.assertEqual(driver.actions.count(('click','课程 102')),1)
            self.assertTrue((Path(d)/'index.html').exists())
    def test_wrong_detail_stops_before_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            driver=FakeDriver(d,wrong=True);n=Navigator(profile(),driver,d,'test');self.assertEqual(n.run(),2)
            self.assertEqual(len(n.items),0);self.assertIn('详情标识',n.reason)
            self.assertNotIn(('back','返回'),driver.actions)
    def test_pause_after_click_resumes_without_reclick(self):
        with tempfile.TemporaryDirectory() as d:
            driver=FakeDriver(d,pause=True);n=Navigator(profile(),driver,d,'test');n.run();self.assertEqual(n.phase,'paused')
            (Path(d)/'PAUSE').unlink();n2=Navigator(profile(),driver,d,'test',resume=True);self.assertEqual(n2.run(),0)
            self.assertEqual(driver.actions.count(('click','课程分类')),1)
            self.assertEqual(len(n2.items),2)
    def test_risky_selected_text_never_clicked(self):
        with tempfile.TemporaryDirectory() as d:
            p=profile();p['pages'][0]['routes'][0]['selector']='绑定学校'
            driver=FakeDriver(d,danger=True);n=Navigator(p,driver,d,'test');self.assertEqual(n.run(),2)
            self.assertEqual(driver.actions,[])
    def test_preview_never_clicks(self):
        with tempfile.TemporaryDirectory() as d:
            driver=FakeDriver(d);n=Navigator(profile(),driver,d,'test');n.run(preview=True)
            self.assertEqual(n.phase,'preview');self.assertEqual(driver.actions,[])
    def test_action_budget_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            driver=FakeDriver(d);n=Navigator(profile(),driver,d,'test',max_actions=1);n.run()
            self.assertEqual(len(driver.actions),1);self.assertIsNone(n.pending)

if __name__=='__main__':unittest.main()
