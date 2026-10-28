// ember: write, read and sync notes. Works offline; the Pi does the tidying.
const $ = id => document.getElementById(id);
const state = { notes: {}, outbox: [], since: 0, chat: [] };
let pending = [], recorder = null, online = true, syncing = false, editing = false, asking = false, trouble = '';

// storage: one IndexedDB store holding a few keys
const db = new Promise((ok, fail) => {
  const r = indexedDB.open('ember', 1);
  r.onupgradeneeded = () => r.result.createObjectStore('kv');
  r.onsuccess = () => ok(r.result);
  r.onerror = () => fail(r.error);
});
const idb = (mode, fn) => db.then(d => new Promise((ok, fail) => {
  const t = d.transaction('kv', mode), r = fn(t.objectStore('kv'));
  t.oncomplete = () => ok(r.result);
  t.onerror = () => fail(t.error);
}));
const load = key => idb('readonly', s => s.get(key));
const store = (key, value) => idb('readwrite', s => s.put(value, key));
const persist = () => Promise.all(Object.keys(state).map(k => store(k, state[k])));

// dates
const pad = n => String(n).padStart(2, '0');
const stamp = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const day = d => d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '').toLowerCase();
const clock = d => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const when = s => { const d = new Date(s); return d.toDateString() === new Date().toDateString() ? clock(d) : day(d).slice(4); };

// write
async function send() {
  const text = $('text').value.trim();
  if (!text && !pending.length) return;
  const id = crypto.randomUUID().slice(0, 8), created = stamp(new Date());
  state.outbox.push({ method: 'POST', url: '/api/notes', body: { id, created, text }, files: pending });
  state.notes[id] = { id, created, body: text, status: 'raw', path: `unsorted/${id}.md` };
  pending = [];
  $('text').value = '';
  sound(true);
  attached();
  store('draft', '');
  await persist();
  render();
  sync();
}

function attached() {  // what goes with the next note: photos as thumbnails, a recording as "voice"; tap one to drop it
  $('attached').replaceChildren(...pending.map(f => {
    const b = document.createElement('button');
    if (f.blob.type.startsWith('image')) {
      const img = b.appendChild(new Image());
      img.onload = () => URL.revokeObjectURL(img.src);
      img.src = URL.createObjectURL(f.blob);
    } else b.textContent = 'voice';
    b.onclick = () => { pending = pending.filter(p => p !== f); attached(); };
    return b;
  }));
}

async function voice() {
  if (recorder) return recorder.stop();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks = [], started = Date.now();
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      const type = recorder.mimeType;
      pending.push({ name: `${Date.now()}.${type.includes('mp4') ? 'm4a' : 'webm'}`, blob: new Blob(chunks, { type }) });
      recorder = null;
      clearInterval(tick);
      $('voice').textContent = 'voice';
      attached();
    };
    recorder.start();
    const tick = setInterval(() => {
      const s = Math.floor((Date.now() - started) / 1000);
      $('voice').textContent = `stop ${Math.floor(s / 60)}:${pad(s % 60)}`;
    }, 500);
  } catch {
    $('attached').textContent = 'no microphone access';
  }
}

