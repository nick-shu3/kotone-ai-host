"""Local-only video composition. External calls are injected by server.py."""
import array
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import wave
import importlib.util

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('kotone_safe_storage', ROOT / 'safe_storage.py')
storage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(storage)
UserError = storage.UserError
MAX_VIDEO_BYTES = 100 * 1024 * 1024

def safe_child_environment():
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'TEMP', 'TMP',
               'TMPDIR', 'COMSPEC', 'PATHEXT', 'LANG', 'LC_ALL'}
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}

VOICES = ('cedar', 'marin', 'coral', 'ash')
STYLES = {
    'calm': '自然な日本語で、落ち着いたゲーム番組の司会者として話してください。親しみのある温かい声。文末を機械的にそろえず、句読点で自然な間を取り、過剰な演技をしない。',
    'bright': '自然な日本語で、ゲーム好きな明るい司会者として話してください。楽しさを伝えつつ、叫ばず、聞き取りやすく、会話らしい抑揚と自然な間をつける。',
}

def checked_text(value, label, limit, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise UserError(f'{label}は1〜{limit}文字で入力してください。')
    return value.strip()

def split_script(text):
    # A cue must always fit the on-screen telop: 32 characters x 2 lines.
    # Keep speech/caption cue boundaries identical so rendering never has to
    # invent extra line breaks later.
    MAX_LINE_CHARS = 32
    MAX_CUE_CHARS = MAX_LINE_CHARS * 2

    units = re.findall(r'[^。！？!?\n]+[。！？!?]?|[。！？!?]', text)
    chunks = []
    for unit in units:
        unit = unit.strip()
        while len(unit) > MAX_CUE_CHARS:
            # Prefer a natural break near the end of the 64-char cue.
            candidates = [
                unit.rfind('、', MAX_LINE_CHARS, MAX_CUE_CHARS),
                unit.rfind(' ', MAX_LINE_CHARS, MAX_CUE_CHARS),
            ]
            cut = max(candidates)
            cut = cut + 1 if cut >= MAX_LINE_CHARS else MAX_CUE_CHARS
            chunks.append(unit[:cut].strip())
            unit = unit[cut:].strip()
        if unit:
            if chunks and len(chunks[-1]) + len(unit) <= MAX_CUE_CHARS:
                chunks[-1] += unit
            else:
                chunks.append(unit)

    if not chunks or len(chunks) > 32:
        raise UserError('原稿を短くしてください。テロップの区切りは最大32個です。')
    return chunks


def format_caption(text, max_chars=32, max_lines=2):
    # Deterministic character-count wrapping. Explicit newlines are normalized
    # first so a malformed input can never create 3+ rendered lines.
    compact = ''.join(str(text).replace('\r', '').split('\n')).strip()
    if len(compact) > max_chars * max_lines:
        raise UserError(f'テロップが長すぎます（最大{max_chars}文字×{max_lines}行）。')
    return '\n'.join(compact[i:i + max_chars] for i in range(0, len(compact), max_chars))

def validate(data):
    if not isinstance(data, dict):
        raise UserError('入力形式が不正です。')
    script = checked_text(data.get('script'), '原稿', 1200)
    title = checked_text(data.get('title', 'FGO / note記事紹介'), 'タイトル', 80)
    voice = data.get('voice', 'marin')
    style = data.get('style', 'calm')
    if voice not in VOICES or not isinstance(style, str) or style not in STYLES:
        raise UserError('音声の設定が不正です。')
    value = data.get('speed', 1)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise UserError('速度は0.8〜1.2で指定してください。')
    try:
        speed = float(value)
    except (ValueError, TypeError, OverflowError):
        raise UserError('速度は0.8〜1.2で指定してください。') from None
    if not math.isfinite(speed) or not 0.8 <= speed <= 1.2:
        raise UserError('速度は0.8〜1.2で指定してください。')
    readings = checked_text(data.get('readings', 'FGO=エフジーオー\nnote=ノート\nシュウ３=シュウさん\n★4=ほしよん\n★5=ほしご'), '読み方辞書', 1200, False)
    replacements = []
    seen = set()
    for line in readings.splitlines():
        if not line.strip(): continue
        if '=' not in line:
            raise UserError('読み方辞書は「表記=読み」で1行ずつ入力してください。')
        word, reading = [v.strip() for v in line.split('=', 1)]
        if not word or not reading or len(word) > 60 or len(reading) > 80:
            raise UserError('読み方辞書の表記・読みを確認してください。')
        if word in seen:
            raise UserError('読み方辞書の同じ表記は1回だけ指定してください。')
        seen.add(word)
        replacements.append((word, reading))
    chunks = split_script(script)
    spoken = []
    for chunk in chunks:
        for word, reading in replacements:
            # Check before allocating: even different dictionary words can cascade.
            resulting_length = len(chunk) + chunk.count(word) * (len(reading) - len(word))
            if resulting_length > 600:
                raise UserError('読み方の置換結果が長すぎます。')
            chunk = chunk.replace(word, reading)
        if len(chunk) > 600:
            raise UserError('読み方の置換結果が長すぎます。')
        spoken.append(chunk)
    return dict(title=title, script=script, voice=voice, style=style, speed=speed,
                readings=readings, chunks=chunks, spoken=spoken)

def dependencies():
    from importlib.metadata import version
    try:
        from PIL import Image, ImageDraw, ImageFont
        if version('Pillow') != '12.3.0':
            raise UserError('動画用ライブラリを更新してください。setup.batを再実行してください。')
    except ImportError:
        raise UserError('先に setup.bat を実行してください（動画用ライブラリが未導入です）。')
    binary = native_binary()
    font_path()
    return str(binary)


def native_binary():
    import hashlib
    if os.environ.get('IMAGEIO_FFMPEG_EXE'):
        raise UserError('外部ffmpegの上書きは利用できません。設定を外してください。')
    if os.name != 'nt' or sys.maxsize <= 2**32:
        raise UserError('動画変換はWindows 64bitに対応しています。')
    try:
        manifest = json.loads((ROOT / 'native-runtime.json').read_text(encoding='utf-8'))
        if manifest['version'] != '9.0.2' or manifest['platform'] != 'windows-x86_64':
            raise UserError('承認済みの動画変換部品の設定を使用してください。')
        path = ROOT / 'runtime' / 'ffmpeg.exe'
        with storage.directory(ROOT, path.parent) as (folder, _):
            with storage.open_media(folder / path.name) as file:
                if os.fstat(file.fileno()).st_size != manifest['binary_size']:
                    raise UserError('動画変換部品のサイズが一致しません。setup.batを再実行してください。')
                digest = hashlib.sha256()
                for chunk in iter(lambda:file.read(1024*1024), b''):
                    digest.update(chunk)
                if digest.hexdigest() != manifest['binary_sha256']:
                    raise UserError('動画変換部品の検証に失敗しました。setup.batを再実行してください。')
        return path
    except (OSError, ValueError, KeyError) as error:
        if isinstance(error, UserError):raise
        raise UserError('先にsetup.batを実行してください（動画変換部品を確認できません）。') from None


def placeholder_sheet():
    """Original geometric fallback; no personal image or provenance metadata."""
    from PIL import Image, ImageDraw
    sheet = Image.new('RGBA', (1774,887), (0,0,0,0))
    draw = ImageDraw.Draw(sheet)
    for state in range(2):
        x=state*887
        draw.rounded_rectangle((x+220,450,x+668,880),radius=90,fill='#20344e',outline='#e878ba',width=10)
        draw.rounded_rectangle((x+214,130,x+674,526),radius=110,fill='#d7eef6',outline='#64ddf2',width=12)
        draw.rounded_rectangle((x+262,230,x+626,390),radius=40,fill='#16233a')
        for eye in (340,546):draw.ellipse((x+eye-24,282,x+eye+24,330),fill='#64ddf2')
        if state:draw.ellipse((x+397,417,x+490,467),fill='#16233a')
        else:draw.line((x+397,440,x+490,440),fill='#16233a',width=10)
        draw.line((x+444,130,x+444,80),fill='#64ddf2',width=12)
        draw.ellipse((x+418,40,x+470,92),fill='#e878ba')
    return sheet


def presenter_sheet():
    from PIL import Image
    path = ROOT / 'presenter.png'
    if not path.exists():return placeholder_sheet()
    with storage.directory(ROOT, ROOT) as (root, _):
        with storage.open_media(root / 'presenter.png') as file:
            with Image.open(file, formats=['PNG']) as source:
                if source.width*source.height > 8_000_000:
                    raise UserError('司会者画像が大きすぎます。')
                return source.convert('RGBA')


def font_path():
    paths = [ROOT / 'NotoSansCJKjp-Regular.otf',
             Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'meiryo.ttc',
             Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'YuGothM.ttc']
    for p in paths:
        if p.is_file(): return str(p)
    raise UserError('日本語フォントが見つかりません。ZIPを再展開してください。')

def timestamp(t):
    ms = round(t * 1000)
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}'

