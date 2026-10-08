"""Offline Windows verification. No credentials or real API calls required."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parent


def run():
    if os.name != 'nt' or sys.maxsize <= 2**32:
        raise ValueError('この確認はWindows 64bit実機で実行してください。')
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise ValueError('通常の権限で実行してください。')
    spec = importlib.util.spec_from_file_location('kotone_windows_check', ROOT/'server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    binary = server.video.dependencies()
    env = server.video.safe_child_environment()
    version = subprocess.run([binary, '-version'], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env, timeout=15, check=True).stdout.splitlines()[0].decode('utf-8','replace')
    if not version.startswith('ffmpeg version 9.0.2'):
        raise ValueError('動画変換部品のバージョンが一致しません。')
    suite = subprocess.run([sys.executable, '-I', '-B', str(ROOT/'tests/test_security.py')],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, timeout=120)
    if suite.returncode:
        raise ValueError('回帰テストが失敗しました。公開を保留してください。')
    with tempfile.TemporaryDirectory(prefix='kotone-check-') as temporary:
        server.ROOT = Path(temporary)
        folder = server.prepare_job_folder('a'*32)
        settings = server.video.validate({'script':'こんにちは。コトネです。★4を紹介します。',
            'title':'Windows動作確認', 'readings':'★4=ほしよん', 'voice':'marin'})
        with server.video.storage.directory(server.ROOT, folder) as (anchored, inherited):
            server.video.storage.make_private(anchored)
            # Local synthetic PCM only. No OpenAI request or API key.
            meta = server.video.synthesize(settings, anchored, lambda payload:b'\0\0'*12000,
                lambda *args:None, threading.Event())
            server.video.render(anchored,meta,lambda *args:None,threading.Event(),
                check_capacity=server.check_capacity,pass_fds=inherited)
            decode = subprocess.run([binary,'-v','error','-i',str(anchored/'video.mp4'),
                '-f','null','-'], stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                env=env,timeout=30)
            if decode.returncode or not (anchored/'thumbnail.png').is_file():
                raise ValueError('動画またはサムネイルの確認に失敗しました。')
            if any(len(cue['text'].splitlines())>2 for cue in meta['cues']):
                raise ValueError('字幕の確認に失敗しました。')
            with server.open_job_media(folder,'video.mp4') as file:
                if len(file.read()) <= 0:raise ValueError('生成物の取得を確認できませんでした。')
    manifest = json.loads((ROOT/'native-runtime.json').read_text(encoding='utf-8'))
    return {'version':(ROOT/'VERSION').read_text().strip(),'status':'PASS',
            'scope':'local Windows offline implementation tests; not independent certification',
            'ffmpeg_version':manifest['version'],'ffmpeg_sha256':manifest['binary_sha256'],
            'checks':['regression_suite','private_output_acl','rename_lock','media_read',
                      'mock_pcm_to_mp4','mp4_decode','thumbnail','two_line_captions'],
            'real_api_calls':0}


if __name__ == '__main__':
    try:
        report = run()
    except ValueError as error:
        print(str(error));raise SystemExit(1)
    except Exception:
        print('Windows確認に失敗しました。公開を保留し、setup.batと通常権限での起動を確認してください。')
        raise SystemExit(1)
    # Excluded by .gitignore and the public package allowlist; no local paths/keys saved.
    descriptor, temporary = tempfile.mkstemp(prefix='.windows-check-', dir=ROOT)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as output:
            json.dump(report,output,ensure_ascii=False,indent=2)
        Path(temporary).replace(ROOT/'WINDOWS_CHECK_RESULT.json')
    finally:
        Path(temporary).unlink(missing_ok=True)
    print('Windows確認: PASS（実API送信なし）。確認結果を保存しました。')
