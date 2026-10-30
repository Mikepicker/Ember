// ember: write, ask, keep and read notes. Works offline; the Pi does the tidying.
// Pages: #write, #ask, #notes, #read, #f/<folder>, #n/<id>. Each page's module draws it; this one picks the page.
import { $, state, online, onChange, load, store, sync, visible } from './core.js';
import * as write from './write.js';
import * as ask from './ask.js';
import * as list from './list.js';
import * as note from './note.js';
import * as read from './read.js';
import * as sound from './sound.js';

function render() {
  const [view, arg] = decodeURIComponent(location.hash.slice(1)).split(/\/(.*)/);
  const page = { ask: 'ask', notes: 'notes', read: 'read', f: 'notes', n: 'note' }[view] || 'write';
  for (const id of ['write', 'ask', 'notes', 'read', 'note']) $(id).hidden = id !== page;
  const tab = page === 'note' ? (arg === 'feeds' ? 'read' : 'notes') : page;
  for (const t of ['write', 'ask', 'notes', 'read']) $('tab-' + t).className = t === tab ? 'on' : '';
  const tidying = visible().some(n => n.status === 'raw');
  $('status').textContent = state.outbox.length ? `${state.outbox.length} waiting` : !online ? 'offline' : tidying ? 'tidying…' : '';
  $('dot').className = !online ? 'off' : ask.asking || tidying || read.refreshing ? 'busy' : '';  // the ember glows while the Pi works
  if (page === 'ask') ask.draw();
  if (page === 'notes') list.draw(view === 'f' ? arg : '');
  if (page === 'read') read.draw();
  if (page === 'note') note.draw(arg);
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

for (const k of Object.keys(state)) state[k] = (await load(k)) ?? state[k];
if ((await load('format')) !== 2) {  // the notes' data changed shape: fetch everything once
  state.since = 0;
  store('format', 2);
}
await write.setup();
ask.setup();
note.setup();
read.setup();
sound.setup();
look(document.documentElement.dataset.look || 'auto');
$('look').onclick = () => look(LOOKS[(LOOKS.indexOf(document.documentElement.dataset.look) + 1) % LOOKS.length]);
$('search').oninput = render;
onChange(render);
addEventListener('hashchange', () => {
  note.leave();
  render();
  if (!$('write').hidden) $('text').focus();
  if (!$('ask').hidden) $('question').focus();
  if (!$('read').hidden) sync();
});
addEventListener('online', sync);
document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && sync());
setInterval(() => document.visibilityState === 'visible' && sync(), 10000);
render();
sync();
navigator.serviceWorker?.register('sw.js');