// sync: send what's waiting, then fetch what changed
async function api(method, url, body) {
  const headers = typeof body === 'string' ? { 'Content-Type': 'application/json' } : {};
  const r = await fetch(url, { method, body, headers });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

async function sync() {
  if (syncing) return;
  syncing = true;
  try {
    while (state.outbox.length) {
      const op = state.outbox[0];
      if (op.files?.length) op.body.files = await Promise.all(op.files.map(f => api('POST', '/api/files/' + encodeURIComponent(f.name), f.blob).then(r => r.url)));
      await api(op.method, op.url, JSON.stringify(op.body));
      state.outbox.shift();
      await store('outbox', state.outbox);
    }
    const r = await api('GET', '/api/changes?since=' + state.since);
    for (const n of r.notes) state.notes[n.id] = n;
    state.since = r.now;
    await persist();
    online = true;
  } catch {
    online = false;
  }
  syncing = false;
  render();
}

function remove(id) {
  const queued = state.outbox.length;
  state.outbox = state.outbox.filter(op => op.body?.id !== id);  // never reached the Pi: just drop it
  if (state.outbox.length === queued) state.outbox.push({ method: 'DELETE', url: `/api/notes/${id}` });
  delete state.notes[id];
  persist().then(sync);
  location.hash = '#notes';
}

function confirmed(button, on) {  // first tap asks "sure?", a second tap within 3 s goes ahead
  button.classList.toggle('sure', on);
  button.textContent = on ? 'sure?' : 'delete';
}

function save(note, body) {
  state.outbox.push({ method: 'PUT', url: `/api/notes/${note.id}`, body: { body, base: note.mtime || 0, edited: stamp(new Date()) } });
  note.body = body;
  persist().then(sync);
}

// ask: the Pi answers from the notes as it writes; "[2]" in an answer is the note it came from
async function ask() {
  const q = $('question').value.trim();
  if (!q || asking) return;
  const turn = { q, a: '', ids: [] }, chat = state.chat.flatMap(t => [t.q, t.a]).concat(q);
  $('question').value = '';
  state.chat.push(turn);
  asking = true;
  trouble = '';
  render();
  try {
    const r = await fetch('/api/ask', { method: 'POST', body: JSON.stringify({ chat }), headers: { 'Content-Type': 'application/json' } });
    if (!r.ok) throw new Error(r.status);
    const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
    let text = '';
    for (let part; !(part = await reader.read()).done; ) {
      text += part.value;
      const at = text.indexOf('\n');  // the first line lists the notes behind the numbers
      if (at < 0) continue;
      turn.ids = JSON.parse(text.slice(0, at));
      turn.a = text.slice(at + 1);
      if (turn.a) sound();
      talk();
    }
    sound(true);
  } catch {
    if (!turn.a) {
      state.chat.pop();
      $('question').value = q;
      trouble = "couldn't reach the Pi. ask again when you're back online.";
    }
  }
  asking = false;
  store('chat', state.chat);
  render();
}

let said = '';
function talk() {
  const cite = t => md(t.a).replace(/\[(\d+)\]/g, (m, k) => (t.ids[k - 1] ? `<a href="#n/${t.ids[k - 1]}">${m}</a>` : m));
  const from = t => [...new Set([...t.a.matchAll(/\[(\d+)\]/g)].map(m => t.ids[m[1] - 1]))].filter(id => state.notes[id]);
  const html = state.chat.map(t => `<p class="q">› ${esc(t.q)}</p>` + (t.a
    ? cite(t) + (from(t).length ? `<p class="from faint">from ${from(t).map(id => `<a href="#n/${id}">${esc(titleOf(state.notes[id]))}</a>`).join(', ')}</p>` : '')
    : '<p class="faint">leafing through your notes…</p>')).join('') +
    `<p class="faint">${trouble || (state.chat.length ? '' : "ask about anything you've written down.")}</p>`;
  if (html !== said) {
    $('chat').innerHTML = said = html;
    $('chat').scrollTop = $('chat').scrollHeight;
  }
}

// sound: soft key clicks while typing and a small bell on send, made on the spot; off unless switched on
let audio = null;
const loud = () => { try { return localStorage.getItem('sound') === 'on'; } catch { return false; } };
function sound(bell) {
  if (!loud()) return;
  audio ||= new AudioContext();
  audio.resume();
  const t = audio.currentTime, gain = audio.createGain();
  gain.connect(audio.destination);
  if (bell) {
    const o = audio.createOscillator();
    o.frequency.value = 2400;
    gain.gain.setValueAtTime(0.12, t);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 1.4);
    o.connect(gain);
    o.start(t);
    o.stop(t + 1.4);
  } else {  // a key: a few milliseconds of fading noise, pitched a little differently each time
    const b = audio.createBuffer(1, 500, audio.sampleRate), d = b.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / d.length) ** 3;
    const s = audio.createBufferSource();
    s.buffer = b;
    s.playbackRate.value = 0.6 + Math.random() * 0.5;
    gain.gain.value = 0.25;
    s.connect(gain);
    s.start(t);
  }
}

