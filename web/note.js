// a note: read it, listen to it, tick its tasks, edit, move or delete it. The lists of folders and feeds open here too.
import { $, state, api, changed, folderOf, titleOf, folders, dues, save, move, remove, day, clock, pad } from './core.js';
import { esc, md, inline, player } from './text.js';
import { row, section } from './list.js';

let related = {}, listening = null, editing = false, moving = false, shown = '';
const id = () => location.hash.startsWith('#n/') ? location.hash.slice(3) : null;

export function draw(nid) {
  const n = state.notes[nid];
  if (!n) return ($('view').innerHTML = '<p class="faint">not synced yet…</p>');
  const d = new Date(n.created), list = nid === 'folders' || nid === 'feeds';
  if (!(nid in related) && !list && n.status !== 'raw') {  // the notes closest in meaning, asked once per visit
    related[nid] = [];
    api('GET', `/api/related/${nid}`).then(r => { related[nid] = r.ids; changed(); }).catch(() => delete related[nid]);
  }
  const about = list ? (nid === 'feeds' ? 'one per line, name: link to its feed. their newest stories show under read.' : 'one per line, name: what goes in it. new notes are filed into these.')
    : `${day(d)} · ${clock(d)} · ${esc(folderOf(n))}`;
  const html = moving
    ? `<div class="label">move to</div>` + folders().map(f => `<button class="row" data-folder="${esc(f)}"><span>${esc(f)}</span><span>${f === folderOf(n) ? 'here' : ''}</span></button>`).join('')
    : `<div class="faint">${about}${list || n.status === 'raw' || listening === nid ? '' : '<button data-listen>listen</button>'}</div><h1>${esc(titleOf(n))}</h1>` +
      (listening === nid ? player(`/api/listen/${nid}`) : '') +
      (n.status === 'raw' ? `<p class="faint">tidying…</p>${md(n.body)}` : md(list ? n.body.replace(/^([^:\n]+): /gm, '**$1**: ') : n.body, dues(n))) +
      (n.tags ? `<p class="tags faint">${n.tags.split(', ').map(t => '#' + esc(t)).join(' ')}</p>` : '') +
      (n.original ? `<p class="faint">${inline(`[[${n.original}]]`)}</p>` : '') +
      section('related', (related[nid] || []).map(r => state.notes[r]).filter(Boolean).map(row));
  if (html !== shown) $('view').innerHTML = shown = html;  // redraw only on change, so playback isn't cut off
  $('view').hidden = editing;
  $('edit').hidden = !editing;
  $('editing').textContent = editing ? 'done' : 'edit';
  $('remove').hidden = list;
  $('moving').hidden = list || editing || n.status === 'raw';  // a note being tidied is about to be filed
  $('moving').textContent = moving ? 'cancel' : 'move';
}

export function leave() {  // another page: nothing stays half done
  editing = moving = false;
  listening = null;
  sure(false);
  document.querySelectorAll('audio').forEach(a => a.pause());
}

function sure(on) {  // the first tap on delete asks "sure?", a second within 3 s goes ahead
  $('remove').classList.toggle('sure', on);
  $('remove').textContent = on ? 'sure?' : 'delete';
}

// the player: play/pause, an ember playhead along a dashed track
const mmss = s => `${Math.floor(s / 60)}:${pad(Math.floor(s % 60))}`;
function tune(player) {
  const a = player.querySelector('audio'), known = isFinite(a.duration);
  player.querySelector('.track').style.setProperty('--at', known ? `${(a.currentTime / a.duration) * 100}%` : '0%');
  player.querySelector('.time').textContent = !a.readyState ? 'reading…' : known ? `${mmss(a.currentTime)} / ${mmss(a.duration)}` : mmss(a.currentTime);  // the Pi is still speaking it
  player.querySelector('button').textContent = a.paused ? 'play' : 'pause';
  player.classList.toggle('on', !a.paused);
}

function tap(e) {
  const player = e.target.closest('.player');
  if (player) {
    const a = player.querySelector('audio'), track = e.target.closest('.track');
    if (track && isFinite(a.duration)) {
      const r = track.getBoundingClientRect();
      a.currentTime = ((e.clientX - r.left) / r.width) * a.duration;
    } else if (e.target.tagName === 'BUTTON') a.paused ? a.play() : a.pause();
    return;
  }
  if (e.target.closest('[data-listen]')) {  // the Pi reads the note aloud; play() is called within the tap, or the iPhone won't play it
    listening = id();
    changed();
    return $('view').querySelector('audio[src^="/api/listen/"]').play().catch(() => {});
  }
  const n = state.notes[id()], to = e.target.closest('[data-folder]'), line = e.target.dataset.line;
  if (to) {
    if (to.dataset.folder !== folderOf(n)) move(n, to.dataset.folder);
    moving = false;
    return changed();
  }
  if (line === undefined) return;
  const lines = n.body.split('\n');
  lines[line] = lines[line].replace(/\[([ x])\]/, (_, c) => (c === 'x' ? '[ ]' : '[x]'));
  save(n, lines.join('\n'));
  changed();
}

export function setup() {
  for (const type of ['loadedmetadata', 'timeupdate', 'seeked', 'play', 'pause', 'ended']) {
    document.addEventListener(type, e => { if (e.target.closest?.('.player')) tune(e.target.closest('.player')); }, true);
  }
  $('view').onclick = tap;
  $('back').onclick = () => { editing = false; history.back(); };
  $('remove').onclick = () => {
    if ($('remove').classList.contains('sure')) return remove(id()), (location.hash = '#notes');
    sure(true);
    setTimeout(() => sure(false), 3000);
  };
  $('moving').onclick = () => { moving = !moving; changed(); };
  $('editing').onclick = () => {
    const n = state.notes[id()];
    moving = false;
    if (editing && $('edit').value !== n.body) save(n, $('edit').value);
    if (!editing) $('edit').value = n.body;
    editing = !editing;
    changed();
  };
}
