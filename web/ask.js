// ask: the Pi answers from the notes as it writes; "[2]" in an answer is the note it came from.
import { $, state, store, changed, titleOf } from './core.js';
import { esc, md } from './text.js';
import { sound } from './sound.js';

export let asking = false;
let trouble = '', said = '';

async function ask() {
  const q = $('question').value.trim();
  if (!q || asking) return;
  const turn = { q, a: '', ids: [] }, chat = state.chat.flatMap(t => [t.q, t.a]).concat(q);
  $('question').value = '';
  state.chat.push(turn);
  asking = true;
  trouble = '';
  changed();
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
      draw();
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
  changed();
}

export function draw() {
  const cite = t => md(t.a).replace(/( ?)\[(\d+)\]/g, (m, s, k) => (t.ids[k - 1] ? `${s}<a href="#n/${t.ids[k - 1]}">[${k}]</a>` : ''));  // a number with no note sent, the model's habit, goes
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

export function setup() {
  $('asking').onclick = ask;
  $('question').onkeydown = e => { if (e.key === 'Enter') ask(); };
  $('forget').onclick = () => {
    state.chat = [];
    trouble = '';
    store('chat', []);
    changed();
  };
}
