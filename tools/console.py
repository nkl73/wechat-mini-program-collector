"""Loopback-only control panel, authenticated by per-launch bearer token."""
import json,mimetypes,secrets,webbrowser
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs,unquote
from pathlib import Path
import task_service as svc
TOKEN=secrets.token_urlsafe(32)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,data,code=200,ctype='application/json; charset=utf-8'):
        body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def authorized(self):
        return self.headers.get('X-Token')==TOKEN or ('mini_session='+TOKEN) in self.headers.get('Cookie','').split('; ')
    def do_GET(self):
        parsed=urlsplit(self.path)
        if parsed.path=='/' and (parse_qs(parsed.query).get('token')==[TOKEN] or self.authorized()):
            body=(svc.TOOLS/'console.html').read_text(encoding='utf-8').replace('__SESSION_TOKEN__',TOKEN).encode('utf-8');self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Set-Cookie',f'mini_session={TOKEN}; HttpOnly; SameSite=Strict; Path=/')
            self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(body);return
        if not self.authorized():self.send({'error':'未授权'},403);return
        try:
            if parsed.path=='/api':
                profiles=[{'path':str(p),'name':svc.load_profile(p)['window_title']} for p in sorted((svc.TOOLS/'profiles').glob('*.json'))]
                self.send({'profiles':profiles,'tasks':svc.list_tasks()});return
            if parsed.path.startswith('/result/'):
                parts=unquote(parsed.path).split('/');root=svc.task(parts[2]);target=(root/('/'.join(parts[3:]) or 'index.html')).resolve();target.relative_to(root.resolve())
                if target.suffix.lower() not in ('.html','.png','.json','.csv','.md'):raise ValueError('不支持的文件类型')
                self.send(target.read_bytes(),ctype=mimetypes.guess_type(str(target))[0] or 'application/octet-stream');return
            self.send({'error':'找不到页面'},404)
        except Exception as e:self.send({'error':str(e)},400)
    def do_POST(self):
        # Require the non-simple header; cookies alone cannot mutate local state.
        if self.headers.get('X-Token')!=TOKEN:self.send({'error':'未授权'},403);return
        try:
            n=int(self.headers.get('Content-Length',0))
            if not 0<n<65536:raise ValueError('请求大小无效')
            data=json.loads(self.rfile.read(n));action=data['action']
            if action=='create':result=svc.create(data['profile'],data['name'],data.get('offline'),data.get('goal',''),scope=data.get('scope','current'))
            elif action in ('preview','continue'):result=svc.start(data['id'],action=='preview')
            elif action in ('pause','stop'):result=svc.control(data['id'],action)
            elif action=='repeat':
                old=svc.read(svc.task(data['id'])/'task.json');result=svc.create(svc.task(data['id'])/'profile.json',old['collection'],old['offline'],old.get('goal',''),old['limit'],old.get('scope','current'))
            else:raise ValueError('未知操作')
            self.send(result)
        except Exception as e:self.send({'error':str(e)},400)
def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}/?token={TOKEN}'
    print('本地采集控制台已启动。关闭此窗口将关闭控制台；运行中的采集进程仍会继续。',flush=True)
    webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
