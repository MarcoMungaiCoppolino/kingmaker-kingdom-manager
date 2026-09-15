(() => {
  // Where one was looking, as a fraction of how much there is to scroll. As
  // a fraction and not in pixels because the zoom changes the width of the
  // drawing: this way one comes back to the **same piece of map** even if
  // it was enlarged meanwhile, instead of to the same number of pixels.
  const KEY = 'km-map-view';
  let memory = null;
  try { memory = JSON.parse(sessionStorage.getItem(KEY) || 'null'); }
  catch (e) { memory = null; }

  const connect = (box) => {
    if (box.dataset.kmDrag) return;
    box.dataset.kmDrag = '1';

    // A hidden box measures zero: there is nothing to remember there and
    // nothing to restore, and reading it anyway would write a zero over the
    // good memory.
    const visible = () => box.clientWidth > 0 && box.clientHeight > 0;
    const howMuch = () => [Math.max(0, box.scrollWidth - box.clientWidth),
                          Math.max(0, box.scrollHeight - box.clientHeight)];

    // When the hand last touched the map. It is the way to know **who**
    // moved the scroll: coming back to the Map something resets it to zero
    // on its own, and without this distinction the memory was overwritten
    // with precisely the zero one wanted to undo.
    let lastGesture = 0;
    const gesture = () => { lastGesture = Date.now(); };
    ['wheel', 'mousedown', 'mousemove', 'touchstart', 'touchmove', 'keydown']
      .forEach((name) => box.addEventListener(name, gesture, {passive: true}));
    const BREATH = 400;   // ms: beyond this, it was not a hand

    let restoring = false;
    const remember = () => {
      if (!visible() || restoring) return;
      const [dx, dy] = howMuch();
      if (dx <= 0 && dy <= 0) return;
      memory = {x: dx > 0 ? box.scrollLeft / dx : 0,
                 y: dy > 0 ? box.scrollTop / dy : 0};
      try { sessionStorage.setItem(KEY, JSON.stringify(memory)); } catch (e) {}
    };

    const restore = () => {
      if (!memory || !visible()) return false;
      const [dx, dy] = howMuch();
      if (dx <= 0 && dy <= 0) return false;   // drawing not yet measurable
      restoring = true;
      box.scrollLeft = memory.x * dx;
      box.scrollTop = memory.y * dy;
      restoring = false;
      return true;
    };

    const outOfPlace = () => {
      if (!memory) return false;
      const [dx, dy] = howMuch();
      return Math.abs(box.scrollLeft - memory.x * dx) > 2
          || Math.abs(box.scrollTop - memory.y * dy) > 2;
    };

    box.addEventListener('scroll', () => {
      if (restoring) return;
      // A scroll nobody asked for: it is the jolt taken when switching tab.
      // It is put back where it was instead of taken for good.
      if (Date.now() - lastGesture > BREATH && outOfPlace()) {
        restore();
        return;
      }
      remember();
    }, {passive: true});

    // On the first round the drawing may not have arrived yet — and without
    // a drawing there is no width, so nowhere to scroll. We retry for a while
    // instead of giving up at the first attempt.
    //
    // With a timer and not with `requestAnimationFrame`: frames do not run
    // when the window is not drawing — another window in front, the browser
    // tab in the background — and there the restore would never have
    // started. The timer runs anyway, and it is precisely when one comes
    // back to look that it must already be in place.
    const restoreWhenPossible = (attempts) => {
      if (restore() || attempts <= 0) return;
      setTimeout(() => restoreWhenPossible(attempts - 1), 60);
    };
    // Changing zoom the width of the drawing changes and the browser clamps
    // the scroll: it is put back on the piece of map one was looking at.
    if (window.ResizeObserver) {
      new ResizeObserver(() => { if (!outOfPlace()) return; restoreWhenPossible(6); })
        .observe(box);
    }
    box.querySelectorAll('img').forEach((img) => {
      img.addEventListener('load', () => restoreWhenPossible(20));
    });
    // Switching tab always goes through a click **outside** the map, and it
    // is right after that click that the scroll is reset to zero. The jolt
    // does not arrive as a scroll event — there is nothing to intercept — so
    // we hook onto the only thing that always precedes it. A click inside
    // the map does not count: there the hand rules, and putting back what
    // it just did would be the opposite defect.
    //
    // We watch for a moment instead of correcting once: putting it back
    // **before** the jolt arrives is useless, and that is what happened
    // answering the click on the next frame.
    let watchUntil = 0, watching = false;
    const watch = () => {
      if (Date.now() > watchUntil) { watching = false; return; }
      if (Date.now() - lastGesture > BREATH && outOfPlace()) restore();
      setTimeout(watch, 60);
    };
    document.addEventListener('click', (e) => {
      if (box.contains(e.target)) return;
      watchUntil = Date.now() + 1200;
      if (!watching) { watching = true; setTimeout(watch, 30); }
    }, true);
    restoreWhenPossible(30);
    let active = false, startX = 0, startY = 0, scrollX = 0, scrollY = 0;
    // How many pixels the mouse moved with the button down: below this
    // threshold it was a click, not a drag, and a right click on the map
    // serves to aim at a journey's destination.
    let shift = 0;
    const THRESHOLD = 5;

    box.addEventListener('mousedown', (e) => {
      if (e.button !== 2 && e.button !== 1) return;   // right or middle
      active = true;
      shift = 0;
      startX = e.clientX; startY = e.clientY;
      scrollX = box.scrollLeft; scrollY = box.scrollTop;
      box.classList.add('km-running');
      e.preventDefault();
    });

    window.addEventListener('mousemove', (e) => {
      if (!active) return;
      // Dragging is a hand at work, even when the pointer leaves the box:
      // without this, after half a second of dragging the scroll would look
      // like a jolt to undo.
      gesture();
      shift = Math.max(shift,
        Math.abs(e.clientX - startX) + Math.abs(e.clientY - startY));
      box.scrollLeft = scrollX - (e.clientX - startX);
      box.scrollTop = scrollY - (e.clientY - startY);
      e.preventDefault();
    });

    const stop = () => {
      if (!active) return;
      active = false;
      box.classList.remove('km-running');
    };
    window.addEventListener('mouseup', stop);
    window.addEventListener('blur', stop);

    // No context menu on the map: there the right button has two jobs. If
    // the mouse moved it was a drag, and the event stops here in the capture
    // phase, before reaching the image; if it stayed still it was a click,
    // and we let it through: that is how the destination is aimed at.
    box.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      if (shift > THRESHOLD) { e.stopPropagation(); }
    }, true);
  };

  const search = () => document.querySelectorAll('.km-drag').forEach(connect);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', search);
  } else {
    search();
  }
  // The panels rebuild on their own: hook the new boxes up again.
  new MutationObserver(search).observe(document.documentElement, {childList: true, subtree: true});
})();
