// Notes as the app shows them: escaped HTML from a little Markdown, with tasks, links, photos and recordings.
import { state, titleOf, day, clock } from './core.js';

export const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

// a recording: play/pause and an ember playhead along a dashed track, worked by note.js
export const player = src => `<span class="player"><audio preload="metadata" src="${src}"></audio><button>play</button><span class="track"><i></i></span><span class="time"></span></span>`;

export function inline(s) {
  return esc(s)
    .replace(/!\[[^\]]*\]\(([^)\s]+)\)/g, '<img src="$1" alt="">')
    .replace(/\[voice\]\(([^)\s]+)\)/g, (_, src) => player(src))
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2">$1</a>')
    .replace(/\[\[([^\]]+)\]\]/g, (_, p) => {
      const n = Object.values(state.notes).find(n => n.path.replace(/\.md$/, '') === p.replace(/\.md$/, ''));
      return n ? `<a href="#n/${n.id}">${esc(titleOf(n))}</a>` : p;
    })
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
}

export function soon(d) {  // when a reminder or event is due, as near as it is: "today 09:00", "fri", "4 nov"
  const days = Math.round((new Date(d.at).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 864e5);
  const date = days === 0 ? 'today' : days === 1 ? 'tomorrow' : days > 1 && days < 7 ? day(d.at).slice(0, 3) : day(d.at).slice(4);
  return d.timed || d.kind === 'VTODO' ? `${date} ${clock(d.at)}` : date;
}

export function md(text, due = []) {  // tasks get a box to tick, and when they went to the phone for
  return text.split('\n').map((line, i) => {
    const t = line.match(/^(\s*)- \[([ x])\] (.*)/), d = due.find(d => d.line === i);
    const when = d ? `<span class="due">${d.kind === 'VEVENT' ? 'calendar' : 'reminder'} · ${soon(d)}</span>` : '';
    if (t) return `<p class="task${t[2] === 'x' ? ' done' : ''}" style="margin-left:${t[1].length}ch"><button data-line="${i}">[${t[2]}]</button> ${inline(t[3])}${when}</p>`;
    const b = line.match(/^(\s*)- (.*)/);
    if (b) return `<p class="bullet" style="margin-left:${b[1].length}ch">${inline(b[2])}</p>`;
    return line.trim() ? `<p>${inline(line)}</p>` : '<br>';
  }).join('');
}
