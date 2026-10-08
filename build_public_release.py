"""Create an allowlisted source ZIP locally. No Git/network/publish operations."""
import hashlib
import os
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent
ALLOWLIST = (
    '.gitignore', 'LICENSE', 'FONT-LICENSE.txt', 'NotoSansCJKjp-Regular.otf',
    'PUBLIC_RELEASE_CHECKLIST.md', 'README.md', 'SECURITY_REVIEW.md',
    'THIRD_PARTY_NOTICES.md', 'VERSION', 'index.html', 'requirements.txt',
    'native-runtime.json', 'safe_storage.py', 'server.py', 'setup.bat',
    'start.bat', 'studio.js', 'video_engine.py', 'install_ffmpeg.py',
    'check_windows.bat', 'check_windows.py', 'build_public_release.py',
    'tests/test_security.py',
)


def build(destination):
    payload = {}
    for relative in ALLOWLIST:
        path = ROOT / relative
        if (path.is_symlink() or not path.is_file()
                or getattr(path.stat(), 'st_file_attributes', 0) & 0x400
                or not path.resolve().is_relative_to(ROOT)):
            raise ValueError('公開用ファイルがありません。またはリンクが含まれています。')
        raw = path.read_bytes()
        if path.suffix != '.otf':
            text = raw.decode('utf-8')
            for pattern in (r'sk-(?:proj-)?[A-Za-z0-9_-]{25,}',
                            r'gh[pousr]_[A-Za-z0-9]{20,}',
                            r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'):
                if re.search(pattern, text):
                    raise ValueError('秘密情報の候補を検出したため公開用ZIPを作成しません。')
        payload[relative] = raw
    manifest = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                       for name, data in sorted(payload.items()))
    payload['SHA256SUMS.txt'] = manifest.encode('utf-8')
    # Exclusive creation: never overwrite an existing package or follow a symlink.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name, data in sorted(payload.items()):
                    info = zipfile.ZipInfo('kotone-ai-host/' + name, (2026,10,8,0,0,0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, data)
    except BaseException:
        Path(destination).unlink(missing_ok=True)
        raise
    return destination


if __name__ == '__main__':
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise SystemExit('バージョンが不正です。')
    try:
        path = build(ROOT / ('kotone-ai-host-v' + version + '-public-source.zip'))
        print('公開準備用ZIPを作成しました。外部への公開・送信は行っていません。')
    except (OSError, ValueError):
        raise SystemExit('ZIPを作成できませんでした。既存ZIPや公開対象ファイルを確認してください。')