// voice player: play/pause, an ember playhead along a dashed track
const mmss = s => `${Math.floor(s / 60)}:${pad(Math.floor(s % 60))}`;
function tune(player) {
  const a = player.querySelector('audio'), known = isFinite(a.duration);
  player.querySelector('.track').style.setProperty('--at', known ? `${(a.currentTime / a.duration) * 100}%` : '0%');
  player.querySelector('.time').textContent = known ? `${mmss(a.currentTime)} / ${mmss(a.duration)}` : mmss(a.currentTime);
  player.querySelector('button').textContent = a.paused ? 'play' : 'pause';
  player.classList.toggle('on', !a.paused);
}
for (const type of ['loadedmetadata', 'timeupdate', 'seeked', 'play', 'pause', 'ended']) {
  document.addEventListener(type, e => { if (e.target.closest?.('.player')) tune(e.target.closest('.player')); }, true);
}

// read
let shown = '';
const esc =s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const visible = () => Object.values(state.notes).filter(n => !n.path.startsWith('_')).sort((a, b) => b.created.localeCompare(a.created));
const folderOf = n => n.path.split('/').slice(0, -1).join('/');
const titleOf = n => n.title || n.body.split('\n')[0] || 'untitled';

function inline(s) {
  return esc(s)
    .replace(/!\[[^\]]*\]\(([^)\s]+)\)/g, '<img src="$1" alt="">')
    .replace(/\[voice\]\(([^)\s]+)\)/g, '<span class="player"><audio preload="metadata" src="$1"></audio><button>play</button><span class="track"><i></i></span><span class="time"></span></span>')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2">$1</a>')
    .replace(/\[\[([^\]]+)\]\]/g, (_, p) => {
      const n = Object.values(state.notes).find(n => n.path.replace(/\.md$/, '') === p.replace(/\.md$/, ''));
      return n ? `<a href="#n/${n.id}">${esc(titleOf(n))}</a>` : p;
    })
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
}

// reminders and events the Pi put in the iPhone's apps: [line, "2026-10-28T17:00", "VTODO" | "VEVENT", has a time]
const dues = n => (n.due || []).map(([line, at, kind, timed]) => ({ n, line, at: new Date(at), kind, timed }));

function soon(d) {
  const days = Math.round((new Date(d.at).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 864e5);
  const date = days === 0 ? 'today' : days === 1 ? 'tomorrow' : days > 1 && days < 7 ? day(d.at).slice(0, 3) : day(d.at).slice(4);
  return d.timed || d.kind === 'VTODO' ? `${date} ${clock(d.at)}` : date;
}

function upcoming() {
  const today = new Date().setHours(0, 0, 0, 0);
  return visible().flatMap(dues)
    .filter(d => d.at >= today && /- \[ \]/.test(d.n.body.split('\n')[d.line] || ''))
    .sort((a, b) => a.at - b.at).slice(0, 6);
}

function md(text, due = []) {
  return text.split('\n').map((line, i) => {
    const t = line.match(/^(\s*)- \[([ x])\] (.*)/), d = due.find(d => d.line === i);
    const when = d ? `<span class="due">${d.kind === 'VEVENT' ? 'calendar' : 'reminder'} · ${soon(d)}</span>` : '';
    if (t) return `<p class="task${t[2] === 'x' ? ' done' : ''}" style="margin-left:${t[1].length}ch"><button data-line="${i}">[${t[2]}]</button> ${inline(t[3])}${when}</p>`;
    const b = line.match(/^(\s*)- (.*)/);
    if (b) return `<p class="bullet" style="margin-left:${b[1].length}ch">${inline(b[2])}</p>`;
    return line.trim() ? `<p>${inline(line)}</p>` : '<br>';
  }).join('');
}

const row = n => `<a class="row" href="#n/${n.id}"><span>${esc(titleOf(n))}</span><span>${n.status === 'raw' ? 'tidying…' : when(n.created)}</span></a>`;
const section = (label, rows) => rows.length ? `<div class="label">${label}</div>${rows.join('')}` : '';

function list(folder) {
  const notes = visible(), words = $('search').value.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length) {
    const found = notes.filter(n => words.every(w => `${n.title} ${n.tags} ${n.body}`.toLowerCase().includes(w)));
    return $('list').innerHTML = section('found', found.map(row)) || '<div class="label">nothing found</div>';
  }
  if (folder) {
    const inside = notes.filter(n => (folderOf(n) + '/').startsWith(folder + '/'));
    return $('list').innerHTML = `<a class="label" href="#notes">‹ ${esc(folder)}</a>` + inside.map(row).join('');
  }
  const counts = {};
  for (const n of notes) folderOf(n).split('/').forEach((_, i, parts) => {
    const f = parts.slice(0, i + 1).join('/');
    counts[f] = (counts[f] || 0) + 1;
  });
  const folders = Object.keys(counts).sort((a, b) => (a === 'unsorted') - (b === 'unsorted') || a.localeCompare(b));
  const coming = upcoming().map(d => `<a class="row" href="#n/${d.n.id}"><span>${esc(d.n.body.split('\n')[d.line].replace(/^\s*- \[ \] /, ''))}</span><span class="due">${soon(d)}</span></a>`);
  $('list').innerHTML =
    section('coming up', coming) +
    section('folders',folders.map(f => `<a class="row" href="#f/${f}" style="padding-left:${(f.split('/').length - 1) * 2}ch"><span>${esc(f.split('/').pop())}</span><span>${counts[f]}</span></a>`)) +
    section('recent', notes.slice(0, 8).map(row)) || '<div class="label">no notes yet</div>';
}

