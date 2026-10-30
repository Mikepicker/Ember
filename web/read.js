// read: the newest stories of the feeds in the list, fetched by the Pi; a tap opens the story in Safari.
import { $, state, store, changed, api, add, remove, visible, folderOf, when } from './core.js';
import { esc } from './text.js';

export let refreshing = false;
const HOT = 500;  // Hacker News points from which a story is trending: the day's biggest stories there
const FLAME = '<svg viewBox="0 0 10 13" aria-label="trending"><path d="M5.6 0C6.2 3.4 9.5 5 9.5 8.8A4.5 4.5 0 0 1 .5 8.8C.5 6.4 1.8 4.8 2.8 3.9 2.8 5.8 3.6 7.1 4.9 7.6 4.2 5.2 4.3 2.4 5.6 0Z"/></svg>';
let listed = '', pulled = '', startY = null;  // where a pull began, at the top of the list

const saved = link => visible().find(n => folderOf(n) === 'saved' && n.body.includes(`](${link})`));

function keep(s) {  // a saved story is a note in saved/, made by the Pi like a shared link; saving it again takes it out
  const n = saved(s.link);
  if (n) remove(n.id);
  else add(`[${s.title.replace(/[[\]]/g, '')}](${s.link})`, { saved: true });
  changed();
}

async function refresh() {  // pulled down: the Pi fetches the feeds again, unless it did in the last minute
  refreshing = true;
  changed();
  state.news = await api('GET', '/api/news?fresh=1').catch(() => state.news);
  refreshing = false;
  store('news', state.news);
  changed();
}

export function draw() {
  const hot = s => s.heat >= HOT ? ` · <span class="hot">${FLAME}${s.heat < 1000 ? s.heat : (s.heat / 1000).toFixed(1).replace('.0', '') + 'k'}</span>` : '';
  const story = (s, i) => `<div class="story"><a href="${esc(s.link)}" target="_blank" rel="noopener"><span>${esc(s.title)}</span>${s.thumb ? `<img src="/files/thumbs/${esc(s.thumb)}" alt="">` : ''}</a>` +
    `<p class="faint"><span>${esc(s.source)}${s.at ? ` · ${when(s.at * 1000)}` : ''}${hot(s)}</span>${saved(s.link) ? `<button class="on" data-story="${i}">★ saved</button>` : `<button data-story="${i}">☆ save</button>`}</p></div>`;
  const failed = state.news?.failed.length ? `<p class="faint">couldn't read ${state.news.failed.map(esc).join(', ')}</p>` : '';
  const picked = state.news?.for_you || [], all = (state.news?.stories || []).map((s, i) => [s, i]);  // for you: closest to what you saved
  const near = picked.map(link => all.find(([s]) => s.link === link)).filter(Boolean), rest = all.filter(([s]) => !picked.includes(s.link));
  $('pull').textContent = refreshing ? 'fetching…' : pulled === 'far' ? 'release to refresh' : pulled ? 'pull to refresh' : near.length ? 'for you' : 'latest';  // apart from the stories, so a pull doesn't redraw the story under the finger
  const html = (near.length ? near.map(([s, i]) => story(s, i)).join('') + '<div class="label">latest</div>' : '') +
    (state.news ? rest.map(([s, i]) => story(s, i)).join('') || '<p class="faint">no stories. are the links right?</p>' : '<p class="faint">fetching the news…</p>') + failed;
  if (html !== listed) $('news').innerHTML = listed = html;  // redraw only on change, so the pictures don't flicker
}

export function setup() {
  $('read').addEventListener('touchstart', e => { startY = $('read').scrollTop <= 0 ? e.touches[0].clientY : null; }, { passive: true });
  $('read').addEventListener('touchmove', e => {
    if (startY === null) return;
    const d = e.touches[0].clientY - startY, was = pulled;
    pulled = d > 80 ? 'far' : d > 10 ? 'some' : '';
    if (pulled !== was) draw();
  }, { passive: true });
  for (const ended of ['touchend', 'touchcancel']) $('read').addEventListener(ended, () => {
    if (pulled === 'far' && !refreshing) refresh();
    startY = null;
    pulled = '';
    draw();
  });
  $('news').onclick = e => {
    const b = e.target.closest('[data-story]');
    if (b) keep(state.news.stories[b.dataset.story]);
  };
}
