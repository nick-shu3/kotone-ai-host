(() => {
  const el = id => document.getElementById(id);
  const audio = el('movie-audio'), player = el('movie-video');
  let jobId = null, ready = false, running = false, sample = false, snapshot = '';
  let cues = [], pollTimer = null, pollFailures = 0;
  let context, analyser, source, samples;
  const blobs = new Map();
  const say = text => { el('movie-status').textContent = text; };
  const settings = () => ({
    title: el('movie-title').value.trim(), script: el('movie-script').value.trim(),
    voice: el('movie-voice').value, style: el('movie-style').value,
    speed: Number(el('movie-speed').value), readings: el('movie-readings').value
  });
  function lock(value) {
    running = value;
    document.querySelectorAll('.movie-task').forEach(b => b.disabled = value);
    ['movie-title','movie-script','movie-voice','movie-style','movie-speed','movie-readings','movie-article'].forEach(id => el(id).disabled = value);
    el('render-movie').disabled = value || !ready || sample || snapshot !== JSON.stringify(settings());
    el('cancel-movie').hidden = !value || !jobId;
    el('movie-progress').hidden = !value;
  }
  async function api(path, body) {
    if (!await sessionReady) throw new Error('start.batから開き直してください。');
    const r = await fetch(path, {method: body === undefined ? 'GET' : 'POST',
      headers: {'Content-Type':'application/json','X-Session':token},
      ...(body === undefined ? {} : {body:JSON.stringify(body)})});
    const result = await r.json();
    if (!r.ok) throw new Error(result.error || '処理を完了できませんでした。');
    return result;
  }
  function clearMedia() {
    audio.pause(); player.pause();
    audio.removeAttribute('src'); player.removeAttribute('src');
    audio.load(); player.load();
    for (const url of blobs.values()) URL.revokeObjectURL(url);
    blobs.clear(); audio.hidden = true; player.hidden = true;
    el('movie-downloads').replaceChildren(); el('movie-downloads').hidden = true;
  }
  async function media(name, expectedJob) {
    const key = expectedJob + '/' + name;
    if (blobs.has(key)) return blobs.get(key);
    const r = await fetch('/media/' + expectedJob + '/' + name, {headers:{'X-Session':token}});
    if (!r.ok) throw new Error('出力ファイルを取得できませんでした。');
    if (Number(r.headers.get('Content-Length')) > 100 * 1024 * 1024)
      throw new Error('出力ファイルが大きすぎます。outputフォルダーを確認してください。');
    const blob = await r.blob();
    if (blob.size > 100 * 1024 * 1024) throw new Error('出力ファイルが大きすぎます。');
    if (expectedJob !== jobId) throw new Error('出力が切り替わりました。');
    const url = URL.createObjectURL(blob); blobs.set(key,url); return url;
  }
  function link(name, label, url) {
    const a = document.createElement('a');
    a.href=url; a.download=name; a.textContent=label; return a;
  }
  async function showAudio(job) {
    const id=jobId;
    cues=job.cues||[];
    const [wav,srt,script]=await Promise.all([
      media('audio.wav',id),media('captions.srt',id),media('script.txt',id)]);
    if (id!==jobId) return;
    audio.src=wav; audio.hidden=false;
    el('movie-downloads').replaceChildren(link('audio.wav','音声WAVを保存',wav),
      link('captions.srt','字幕SRTを保存',srt),link('script.txt','原稿を保存',script));
    el('movie-downloads').hidden=false;
    el('output-location').textContent='作成ファイルはアプリの output/' + id + ' にも保存されています。非公開の原稿や会話は公開しないでください。';
    if(sample) audio.play().catch(()=>say('再生ボタンで試聴してください。'));
  }
  async function poll() {
    const id=jobId;
    try {
      const job=await api('/api/job/'+id);
      if(id!==jobId) return;
      pollFailures=0; say(job.message+'（API送信残り '+job.calls_remaining+' 回）');
      el('movie-progress').value=job.progress;
      if(job.status==='audio_ready') {
        await showAudio(job); ready=true; lock(false);
      } else if(job.status==='done') {
        const url=await media('video.mp4',id);
        if(id!==jobId)return;
        player.src=url;player.hidden=false;
        el('movie-downloads').prepend(link('video.mp4','MP4を保存',url));
        ready=true;lock(false);
      } else if(job.status==='failed') {
        ready=false;lock(false);
      } else pollTimer=setTimeout(poll,1000);
    } catch(e) {
      pollFailures++;
      say(e.message+' 生成が止まったとは限りません。中止ボタンを残して状態を再確認しています。');
      pollTimer=setTimeout(poll,Math.min(15000,3000*pollFailures));
    }
  }
  async function prepare(customText, onlySample=false) {
    if(running||!await sessionReady)return;
    const input=settings();
    if(customText!==undefined)input.script=customText;
    if(onlySample)input.script=input.script.slice(0,64);
    if(!input.script)return say('まず原稿を入力してください。');
    snapshot=JSON.stringify(settings());sample=onlySample||customText!==undefined;
    ready=false;jobId=null;clearTimeout(pollTimer);clearMedia();
    lock(true);say('音声生成を開始しています…');
    try {
      const result=await api('/api/voice',input);jobId=result.job;
      el('scene-title').textContent=input.title;
      el('scene-caption').textContent='音声を生成しています…';
      lock(true);poll();
    }catch(e){lock(false);say(e.message);}
  }
  async function draft() {
    if(running||!await sessionReady)return;
    const article=el('movie-article').value.trim();
    if(!article)return say('紹介する記事の本文を貼り付けてください。');
    lock(true);say('紹介原稿を作成しています…');
    try {
      const result=await api('/api/talk',{action:'script',article,message:'',history:[]});
      el('movie-script').value=result.text.slice(0,1200);
      say('記事と照合し、原稿を確認・編集してください。（API送信残り '+result.calls_remaining+' 回）');
    }catch(e){say(e.message);}finally{lock(false);}
  }
  el('draft-movie').onclick=draft;
  el('sample-voice').onclick=()=>prepare(undefined,true);
  el('create-voice').onclick=()=>prepare();
  window.makeNaturalVoice=text=>{
    if(!text)return say('まず返答や原稿を作成してください。');
    return prepare(text);
  };
  el('render-movie').onclick=async()=>{
    if(running||!ready||sample||snapshot!==JSON.stringify(settings()))return;
    // A new render must fetch the new video, not reuse a previously downloaded blob.
    const key=jobId+'/video.mp4';if(blobs.has(key)){URL.revokeObjectURL(blobs.get(key));blobs.delete(key);}
    lock(true);say('MP4を書き出しています…');
    try{await api('/api/render',{job:jobId});poll();}
    catch(e){lock(false);say(e.message);}
  };
  el('cancel-movie').onclick=async()=>{
    if(!jobId)return;
    try{const result=await api('/api/cancel',{job:jobId});say(result.message);}
    catch(e){say(e.message);}
  };
  ['movie-title','movie-script','movie-voice','movie-style','movie-speed','movie-readings'].forEach(id=>{
    el(id).addEventListener('input',()=>{if(!running)lock(false);});
  });
  audio.addEventListener('play',()=>{
    if(!context){
      const AC=window.AudioContext||window.webkitAudioContext;
      if(!AC)return;
      context=new AC();source=context.createMediaElementSource(audio);
      analyser=context.createAnalyser();analyser.fftSize=256;
      source.connect(analyser);analyser.connect(context.destination);
      samples=new Uint8Array(analyser.frequencyBinCount);
    }
    context.resume().catch(()=>{});
  });
  function animate(){
    if(!audio.paused){
      const cue=cues.find(c=>c.start<=audio.currentTime&&audio.currentTime<c.end);
      if(cue)el('scene-caption').textContent=cue.text;
      if(analyser){
        analyser.getByteTimeDomainData(samples);
        let total=0;for(const value of samples)total+=(value-128)**2;
        el('avatar-sheet').style.transform=Math.sqrt(total/samples.length)>4?'translateX(-50%)':'translateX(0)';
      }
    }else el('avatar-sheet').style.transform='translateX(0)';
    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);
  window.addEventListener('beforeunload',()=>{clearTimeout(pollTimer);clearMedia();});
  document.querySelectorAll('.movie-task').forEach(b=>b.disabled=true);
  (async()=>{
    if(!await sessionReady)return;
    try {
      const cap=await api('/api/capabilities');
      lock(false);
      if(!cap.video_ready)say(cap.error);
      else if(!cap.api_ready)say('APIキー未設定です。start.batを再起動して入力してください。');
      else say('原稿を確認して音声を生成できます。API送信残り '+cap.calls_remaining+' 回。');
    }catch(e){say(e.message);}
  })();
})();
