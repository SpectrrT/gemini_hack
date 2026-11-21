// Live camera previews are shown mirrored, like a mirror or a video call. Display only: the frames sent to
// the models and the recorded clips are not flipped. Recorded files played in the same <video> stay unflipped.
(function () {
  const style = document.createElement('style');
  style.textContent = 'video.mirror { transform: scaleX(-1); }';
  document.head.appendChild(style);
  const sync = e => { const v = e.target; if (v && v.tagName === 'VIDEO') v.classList.toggle('mirror', !!v.srcObject); };
  ['loadedmetadata', 'emptied', 'play', 'playing'].forEach(ev => document.addEventListener(ev, sync, true));
})();
