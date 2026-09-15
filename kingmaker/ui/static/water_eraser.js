// The watercourse eraser: hold the button down and pass over the lines.
//
// Erasing a river one click at a time did not work, and not for a detail: a
// cut inside a hex is a line, and «click near the center» covered less than
// half its length. On the rest the click found nothing and nothing happened
// — which from outside reads «the button is broken».
//
// The right gesture to remove a line is to pass over it. Here the browser
// does only its share: it collects the points the mouse passes through and
// sends them to the server in bunches. What lies under those points is known
// by the server, the only one having the borders and the banks.
(() => {
  const PACE = 70;          // ms between one send and the next: ~14 a second
  const STEP = 4;           // px below which the point adds nothing

  let state = null;

  const activate = () => !!window.kmWaterEraser;

  const imageCoords = (box, e) => {
    const img = box.querySelector('img');
    if (!img || !img.naturalWidth) return null;
    const r = img.getBoundingClientRect();
    const scale = img.clientWidth / img.naturalWidth;
    return {x: (e.clientX - r.left) / scale, y: (e.clientY - r.top) / scale};
  };

  const send = () => {
    if (!state || !state.points.length) return;
    if (typeof emitEvent === 'function') {
      emitEvent('km_water_eraser', {points: state.points});
    }
    state.points = [];
  };

  document.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || !activate()) return;
    const box = e.target.closest('.km-drag');
    if (!box) return;
    const point = imageCoords(box, e);
    if (!point) return;
    state = {box, points: [[point.x, point.y]], last: point,
             heartbeat: setInterval(send, PACE)};
    // Without this the drag selects the image and the pointer becomes a
    // «you are moving a file» arrow.
    e.preventDefault();
  });

  window.addEventListener('mousemove', (e) => {
    if (!state || !activate()) return;
    const point = imageCoords(state.box, e);
    if (!point) return;
    // A point every so many pixels: the eraser must follow the line, not
    // count every mouse tick.
    const dx = point.x - state.last.x, dy = point.y - state.last.y;
    if (dx * dx + dy * dy < STEP * STEP) return;
    state.last = point;
    state.points.push([point.x, point.y]);
  });

  const close = () => {
    if (!state) return;
    clearInterval(state.heartbeat);
    send();
    state = null;
  };

  window.addEventListener('mouseup', close);
  window.addEventListener('blur', close);
})();
