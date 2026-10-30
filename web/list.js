// notes: what's coming up, the folders, the latest notes, and search across all of them.
import { $, visible, folderOf, titleOf, folders, dues, when } from './core.js';
import { esc, soon } from './text.js';

export const row = n => `<a class="row" href="#n/${n.id}"><span>${esc(titleOf(n))}</span><span>${n.status === 'raw' ? 'tidying…' : when(n.created)}</span></a>`;
export const section = (label, rows) => rows.length ? `<div class="label">${label}</div>${rows.join('')}` : '';

function upcoming() {  // the open tasks due from today on, soonest first
  const today = new Date().setHours(0, 0, 0, 0);
  return visible().flatMap(dues)
    .filter(d => d.at >= today && /- \[ \]/.test(d.n.body.split('\n')[d.line] || ''))
    .sort((a, b) => a.at - b.at).slice(0, 6);
}

export function draw(folder) {
  const notes = visible(), words = $('search').value.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length) {
    const found = notes.filter(n => words.every(w => `${n.title} ${n.tags} ${folderOf(n)} ${n.body}`.toLowerCase().includes(w)));
    return $('list').innerHTML = section('found', found.map(row)) || '<div class="label">nothing found</div>';
  }
  if (folder) {
    const inside = notes.filter(n => (folderOf(n) + '/').startsWith(folder + '/'));
    return $('list').innerHTML = `<a class="label" href="#notes">‹ ${esc(folder)}</a>` + inside.map(row).join('');
  }
  const counts = {}, add = (folder, k) => folder.split('/').forEach((_, i, parts) => {
    const f = parts.slice(0, i + 1).join('/');
    counts[f] = (counts[f] || 0) + k;
  });
  folders().forEach(f => add(f, 0));  // a folder from the list shows before any note is in it
  notes.forEach(n => add(folderOf(n), 1));
  const names = Object.keys(counts).sort((a, b) => (a === 'unsorted') - (b === 'unsorted') || a.localeCompare(b));
  const coming = upcoming().map(d => `<a class="row" href="#n/${d.n.id}"><span>${esc(d.n.body.split('\n')[d.line].replace(/^\s*- \[ \] /, ''))}</span><span class="due">${soon(d)}</span></a>`);
  $('list').innerHTML =
    section('coming up', coming) +
    '<div class="label">folders<a href="#n/folders">edit</a></div>' +
    names.map(f => `<a class="row" href="#f/${encodeURIComponent(f)}" style="padding-left:${(f.split('/').length - 1) * 2}ch"><span>${esc(f.split('/').pop())}</span><span>${counts[f] || ''}</span></a>`).join('') +
    section('recent', notes.slice(0, 8).map(row));
}