function show(id) {
  const n = state.notes[id];
  if (!n) return ($('view').innerHTML = '<p class="faint">not synced yet…</p>');
  const d = new Date(n.created);
  const html =
    `<div class="faint">${day(d)} · ${clock(d)} · ${esc(folderOf(n))}</div><h1>${esc(titleOf(n))}</h1>` +
    (n.status === 'raw' ? `<p class="faint">tidying…</p>${md(n.body)}` : md(n.body, dues(n))) +
    (n.tags ? `<p class="tags faint">${n.tags.split(', ').map(t => '#' + esc(t)).join(' ')}</p>` : '') +
    (n.original ? `<p class="faint">${inline(`[[${n.original}]]`)}</p>` : '');
  if (html !== shown) $('view').innerHTML = shown = html;  // redraw only on change, so playback isn't cut off
  $('view').hidden = editing;
  $('edit').hidden = !editing;
  $('editing').textContent = editing ? 'done' : 'edit';
}

// look: follow the iPhone (auto), or always day or night; remembered on this device
const LOOKS = ['auto', 'day', 'night'];
function look(v) {
  document.documentElement.dataset.look = v;
  try { localStorage.setItem('look', v); } catch {}
  $('look-now').textContent = v === 'auto' ? 'auto, like the iPhone' : v;
  const [light, dark] = document.querySelectorAll('meta[name=theme-color]');
  light.content = v === 'night' ? '#1d1915' : '#f3ead8';
  dark.content = v === 'day' ? '#f3ead8' : '#1d1915';
}

// navigation: #write, #ask, #notes, #f/<folder>, #n/<id>
function render() {
  const [view, arg] = location.hash.slice(1).split(/\/(.*)/);
  const page = { ask: 'ask', notes: 'notes', f: 'notes', n: 'note' }[view] || 'write';
  for (const id of ['write', 'ask', 'notes', 'note']) $(id).hidden = id !== page;
  for (const tab of ['write', 'ask', 'notes']) $('tab-' + tab).className = (page === 'note' ? 'notes' : page) === tab ? 'on' : '';
  const tidying = visible().some(n => n.status === 'raw');
  $('status').textContent = state.outbox.length ? `${state.outbox.length} waiting` : !online ? 'offline' : tidying ? 'tidying…' : '';
  $('dot').className = !online ? 'off' : asking || tidying ? 'busy' : '';  // the ember glows while the Pi works
  if (page === 'ask') talk();
  if (page === 'notes') list(view === 'f' ? arg : '');
  if (page === 'note') show(arg);
}

function noteId() { return location.hash.startsWith('#n/') ? location.hash.slice(3) : null; }

