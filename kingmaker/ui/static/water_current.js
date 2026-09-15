// The current guide: take a vertex and follow the river with a finger.
//
// Giving a river a direction means giving it to all its stretches, one by
// one, and in the same sense. Doing it stretch by stretch would be a dozen
// clicks for a short river, each with the chance of getting the direction
// wrong: the right gesture is the one made with a finger on a chart — start
// here, go down to there.
//
// For that gesture to be seen while you make it, the course must be
// recomputed at every mouse move, and asking the server thirty times a
// second would be absurd. So the server sends **the network** once — the
// nodes with their coordinates and the stretches joining them — and here only
// the drawing is done. When one then clicks, the course is redone by the
// server on its own network: nothing of the browser's is kept, as for the
// travel ruler.
(() => {
  const COLOR = '#59e0c4';
  const RIM = '#0b1015';

  let network = null;          // {nodes: {key: [x, y]}, arcs: [[a, b], ...]}
  let neighbours = null;        // key -> [key, ...]
  let drawn = null;     // the last html written, so it is not rewritten unchanged

  const activate = () => !!(network && network.active);

  const buildNeighbours = () => {
    neighbours = {};
    for (const [a, b] of (network.arcs || [])) {
      (neighbours[a] = neighbours[a] || []).push(b);
      (neighbours[b] = neighbours[b] || []).push(a);
    }
  };

  // The shortest course in number of stretches: the same criterion as the
  // server. A river normally has a single road, and where it forks the
  // branches count, not how long they are.
  const course = (from, a) => {
    if (!neighbours || from === a) return from === a ? [from] : null;
    const fromWhere = {[from]: null};
    const queue = [from];
    for (let i = 0; i < queue.length; i++) {
      const here = queue[i];
      for (const other of (neighbours[here] || [])) {
        if (other in fromWhere) continue;
        fromWhere[other] = here;
        if (other === a) {
          const road = [a];
          while (fromWhere[road[road.length - 1]] !== null) {
            road.push(fromWhere[road[road.length - 1]]);
          }
          return road.reverse();
        }
        queue.push(other);
      }
    }
    return null;
  };

  const imageCoords = (box, e) => {
    const img = box.querySelector('img');
    if (!img || !img.naturalWidth) return null;
    const r = img.getBoundingClientRect();
    const scale = img.clientWidth / img.naturalWidth;
    return {x: (e.clientX - r.left) / scale, y: (e.clientY - r.top) / scale};
  };

  const nearest = (point) => {
    let chosen = null, dist = null;
    for (const key in (network.nodes || {})) {
      const [x, y] = network.nodes[key];
      const d = (point.x - x) ** 2 + (point.y - y) ** 2;
      if (dist === null || d < dist) { chosen = key; dist = d; }
    }
    if (chosen === null) return null;
    // Beyond a certain distance the finger is not pointing at any vertex:
    // better not to show a course that is not the one wanted.
    const threshold = (network.threshold || 0);
    return (threshold && dist > threshold * threshold) ? null : chosen;
  };

  // An arrow tip in the middle of the stretch: the direction is the only
  // thing this gesture decides, and it must be seen while deciding.
  const tip = (a, b, side) => {
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    const along = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    const dx = (b[0] - a[0]) / along, dy = (b[1] - a[1]) / along;
    const p = side * 0.5;
    const points = [
      [mx + dx * p, my + dy * p],
      [mx - dx * p * 0.6 - dy * p * 0.55, my - dy * p * 0.6 + dx * p * 0.55],
      [mx - dx * p * 0.6 + dy * p * 0.55, my - dy * p * 0.6 - dx * p * 0.55],
    ];
    return `<path d="M${points.map(q => q[0].toFixed(1) + ' ' + q[1].toFixed(1))
      .join('L')}Z" fill="${COLOR}" stroke="${RIM}" stroke-width="${(side * 0.12).toFixed(1)}"/>`;
  };

  const draw = (road) => {
    const box = document.querySelector('.km-drag');
    if (!box) return;
    const svg = box.querySelector('svg');
    if (!svg) return;
    let g = svg.querySelector('#km-current');
    let html = '';
    if (road && road.length > 1) {
      const points = road.map(c => network.nodes[c]);
      const line = 'M' + points.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('L');
      const side = network.side || 20;
      html = `<path d="${line}" fill="none" stroke="${RIM}" `
           + `stroke-width="${(side * 0.42).toFixed(1)}" stroke-linecap="round" `
           + `stroke-linejoin="round" stroke-opacity="0.55"/>`
           + `<path d="${line}" fill="none" stroke="${COLOR}" `
           + `stroke-width="${(side * 0.24).toFixed(1)}" stroke-linecap="round" `
           + `stroke-linejoin="round"/>`;
      for (let i = 0; i + 1 < points.length; i++) {
        html += tip(points[i], points[i + 1], side);
      }
    }
    if (!html) {
      if (g) { g.remove(); drawn = null; }
      return;
    }
    if (!g) {
      g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('id', 'km-current');
      svg.appendChild(g);
      drawn = null;
    }
    // The comparison is with what *we wrote*, not with the innerHTML read
    // back: the browser re-serialises it its own way and it would never
    // match, and rewriting at every round makes the drawing flicker.
    if (drawn === html) return;
    g.innerHTML = html;
    drawn = html;
  };

  window.addEventListener('mousemove', (e) => {
    if (!activate() || !network.from) { return; }
    const box = e.target.closest ? e.target.closest('.km-drag') : null;
    if (!box) return;
    const point = imageCoords(box, e);
    if (!point) return;
    const until = nearest(point);
    draw(until ? course(network.from, until) : null);
  });

  // The server sends the network when it changes, and switches it off when
  // the brush changes hands: without this the guide would stay on under
  // another mode.
  window.kmCurrent = (data) => {
    network = data || null;
    if (!network || !network.active) { network = null; neighbours = null; draw(null); return; }
    buildNeighbours();
    if (!network.from) draw(null);
  };
})();
