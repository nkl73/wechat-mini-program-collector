import base64,io,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from test_navigation import FakeDriver,profile
from wa_navigation import Navigator
from wa_overlays import locate

def rule():
    im=Image.new('L',(24,24),255);d=ImageDraw.Draw(im);d.line((4,4,20,20),fill=0,width=3);d.line((4,20,20,4),fill=0,width=3)
    b=io.BytesIO();im.save(b,format='PNG')
    return {'id':'follow','patterns':['长按扫码关注公众号','接收重要提醒'],'region':[0,0,1,1],
        'close_region':[.5,0,1,1],'identity_region':[0,0,1,1],'identity_pattern':r'课程编号:(\d+)',
        'review_evidence':'synthetic fixture','purpose':'dismiss_only','close_template_png':base64.b64encode(b.getvalue()).decode()}

class OverlayDriver(FakeDriver):
    def __init__(self,*args,stuck=False,wrong=False,**kwargs):
        super().__init__(*args,**kwargs);self.closed=False;self.stuck=stuck;self.change=wrong
    def observe(self,index):
        s=super().observe(index)
        if self.node=='d101' and not self.closed:
            s['ocr']['lines'] += [{'text':t,'conf':.99,'box':[10,500+i*40,300,530+i*40]} for i,t in enumerate(['长按扫码关注公众号','接收重要提醒'])]
            s['ocr']['hash']='overlay'
        return s
    def act(self,kind,**kwargs):
        if kind=='dismiss':
            self.actions.append((kind,kwargs['text']));self.closed=not self.stuck
            if self.change:self.node='d102'
            return
        return super().act(kind,**kwargs)

class OverlayTests(unittest.TestCase):
    def test_pause_after_dismiss_resumes_without_second_click(self):
        class Pausing(OverlayDriver):
            def act(self,kind,**kwargs):
                super().act(kind,**kwargs)
                if kind=='dismiss':(self.out/'PAUSE').touch()
        with tempfile.TemporaryDirectory() as out:
            p=profile();p['overlays']=[rule()];d=Pausing(out);n=Navigator(p,d,out,'test')
            with patch('wa_overlays.locate',return_value=[300,300,320,320]):n.run()
            self.assertEqual(n.phase,'paused');self.assertIsNotNone(n.overlay_pending)
            (Path(out)/'PAUSE').unlink();n=Navigator(p,d,out,'test',resume=True)
            self.assertEqual(n.run(),0,n.reason);self.assertEqual(len(n.items),2)
            self.assertEqual(sum(a[0]=='dismiss' for a in d.actions),1)
    def test_preview_popup_no_click(self):
        with tempfile.TemporaryDirectory() as out:
            p=profile();p['overlays']=[rule()];d=OverlayDriver(out);d.node='d101'
            n=Navigator(p,d,out,'test');self.assertEqual(n.run(preview=True),2);self.assertEqual(d.actions,[])
    def run_case(self,**options):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        p=profile();p['overlays']=[rule()];driver=OverlayDriver(temp.name,**options)
        n=Navigator(p,driver,temp.name,'test')
        with patch('wa_overlays.locate',return_value=[300,300,320,320]):code=n.run()
        return code,n,driver
    def test_closes_before_enter_settle_and_extraction(self):
        code,n,d=self.run_case();self.assertEqual(code,0,n.reason);self.assertEqual(len(n.items),2)
        self.assertFalse(any('扫码' in item['body'] for item in n.items))
        self.assertEqual(sum(a[0]=='dismiss' for a in d.actions),1)
    def test_no_retry_when_popup_remains(self):
        code,n,d=self.run_case(stuck=True);self.assertEqual(code,2);self.assertEqual(len(n.items),0)
        self.assertEqual(sum(a[0]=='dismiss' for a in d.actions),1)
    def test_wrong_identity_after_close(self):
        code,n,d=self.run_case(wrong=True);self.assertEqual(code,2);self.assertEqual(len(n.items),0)
    def test_unknown_popup_stops_despite_matching_detail(self):
        with tempfile.TemporaryDirectory() as out:
            d=OverlayDriver(out);n=Navigator(profile(),d,out,'test');self.assertEqual(n.run(),2)
            self.assertEqual(len(n.items),0);self.assertFalse(any(a[0]=='dismiss' for a in d.actions))
    def test_template_moves_with_icon_and_rejects_two(self):
        r=rule();icon=Image.open(io.BytesIO(base64.b64decode(r['close_template_png'])))
        with tempfile.TemporaryDirectory() as out:
            shot=Path(out)/'shot.png';im=Image.new('L',(400,700),255);im.paste(icon,(330,400));im.save(shot)
            box=locate(r,shot);self.assertAlmostEqual((box[0]+box[2])/2,342,delta=2)
            im.paste(icon,(250,200));im.save(shot)
            with self.assertRaises(ValueError):locate(r,shot)

if __name__=='__main__':unittest.main()
