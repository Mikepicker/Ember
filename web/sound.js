// Soft key clicks while typing and a small bell on send, made on the spot; off unless switched on under notes.
import { $ } from './core.js';

let audio = null;
const loud = () => { try { return localStorage.getItem('sound') === 'on'; } catch { return false; } };

export function sound(bell) {
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

export function setup() {
  $('sound-now').textContent = loud() ? 'on' : 'off';
  $('sound').onclick = () => {
    try { localStorage.setItem('sound', loud() ? 'off' : 'on'); } catch {}
    $('sound-now').textContent = loud() ? 'on' : 'off';
    sound(true);
  };
  document.addEventListener('input', e => e.inputType && sound());  // typing, not picking a photo
}
