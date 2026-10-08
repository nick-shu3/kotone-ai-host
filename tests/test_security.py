"""Offline regression tests. No real API requests, credentials or public services."""
import importlib.util
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kotone_server_under_test', ROOT/'server.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.oldroot = s.ROOT
        s.ROOT = Path(self.temp.name)
        for name in ('index.html', 'studio.js'):
            (s.ROOT/name).write_bytes((ROOT/name).read_bytes())
        s.JOBS.clear()
        s.CALL_COUNT = 0
        s.API_KEY = 'AUDIT_DUMMY_NOT_A_REAL_KEY'
        s.BOOTSTRAP = 'AUDIT_DUMMY_LAUNCH_CAPABILITY'
        s.BOOTSTRAP_CREATED = time.monotonic()
        self.server = s.LocalServer(('127.0.0.1', 0), s.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        s.ROOT = self.oldroot
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        h = dict(headers or {})
        if method == 'POST':
            h.setdefault('Content-Type', 'application/json')
            h.setdefault('Origin', self.origin)
        body = None if data is None else json.dumps(data)
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        result = r.status, dict(r.getheaders()), r.read()
        c.close()
        return result

    def media_job(self):
        jid = '1'*32
        folder = s.prepare_job_folder(jid)
        (folder/'script.txt').write_text('AUDIT_SENTINEL')
        s.JOBS[jid] = {'folder': folder}
        return jid, folder

    def test_original_memory_bomb_rejected(self):
        with self.assertRaises(s.UserError):
            s.video.validate({'script':'a', 'readings':('a='+'a'*80+'\n')*5})

    def test_different_words_cannot_cascade(self):
        dictionary = '\n'.join(a+'='+b*80 for a,b in zip('abcde','bcdef'))
        with self.assertRaises(s.UserError):
            s.video.validate({'script':'a','readings':dictionary})

    def test_normal_dictionary_and_caption(self):
        r = s.video.validate({'script':'FGOの★4を紹介します。','readings':'FGO=エフジーオー\n★4=ほしよん'})
        self.assertEqual(r['spoken'], ['エフジーオーのほしよんを紹介します。'])
        for text in s.video.split_script('あ'*1200):
            self.assertLessEqual(len(text), 64)
            self.assertLessEqual(len(s.video.format_caption(text).splitlines()), 2)

    def test_speed_error_does_not_echo_input(self):
        secretish = 'AUDIT_PRIVATE_MARKER'
        with self.assertRaises(s.UserError) as e:
            s.video.validate({'script':'テスト。','speed':secretish})
        self.assertNotIn(secretish, str(e.exception))

    def test_root_and_rejection_do_not_disclose_capabilities(self):
        for headers in ({}, {'Host':'evil.example'}):
            status, h, body = self.request('GET','/',headers=headers)
            self.assertNotIn(s.TOKEN, h.get('Content-Security-Policy',''))
            self.assertNotIn(s.TOKEN.encode(), body)
            self.assertNotIn(s.BOOTSTRAP.encode(), body)
        a = self.request('GET','/')[1]['Content-Security-Policy']
        b = self.request('GET','/')[1]['Content-Security-Policy']
        self.assertNotEqual(a,b)

    def test_bootstrap_requires_secret(self):
        self.assertEqual(self.request('POST','/api/session',{}, {'X-Bootstrap':'wrong'})[0],403)
        self.assertEqual(self.request('POST','/api/session',{})[0],403)

    def test_bootstrap_once(self):
        h = {'X-Bootstrap':s.BOOTSTRAP}
        status, _, body = self.request('POST','/api/session',{},h)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['session'],s.TOKEN)
        self.assertEqual(self.request('POST','/api/session',{},h)[0],403)

    def test_bootstrap_expiry(self):
        s.BOOTSTRAP_CREATED -= 121
        self.assertEqual(self.request('POST','/api/session',{}, {'X-Bootstrap':s.BOOTSTRAP})[0],403)

    def test_origin_and_session_checks(self):
        for h in ({}, {'X-Session':'wrong'}, {'X-Session':s.TOKEN,'Origin':'https://evil.example'},
                  {'X-Session':s.TOKEN,'Host':'evil.example'}):
            self.assertEqual(self.request('POST','/api/talk',{},h)[0],403)
        self.assertEqual(self.request('GET','/api/capabilities')[0],403)

    def test_duplicate_host_rejected(self):
        c = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        c.putrequest('GET','/',skip_host=True)
        host = '127.0.0.1:'+str(self.server.server_port)
        c.putheader('Host',host); c.putheader('Host',host); c.endheaders()
        r=c.getresponse();self.assertEqual(r.status,403);r.read();c.close()

    def test_duplicate_length_rejected(self):
        c = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        c.putrequest('POST','/api/talk')
        for key,value in [('Origin',self.origin),('X-Session',s.TOKEN),('Content-Type','application/json'),
                          ('Content-Length','2'),('Content-Length','2')]: c.putheader(key,value)
        c.endheaders(b'{}')
        r=c.getresponse();self.assertEqual(r.status,400);r.read();c.close()

    def test_invalid_json_is_generic(self):
        c = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        c.request('POST','/api/talk',body='{"AUDIT_PRIVATE_MARKER":',
                  headers={'Origin':self.origin,'X-Session':s.TOKEN,'Content-Type':'application/json'})
        r=c.getresponse();self.assertEqual(r.status,400)
        self.assertNotIn(b'AUDIT_PRIVATE_MARKER',r.read());c.close()

    def test_media_auth_allowlist_and_traversal(self):
        jid, _ = self.media_job()
        base='/media/'+jid+'/'
        self.assertEqual(self.request('GET',base+'script.txt')[0],403)
        h={'X-Session':s.TOKEN}
        self.assertEqual(self.request('GET',base+'script.txt',headers=h)[2],b'AUDIT_SENTINEL')
        for name in ('meta.json','../server.py','%2e%2e%2fserver.py','render.log'):
            self.assertEqual(self.request('GET',base+name,headers=h)[0],404)
        self.assertEqual(self.request('GET','/media/'+'2'*32+'/script.txt',headers=h)[0],404)

    def test_media_range(self):
        jid,_=self.media_job()
        status,_,body=self.request('GET','/media/'+jid+'/script.txt',headers={'X-Session':s.TOKEN,'Range':'bytes=0-4'})
        self.assertEqual(status,206);self.assertEqual(body,b'AUDIT')
        self.assertEqual(self.request('GET','/media/'+jid+'/script.txt',
            headers={'X-Session':s.TOKEN,'Range':'bytes='+'9'*100+'-'})[0],416)

    def test_media_symlink_rejected(self):
        jid, folder=self.media_job()
        target=s.ROOT/'private.txt';target.write_text('AUDIT_PRIVATE_MARKER')
        path=folder/'script.txt';path.unlink()
        try:path.symlink_to(target)
        except OSError:self.skipTest('OS does not permit test symlinks')
        self.assertEqual(self.request('GET','/media/'+jid+'/script.txt',headers={'X-Session':s.TOKEN})[0],404)

    def test_media_hardlink_rejected(self):
        jid,folder=self.media_job()
        target=s.ROOT/'private.txt';target.write_text('AUDIT_PRIVATE_MARKER')
        path=folder/'script.txt';path.unlink()
        try:os.link(target,path)
        except OSError:self.skipTest('OS does not permit hardlinks')
        self.assertEqual(self.request('GET','/media/'+jid+'/script.txt',headers={'X-Session':s.TOKEN})[0],404)

    def test_output_directory_link_rejected(self):
        target=s.ROOT/'external';target.mkdir()
        try:(s.ROOT/'output').symlink_to(target,target_is_directory=True)
        except OSError:self.skipTest('OS does not permit test symlinks')
        with self.assertRaises(s.UserError):s.prepare_job_folder('3'*32)

    def test_missing_avatar_uses_original_fallback(self):
        status,headers,body=self.request('GET','/presenter.png')
        self.assertEqual(status,200)
        self.assertEqual(headers['Content-Type'],'image/png')
        self.assertTrue(body.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertNotIn(b'caBX',body)

    def test_slots_bounded_and_recover(self):
        connections=[socket.create_connection(('127.0.0.1',self.server.server_port),timeout=2) for _ in range(16)]
        deadline=time.monotonic()+1
        while self.server.slots._value>0 and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.server.slots._value,0)
        for connection in connections:connection.close()
        deadline=time.monotonic()+2
        while self.server.slots._value<8 and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.server.slots._value,8)
        self.assertEqual(self.request('GET','/')[0],200)

    def test_lan_bind_rejected(self):
        with self.assertRaises(s.UserError):s.LocalServer(('0.0.0.0',0),s.Handler)

    def test_call_limit(self):
        s.CALL_COUNT=29
        s.count_call();self.assertEqual(s.CALL_COUNT,30)
        with self.assertRaises(s.UserError):s.count_call()
        self.assertEqual(s.CALL_COUNT,30)

    def test_child_environment_contains_no_secrets(self):
        with mock.patch.dict(os.environ,{'OPENAI_API_KEY':'AUDIT_PRIVATE_MARKER',
              'OTHER_SECRET':'AUDIT_PRIVATE_MARKER','HTTP_PROXY':'AUDIT_PRIVATE_MARKER'}):
            env=s.video.safe_child_environment()
        self.assertNotIn('OPENAI_API_KEY',env);self.assertNotIn('OTHER_SECRET',env)
        self.assertNotIn('HTTP_PROXY',env)

    def test_authenticated_talk_without_external_call(self):
        with mock.patch.object(s,'generate',return_value='コトネです。'):
            status,_,body=self.request('POST','/api/talk',{'action':'intro','article':'テスト記事。'},
                                     {'X-Session':s.TOKEN})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['text'],'コトネです。')
        self.assertEqual(s.CALL_COUNT,1)

    def test_auth_missing_origin(self):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        c.request('POST','/api/talk',body='{}',headers={'X-Session':s.TOKEN,'Content-Type':'application/json'})
        r=c.getresponse();self.assertEqual(r.status,403);r.read();c.close()

    def test_server_header_and_default_errors_hide_runtime(self):
        for method, path in [('GET','/'),('HEAD','/'),('PATCH','/')]:
            status, headers, body = self.request(method, path)
            self.assertNotIn('Server',headers)
            self.assertNotIn(b'Python/',body)
            self.assertNotIn(b'BaseHTTP',body)

    def test_render_low_capacity_rejected_before_start(self):
        jid, folder = self.media_job()
        s.JOBS[jid].update(id=jid,status='audio_ready',cancel=threading.Event(),meta={})
        with mock.patch.object(s.video,'dependencies',return_value='AUDIT_FAKE_BINARY'), \
                mock.patch.object(s,'check_capacity',side_effect=s.UserError('AUDIT_FULL')):
            status,_,body=self.request('POST','/api/render',{'job':jid},{'X-Session':s.TOKEN})
        self.assertEqual(status,400)
        self.assertEqual(s.JOBS[jid]['status'],'audio_ready')
        self.assertTrue(s.CALL_LOCK.acquire(blocking=False));s.CALL_LOCK.release()

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux anchored descriptor test')
    def test_parent_swap_does_not_redirect_media(self):
        jid, folder = self.media_job()
        outside=s.ROOT/'private';outside.mkdir()
        (outside/'script.txt').write_text('AUDIT_PRIVATE_MARKER')
        real_open=os.open
        swapped=False
        def swap_then_open(path,*args,**kwargs):
            nonlocal swapped
            if str(path).startswith('/proc/self/fd/') and str(path).endswith('/script.txt'):
                folder.rename(folder.with_name('saved'))
                folder.symlink_to(outside,target_is_directory=True)
                swapped=True
            return real_open(path,*args,**kwargs)
        with mock.patch.object(os,'open',side_effect=swap_then_open):
            with s.open_job_media(folder,'script.txt') as file:
                self.assertEqual(file.read(),b'AUDIT_SENTINEL')
        self.assertTrue(swapped)
        self.assertEqual(self.request('GET','/media/'+jid+'/script.txt',headers={'X-Session':s.TOKEN})[0],404)

    @unittest.skipUnless(hasattr(os,'mkfifo'),'FIFO test')
    def test_media_fifo_rejected_without_blocking(self):
        jid,folder=self.media_job()
        (folder/'script.txt').unlink();os.mkfifo(folder/'script.txt')
        self.assertEqual(self.request('GET','/media/'+jid+'/script.txt',headers={'X-Session':s.TOKEN})[0],404)

    def test_response_deadline_survives_get(self):
        original=s.Handler.REQUEST_SECONDS
        s.Handler.REQUEST_SECONDS=.15
        try:
            # A simulated blocked sender must be interrupted by the connection deadline.
            with mock.patch.object(s.Handler,'send',lambda h,*a,**k: time.sleep(.4)):
                connection=socket.create_connection(('127.0.0.1',self.server.server_port),timeout=2)
                connection.sendall(('GET / HTTP/1.1\r\nHost: 127.0.0.1:'+str(self.server.server_port)+'\r\n\r\n').encode())
                self.assertEqual(connection.recv(1),b'')
                connection.close()
        finally:
            s.Handler.REQUEST_SECONDS=original

    @unittest.skipUnless(os.name=='nt','Windows directory share-delete protection')
    def test_windows_parent_rename_blocked(self):
        jid,folder=self.media_job()
        with s.video.storage.directory(s.ROOT,folder):
            with self.assertRaises(OSError):folder.rename(folder.with_name('swapped'))

    def test_render_capacity_failure_cleans_temp_preserves_final(self):
        import wave
        import io
        jid,folder=self.media_job()
        with wave.open(str(folder/'audio.wav'),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000)
            wav.writeframes(b'\0\0'*2400)
        (folder/'video.mp4').write_bytes(b'AUDIT_OLD_VIDEO')
        class FakeProcess:
            def __init__(self,*args,**kwargs):
                self.stdin=io.BytesIO();self.code=None
                (folder/'rendering.mp4').write_bytes(b'AUDIT_PARTIAL_VIDEO')
            def poll(self):return self.code
            def kill(self):self.code=-1
            def wait(self,**kwargs):return self.code or 0
        def capacity():
            if (folder/'rendering.mp4').exists():raise s.UserError('AUDIT_FULL')
        with mock.patch.object(s.video.subprocess,'Popen',FakeProcess):
            with self.assertRaises(s.UserError):
                s.video.render(folder,{'title':'test','cues':[]},lambda *a:None,
                               threading.Event(),binary='AUDIT_FAKE_BINARY',check_capacity=capacity)
        self.assertFalse((folder/'rendering.mp4').exists())
        self.assertEqual((folder/'video.mp4').read_bytes(),b'AUDIT_OLD_VIDEO')
        self.assertTrue((folder/'audio.wav').exists())

    def test_placeholder_composition_two_states(self):
        self.assertEqual(s.video.placeholder_sheet().size,(1774,887))
        original=s.video.ROOT;s.video.ROOT=s.ROOT
        try:
            (s.ROOT/'NotoSansCJKjp-Regular.otf').write_bytes((ROOT/'NotoSansCJKjp-Regular.otf').read_bytes())
            for state in (0,1):
                frame=s.video.compose('FGOの紹介','最大2行のテロップです。',state)
                self.assertEqual(frame.size,(1280,720))
        finally:s.video.ROOT=original

    def test_public_pack_excludes_private_files(self):
        spec=importlib.util.spec_from_file_location('public_builder',ROOT/'build_public_release.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        builder.ROOT=s.ROOT
        for relative in builder.ALLOWLIST:
            path=s.ROOT/relative;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((ROOT/relative).read_bytes())
        private_marker='AUDIT_'+s.secrets.token_hex(16)
        (s.ROOT/'presenter.png').write_bytes(b'AUDIT_PRIVATE_IMAGE')
        (s.ROOT/'.env').write_text(private_marker)
        (s.ROOT/'output').mkdir();(s.ROOT/'output'/'script.txt').write_text(private_marker)
        (s.ROOT/'runtime').mkdir();(s.ROOT/'runtime'/'ffmpeg.exe').write_bytes(b'AUDIT_BINARY')
        (s.ROOT/'WINDOWS_CHECK_RESULT.json').write_text('AUDIT_LOCAL_RESULT')
        destination=s.ROOT/'public.zip';builder.build(destination)
        import zipfile,hashlib
        with zipfile.ZipFile(destination) as archive:
            names=archive.namelist()
            self.assertIn('kotone-ai-host/LICENSE',names)
            for name in names:
                self.assertNotIn('presenter.png',name)
                self.assertNotIn('output/',name);self.assertNotIn('runtime/',name)
                self.assertNotIn('.env',name);self.assertNotIn('WINDOWS_CHECK_RESULT',name)
                self.assertNotIn(private_marker.encode(),archive.read(name))
            for line in archive.read('kotone-ai-host/SHA256SUMS.txt').decode().splitlines():
                digest,name=line.split('  ',1)
                self.assertEqual(hashlib.sha256(archive.read('kotone-ai-host/'+name)).hexdigest(),digest)
        with self.assertRaises(FileExistsError):builder.build(destination)

    def test_public_builder_refuses_secret_and_symlink(self):
        spec=importlib.util.spec_from_file_location('public_builder_2',ROOT/'build_public_release.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        builder.ROOT=s.ROOT;builder.ALLOWLIST=('example.txt',)
        (s.ROOT/'example.txt').write_text('sk-proj-'+'A'*30)
        with self.assertRaises(ValueError):builder.build(s.ROOT/'public.zip')
        self.assertFalse((s.ROOT/'public.zip').exists())
        (s.ROOT/'example.txt').unlink()
        try:(s.ROOT/'example.txt').symlink_to(ROOT/'README.md')
        except OSError:self.skipTest('test symlinks unavailable')
        with self.assertRaises(ValueError):builder.build(s.ROOT/'public.zip')

    def test_native_installer_rejects_bad_archive_and_paths(self):
        import io,hashlib,zipfile
        spec=importlib.util.spec_from_file_location('native_installer',ROOT/'install_ffmpeg.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        memory=io.BytesIO()
        with zipfile.ZipFile(memory,'w') as archive:archive.writestr('bad','bad')
        data=memory.getvalue()
        manifest={'max_download_bytes':1024*1024,'archive_sha256':'0'*64,'files':[]}
        with self.assertRaises(installer.UserError):installer.install_archive(io.BytesIO(data),manifest,s.ROOT)
        manifest['archive_sha256']=hashlib.sha256(data).hexdigest()
        manifest['files']=[{'name':'../escape'}]*3
        with self.assertRaises(installer.UserError):installer.install_archive(io.BytesIO(data),manifest,s.ROOT)
        self.assertFalse((s.ROOT.parent/'escape').exists())

    def test_native_member_failure_preserves_old_executable(self):
        import io,hashlib,zipfile
        spec=importlib.util.spec_from_file_location('native_installer_member',ROOT/'install_ffmpeg.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        memory=io.BytesIO();entries=[]
        with zipfile.ZipFile(memory,'w') as archive:
            for name in ('ffmpeg.exe','FFMPEG-LICENSE.txt','FFMPEG-README.txt'):
                data=('AUDIT_'+name).encode();member='bundle/'+name
                archive.writestr(member,data)
                entries.append({'member':member,'name':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            archive.writestr('../not-selected.txt',b'AUDIT_EXTRA')
        data=memory.getvalue()
        manifest={'max_download_bytes':1024*1024,'archive_sha256':hashlib.sha256(data).hexdigest(),'files':entries}
        (s.ROOT/'ffmpeg.exe').write_bytes(b'AUDIT_OLD_EXECUTABLE')
        entries[1]['sha256']='0'*64
        with self.assertRaises(installer.UserError):installer.install_archive(io.BytesIO(data),manifest,s.ROOT)
        self.assertEqual((s.ROOT/'ffmpeg.exe').read_bytes(),b'AUDIT_OLD_EXECUTABLE')
        self.assertFalse(list(s.ROOT.glob('.install-*')))
        entries[1]['sha256']=hashlib.sha256(b'AUDIT_FFMPEG-LICENSE.txt').hexdigest()
        installer.install_archive(io.BytesIO(data),manifest,s.ROOT)
        self.assertEqual((s.ROOT/'ffmpeg.exe').read_bytes(),b'AUDIT_ffmpeg.exe')
        self.assertFalse((s.ROOT.parent/'not-selected.txt').exists())

    def test_low_disk_rejected(self):
        with mock.patch.object(s.shutil,'disk_usage',return_value=(1,1,1)):
            # disk_usage returns a named tuple in production
            class Disk:free=1
            with mock.patch.object(s.shutil,'disk_usage',return_value=Disk()):
                with self.assertRaises(s.UserError):s.prepare_job_folder('4'*32)

if __name__ == '__main__':
    unittest.main(verbosity=2)