$('send').onclick = send;
$('voice').onclick = voice;
$('text').oninput = () => store('draft', $('text').value);
$('text').onkeydown = e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') send();
};
$('photo').onchange = e => {  // photos picked together can share a name, like "image.jpg"
  [...e.target.files].forEach((f, i) => pending.push({ name: `${Date.now()}-${i}-${f.name.replace(/[^\w.]/g, '')}`, blob: f }));
  e.target.value = '';
  attached();
};
document.addEventListener('paste', e => {  // a pasted image becomes a photo; pasted text still goes into the note
  const images = [...e.clipboardData.files].filter(f => f.type.startsWith('image/'));
  if ($('write').hidden || !images.length) return;
  if (!e.clipboardData.getData('text/plain')) e.preventDefault();
  for (const f of images) pending.push({ name: `${Date.now()}-pasted.${f.type.split('/')[1]}`, blob: f });
  attached();
});
$('search').oninput = () => render();
$('look').onclick = () => look(LOOKS[(LOOKS.indexOf(document.documentElement.dataset.look) + 1) % LOOKS.length]);
$('sound').onclick = () => {
  try { localStorage.setItem('sound', loud() ? 'off' : 'on'); } catch {}
  $('sound-now').textContent = loud() ? 'on' : 'off';
  sound(true);
};
document.addEventListener('input', e => e.inputType && sound());  // typing, not picking a photo
$('asking').onclick = ask;
$('question').onkeydown = e => {
  if (e.key === 'Enter') ask();
};
$('forget').onclick = () => {
  state.chat = [];
  trouble = '';
  store('chat', []);
  render();
};
document.addEventListener('click', e => {
  if (!$('write').hidden && !e.target.closest('button, label, a, input, textarea')) $('text').focus();
});
$('back').onclick = () => { editing = false; history.back(); };
$('remove').onclick = () => {
  if ($('remove').classList.contains('sure')) return remove(noteId());
  confirmed($('remove'), true);
  setTimeout(() => confirmed($('remove'), false), 3000);
};
$('editing').onclick = () => {
  const n = state.notes[noteId()];
  if (editing && $('edit').value !== n.body) save(n, $('edit').value);
  if (!editing) $('edit').value = n.body;
  editing = !editing;
  render();
};
$('view').onclick = e => {
  const player = e.target.closest('.player');
  if (player) {
    const a = player.querySelector('audio'), track = e.target.closest('.track');
    if (track && isFinite(a.duration)) {
      const r = track.getBoundingClientRect();
      a.currentTime = ((e.clientX - r.left) / r.width) * a.duration;
    } else if (e.target.tagName === 'BUTTON') {
      if (a.paused) a.play();
      else a.pause();
    }
    return;
  }
  const line = e.target.dataset.line;
  if (line === undefined) return;
  const n = state.notes[noteId()], lines = n.body.split('\n');
  lines[line] = lines[line].replace(/\[([ x])\]/, (_, c) => (c === 'x' ? '[ ]' : '[x]'));
  save(n, lines.join('\n'));
  render();
};

(async () => {
  for (const k of Object.keys(state)) state[k] = (await load(k)) ?? state[k];
  if ((await load('format')) !== 2) {  // the notes' data changed shape: fetch everything once
    state.since = 0;
    store('format', 2);
  }
  $('text').value ||= (await load('draft')) || '';
  look(document.documentElement.dataset.look || 'auto');
  $('sound-now').textContent = loud() ? 'on' : 'off';
  const tick = () => { const d = new Date(); $('now').textContent = `${day(d)} · ${clock(d)}`; };
  tick();
  setInterval(tick, 15000);
  addEventListener('hashchange', () => {
    editing = false;
    confirmed($('remove'), false);
    document.querySelectorAll('audio').forEach(a => a.pause());
    render();
    if (!$('write').hidden) $('text').focus();
    if (!$('ask').hidden) $('question').focus();
  });
  addEventListener('online', sync);
  document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && sync());
  setInterval(() => document.visibilityState === 'visible' && sync(), 10000);
  render();
  sync();
  navigator.serviceWorker?.register('sw.js');
})();
