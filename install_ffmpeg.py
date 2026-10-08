"""Install a pinned Windows native runtime. Never extract arbitrary archive paths."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('kotone_install_storage', ROOT / 'safe_storage.py')
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)
UserError = storage.UserError
URL = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip'
ALLOWED_NAMES = {'ffmpeg.exe', 'FFMPEG-LICENSE.txt', 'FFMPEG-README.txt'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise UserError('動画変換部品の取得先が変更されました。承認済みの更新版を使用してください。')


def install_archive(archive, manifest, folder):
    """Verify entire archive and each selected member before replacing any file."""
    archive.seek(0)
    digest = hashlib.sha256()
    total = 0
    for chunk in iter(lambda: archive.read(1024*1024), b''):
        total += len(chunk)
        if total > manifest['max_download_bytes']:
            raise UserError('動画変換部品が大きすぎます。')
        digest.update(chunk)
    if digest.hexdigest() != manifest['archive_sha256']:
        raise UserError('動画変換部品のSHA-256が一致しません。導入を中止しました。')
    entries = manifest['files']
    if len(entries) != 3 or {entry['name'] for entry in entries} != ALLOWED_NAMES:
        raise UserError('動画変換部品の設定が不正です。')
    staged = []
    try:
        with zipfile.ZipFile(archive) as source:
            for entry in entries:
                info = source.getinfo(entry['member'])
                if info.file_size != entry['size'] or not 0 < info.file_size <= 120*1024*1024:
                    raise UserError('動画変換部品のサイズが一致しません。')
                target = folder / ('.install-' + secrets.token_hex(16) + '.tmp')
                staged.append((target, folder / entry['name']))
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                     | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                digest = hashlib.sha256()
                count = 0
                with os.fdopen(descriptor, 'wb') as output, source.open(info) as member:
                    for chunk in iter(lambda: member.read(1024*1024), b''):
                        count += len(chunk)
                        if count > entry['size']:
                            raise UserError('動画変換部品が大きすぎます。')
                        digest.update(chunk)
                        output.write(chunk)
                if count != entry['size'] or digest.hexdigest() != entry['sha256']:
                    raise UserError('動画変換部品のファイル検証に失敗しました。')
        # Publish executable last, after notices and all member hashes are verified.
        for temporary, destination in sorted(staged, key=lambda pair: pair[1].name == 'ffmpeg.exe'):
            temporary.replace(destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def main():
    if os.name != 'nt' or sys.maxsize <= 2**32:
        raise UserError('Windows 64bitでsetup.batを実行してください。')
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise UserError('管理者権限ではなく通常の権限でsetup.batを実行してください。')
    manifest = json.loads((ROOT / 'native-runtime.json').read_text(encoding='utf-8'))
    if manifest['url'] != URL or manifest['version'] != '9.0.2':
        raise UserError('動画変換部品の設定が不正です。')
    with storage.directory(ROOT, ROOT) as (root, _):
        (root / 'runtime').mkdir(mode=0o700, exist_ok=True)
    with storage.directory(ROOT, ROOT / 'runtime') as (folder, _):
        storage.make_private(folder)
        if (shutil.disk_usage(folder).free < 640*1024*1024
                or shutil.disk_usage(tempfile.gettempdir()).free < 512*1024*1024):
            raise UserError('動画変換部品の導入に必要な空き容量が不足しています。')
        print('Downloading pinned FFmpeg 9.0.2 (about 109 MB); checking SHA-256.')
        started = time.monotonic()
        opener = urllib.request.build_opener(NoRedirect())
        with tempfile.TemporaryFile() as archive:
            with opener.open(URL, timeout=20) as response:
                length = response.headers.get('Content-Length')
                if length and int(length) > manifest['max_download_bytes']:
                    raise UserError('動画変換部品が大きすぎます。')
                total = 0
                while True:
                    chunk = response.read(1024*1024)
                    if not chunk:break
                    total += len(chunk)
                    if total > manifest['max_download_bytes'] or time.monotonic()-started > 300:
                        raise UserError('動画変換部品のサイズまたは取得時間が上限に達しました。')
                    archive.write(chunk)
            install_archive(archive, manifest, folder)
        print('FFmpeg installed and verified. Upstream license/readme retained in runtime/.')


if __name__ == '__main__':
    try:
        main()
    except UserError as error:
        print(str(error))
        raise SystemExit(1)
    except Exception:
        print('動画変換部品を導入できませんでした。接続と空き容量を確認してください。')
        raise SystemExit(1)