def synthesize(settings, folder, speech, update, cancel):
    folder.mkdir(parents=True, exist_ok=True)
    frames = bytearray(); cues = []; rate = 24000
    for i, (subtitle, spoken) in enumerate(zip(settings['chunks'], settings['spoken'])):
        if cancel.is_set(): raise UserError('中止しました。生成済みのAPI利用分は取り消されません。')
        update(f'音声を生成しています {i+1}/{len(settings["chunks"])}', round(i / len(settings['chunks']) * 90))
        # PCM avoids unreliable streaming WAV header lengths; format is 24 kHz, 16-bit LE mono.
        pcm = speech({'model': 'gpt-4o-mini-tts', 'voice': settings['voice'], 'input': spoken,
                      'instructions': STYLES[settings['style']] + ' 名前「コトネ」は「コ」にアクセントを置いてください。', 'speed': settings['speed'], 'response_format': 'pcm'})
        if not pcm or len(pcm) % 2 or len(pcm) > rate * 2 * 90:
            raise UserError('音声データの形式・長さを確認できませんでした。')
        start = len(frames) / (rate * 2)
        frames.extend(pcm)
        # Brief pause, not a forced gap in the middle of synthesized speech.
        frames.extend(b'\0\0' * int(rate * 0.12))
        end = len(frames) / (rate * 2)
        cues.append({'start': start, 'end': end, 'text': format_caption(subtitle)})
        if end > 300: raise UserError('動画が5分を超えます。原稿を短くしてください。')
    if cancel.is_set(): raise UserError('中止しました。')
    with wave.open(str(folder / 'audio.wav'), 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(frames)
    (folder / 'captions.srt').write_text('\n\n'.join(f'{i+1}\n{timestamp(c["start"])} --> {timestamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues)), encoding='utf-8')
    (folder / 'script.txt').write_text(settings['script'], encoding='utf-8')
    meta = dict(title=settings['title'], duration=len(frames)/(rate*2), cues=cues,
                voice=settings['voice'], style=settings['style'], speed=settings['speed'])
    (folder / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    return meta

def wrapped(text, font, width):
    lines=[]; line=''
    for ch in text:
        if ch=='\n' or (line and font.getlength(line+ch)>width):
            lines.append(line); line=''
        if ch!='\n': line+=ch
    if line: lines.append(line)
    return lines

def compose(title, caption, mouth=0):
    from PIL import Image, ImageDraw, ImageFont
    font = font_path()
    f=lambda size:ImageFont.truetype(font,size)
    im=Image.new('RGB',(1280,720),'#0b1020'); d=ImageDraw.Draw(im)
    d.rectangle((0,0,1280,6),fill='#64ddf2')
    d.text((52,32),'SHU3  /  FGO CHANNEL',font=f(23),fill='#64ddf2')
    d.text((1050,34),'AI音声・AI司会',font=f(17),fill='#b6c5db')
    # Original two-state asset. Cropping is performed by the renderer; source is unchanged.
    sheet=presenter_sheet()
    w,h=sheet.size; sprite=sheet.crop((mouth*w//2,0,(mouth+1)*w//2,h))
    sprite.thumbnail((510,570),Image.Resampling.LANCZOS)
    im.paste(sprite,(20,98),sprite)
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((542,106,1228,462),radius=22,fill='#16233a',outline='#334762',width=2)
    d.text((574,135),'NOTE  /  記事紹介',font=f(18),fill='#64ddf2')
    size=39
    while size>24 and len(wrapped(title,f(size),614))>5:size-=1
    lines=wrapped(title,f(size),614)
    for i,line in enumerate(lines[:6]):d.text((574,186+i*(size+13)),line,font=f(size),fill='#f1f5ff')
    d.rounded_rectangle((44,494,1236,668),radius=18,fill='#18263b',outline='#435671',width=2)
    size=32
    # Caption text is already normalized to 32 chars x max 2 lines.
    # Do not wrap it again by pixel width here; double-wrapping caused 3-4 lines.
    normalized_caption = format_caption(caption)
    lines = normalized_caption.split('\n') if normalized_caption else []
    if len(lines) > 2 or any(len(line) > 32 for line in lines):
        raise UserError('テロップのレイアウトが不正です。')
    y=511+(139-len(lines)*(size+12))/2
    for i,line in enumerate(lines):d.text((78,y+i*(size+12)),line,font=f(size),fill='#ffffff')
    d.text((48,683),'シュウ３のnoteを、AI司会者が紹介しています',font=f(16),fill='#9cafc9')
    return im

def render(folder, meta, update, cancel, binary=None, check_capacity=None, pass_fds=()):
    if check_capacity:
        check_capacity()
    binary=binary or dependencies()
    with wave.open(str(folder/'audio.wav'),'rb') as wav:
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2:raise UserError('音声形式が不正です。')
        rate=wav.getframerate()
        if rate != 24000 or not 1 <= wav.getnframes() <= rate * 300:
            raise UserError('音声の長さ・形式が不正です。')
        samples=array.array('h',wav.readframes(wav.getnframes()))
    if sys.byteorder!='little':samples.byteswap()
    fps=12; total=math.ceil(len(samples)/rate*fps)
    if total<1 or total>3600:raise UserError('動画の長さが不正です。')
    temp=folder/'rendering.mp4'; final=folder/'video.mp4'
    args=[binary,'-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24',
          '-s','1280x720','-framerate',str(fps),'-protocol_whitelist','pipe',
          '-format_whitelist','rawvideo','-i','pipe:0','-protocol_whitelist','file',
          '-format_whitelist','wav','-f','wav','-i',str(folder/'audio.wav'),
          '-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','veryfast','-crf','20',
          '-pix_fmt','yuv420p','-r','24','-c:a','aac','-b:a','160k','-ar','48000',
          '-movflags','+faststart','-shortest',str(temp)]
    cueidx=-1; pair=None; started=time.monotonic()
    with open(folder/'render.log','wb') as log:
        # Do not persist ffmpeg's raw diagnostics: they can contain local paths.
        process_options = {'pass_fds': pass_fds} if os.name != 'nt' else {}
        proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                              env=safe_child_environment(),
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0), **process_options)
        storage_errors = []
        def monitor_capacity():
            if temp.exists() and temp.stat().st_size >= MAX_VIDEO_BYTES:
                raise UserError('MP4の保存上限100MiBに達しました。原稿を短くしてください。')
            if check_capacity:
                check_capacity()
        # A watchdog also breaks a blocked pipe write if the encoder hangs.
        def watch():
            while proc.poll() is None:
                if cancel.wait(.25) or time.monotonic()-started>600:
                    if proc.poll() is None:proc.kill()
                    return
                try:
                    monitor_capacity()
                except (UserError, OSError):
                    storage_errors.append('保存容量の上限または空き容量の不足により、書き出しを中止しました。音声は再利用できます。')
                    if proc.poll() is None:proc.kill()
                    return
        import threading
        watcher = threading.Thread(target=watch,daemon=True)
        watcher.start()
        try:
            for n in range(total):
                if storage_errors:raise UserError(storage_errors[0])
                if n % 12 == 0:monitor_capacity()
                if cancel.is_set():raise UserError('書き出しを中止しました。音声は再利用できます。')
                t=n/fps
                idx=next((i for i,c in enumerate(meta['cues']) if c['start']<=t<c['end']),len(meta['cues'])-1)
                if idx!=cueidx:
                    pair=[compose(meta['title'],meta['cues'][idx]['text'],k) for k in (0,1)]; cueidx=idx
                    if n==0:pair[0].save(folder/'thumbnail.png')
                segment=samples[int(n*rate/fps):int((n+1)*rate/fps)]
                rms=math.sqrt(sum(x*x for x in segment)/max(1,len(segment)))
                opened=int(rms>550)
                frame=pair[opened].copy()
                from PIL import ImageDraw
                ImageDraw.Draw(frame).rectangle((0,714,int(1280*(n+1)/total),719),fill='#64ddf2')
                proc.stdin.write(frame.tobytes())
                if n%12==0:update('MP4を書き出しています',round(n/total*100))
            proc.stdin.close()
            code=proc.wait(timeout=60)
            log.write(f'ffmpeg_exit_code={code}\n'.encode('ascii'))
            if storage_errors:raise UserError(storage_errors[0])
            if code!=0:raise UserError('動画変換に失敗しました。出力フォルダーのrender.logを確認してください。')
            if cancel.is_set():raise UserError('書き出しを中止しました。')
            monitor_capacity()
            temp.replace(final)
        except BaseException:
            if proc.poll() is None:proc.kill()
            proc.wait()
            temp.unlink(missing_ok=True)
            if storage_errors:raise UserError(storage_errors[0]) from None
            raise
        finally:
            watcher.join(timeout=1)
            if proc.stdin and not proc.stdin.closed:proc.stdin.close()
    return final
