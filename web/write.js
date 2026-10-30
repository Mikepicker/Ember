// write: a note, with photos and a recording, goes out as it is; the Pi tidies it.
import { $, add, changed, load, store, pad, day, clock } from './core.js';
import { sound } from './sound.js';

let pending = [], recorder = null;  // what goes with the next note

function send() {
  const text = $('text').value.trim();
  if (!text && !pending.length) return;
  add(text, { files: pending });
  pending = [];
  $('text').value = '';
  store('draft', '');
  sound(true);
  attached();
  changed();
}

function attached() {  // photos as thumbnails, a recording as "voice"; tap one to drop it
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

export async function setup() {
  $('send').onclick = send;
  $('voice').onclick = voice;
  $('text').value ||= (await load('draft')) || '';
  $('text').oninput = () => store('draft', $('text').value);
  $('text').onkeydown = e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') send(); };  // braces: a handler returning false drops the key
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
  document.addEventListener('click', e => {  // a tap anywhere on the page is a tap on the paper
    if (!$('write').hidden && !e.target.closest('button, label, a, input, textarea')) $('text').focus();
  });
  const tick = () => { const d = new Date(); $('now').textContent = `${day(d)} · ${clock(d)}`; };
  tick();
  setInterval(tick, 15000);
}
