// The app's state, kept in IndexedDB so it works offline, and synced with the Pi: changes go out through an outbox,
// and what changed there comes back every 10 seconds.
export const $ = id => document.getElementById(id);
export const state = { notes: {}, outbox: [], since: 0, chat: [], news: null };
export let online = true;

const redraws = [];
export const onChange = fn => redraws.push(fn);
export const changed = () => redraws.forEach(fn => fn());

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
export const load = key => idb('readonly', s => s.get(key));
export const store = (key, value) => idb('readwrite', s => s.put(value, key));
export const persist = () => Promise.all(Object.keys(state).map(k => store(k, state[k])));

export async function api(method, url, body) {
  const headers = typeof body === 'string' ? { 'Content-Type': 'application/json' } : {};
  const r = await fetch(url, { method, body, headers });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

let syncing = false;
export async function sync() {  // send what's waiting, then fetch what changed
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
    if (!$('read').hidden) state.news = await api('GET', '/api/news').catch(() => state.news);  // after the outbox: an edited feeds list counts
    await persist();
    online = true;
  } catch {
    online = false;
  }
  syncing = false;
  changed();
}

function send(op) {
  state.outbox.push(op);
  persist().then(sync);
}

// notes: what's shown, and the changes made to them here
export const visible = () => Object.values(state.notes).filter(n => !n.path.startsWith('_')).sort((a, b) => b.created.localeCompare(a.created));
export const folderOf = n => n.path.split('/').slice(0, -1).join('/');
export const titleOf = n => n.title || n.body.split('\n')[0] || 'untitled';
export const folders = () => state.notes.folders?.folders || [];  // the folders in the list, which new notes are filed into
// reminders and events the Pi put in the iPhone's apps: [line, "2026-10-28T17:00", "VTODO" | "VEVENT", has a time]
export const dues = n => (n.due || []).map(([line, at, kind, timed]) => ({ n, line, at: new Date(at), kind, timed }));

export function add(text, { files = [], saved = false } = {}) {  // a new note waits as written until the Pi has tidied it
  const id = crypto.randomUUID().slice(0, 8), created = stamp(new Date());
  state.notes[id] = { id, created, body: text, status: 'raw', path: `${saved ? 'saved' : 'unsorted'}/${id}.md` };
  send({ method: 'POST', url: '/api/notes', body: { id, created, text, saved }, files });
}

export function save(note, body) {
  note.body = body;
  send({ method: 'PUT', url: `/api/notes/${note.id}`, body: { body, base: note.mtime || 0, edited: stamp(new Date()) } });
}

export function move(note, folder) {  // the Pi moves the file; the note shows in its new folder straight away
  note.path = `${folder}/${note.path.split('/').pop()}`;
  send({ method: 'PUT', url: `/api/notes/${note.id}`, body: { folder } });
}

export function remove(id) {
  const queued = state.outbox.length;
  state.outbox = state.outbox.filter(op => op.body?.id !== id);  // never reached the Pi: just drop it
  delete state.notes[id];
  if (state.outbox.length === queued) send({ method: 'DELETE', url: `/api/notes/${id}` });
  else persist().then(sync);
}

// dates
export const pad = n => String(n).padStart(2, '0');
export const stamp = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const day = d => d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '').toLowerCase();
export const clock = d => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const when = s => { const d = new Date(s); return d.toDateString() === new Date().toDateString() ? clock(d) : day(d).slice(4); };
