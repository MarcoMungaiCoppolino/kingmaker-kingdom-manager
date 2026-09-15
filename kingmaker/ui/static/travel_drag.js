// Dragging the travel arrow, like the Roll20 ruler.
//
// The server sends `window.kmTravelField` once: the geometry of the walkable
// hexes, what entering each costs, and for every traveller what reaching it
// costs them. From that moment the drawing is all in here: while the mouse
// moves no request leaves, and the arrow stays behind the hand instead of
// chasing it.
//
// With a single traveller the course is not always the shortest, and on
// purpose: as soon as you press, the arrow takes the cheapest way, but if you
// keep dragging hex by hex it follows the hand even when that is longer.
// Going back over your own steps shortens it.
//
// With several scattered travellers the ruler also shows where they meet: the
// browser redoes the same arithmetic as the server — a backwards Dijkstra
// from the destination and the rendezvous-point formula — and draws the roads
// joining. There too the hand guides, but it guides the road made as one: the
// meeting point and the approach branches are decided when you press and then
// stay still, because with a single mouse three courses cannot be guided
// together.
//
// The left button traces, the right keeps panning the map: they can be held
// together, and it is the way to extend a journey beyond the edge of the
// screen without letting go of the arrow.
(() => {
  const COLOR = '#7fc3e8';
  const BRANCH_COLOR = '#9fd8f5';   // the approach roads, fainter
  const THRESHOLD = 4;                // px below which it was a click, not a drag
  const WAIT = 260;              // ms of still pressure that count as a drag
  const MAX_STEPS = 400;
  const MAX_FILL = 4;   // hexes the hand can skip in one go
  // How long the hand must stay in a new cell before the arrow enters it.
  // Without it, the cell was chosen by the nearest center at every move, and
  // the border between two cells is the side of the hex: a pixel of jitter
  // crossed it. On a side it went unnoticed — re-entering the cell you leave
  // shortens — but on a **vertex** three cells touch, and circling around it
  // by a few pixels lengthened the course by three steps per loop, without
  // anyone asking.
  const HALT = 90;                // ms still in the new cell to enter it
  // Whoever enters well inside waits for nothing: jitter lives on the edges,
  // and whoever passes near the center has already said where they want to
  // go. It serves not to slow down a running hand: without it a quick sweep
  // would commit no cell and the road would then be **filled** by the
  // cheapest course, which is not the one the finger followed.
  const INSIDE = 0.3;              // share of the step within which one enters at once
  // On the water the hand guides by **edges**, not by nearest point: from
  // the last junction only the lines leaving it are candidates, and a line
  // is taken only once the cursor has travelled a good part of it. At a
  // confluence nothing is chosen while the hand hovers on the vertex: it
  // must go into a line before the arrow follows it there.
  const COMMIT = 0.65;             // share of a side travelled before its junction is taken
  const BACK = 0.5;                // share travelled back along a side before its junction is undone
  const OFF_LINE = 0.5;            // in junction spacings: beyond it a line is not armed
  const RUN_AHEAD = 1.0;           // in junction spacings: beyond it from every line the fill takes over
  const EDGE_HOPS = 4;             // inner junctions a line may cross: a chord is four pieces
  // The same rules in screen pixels: what a hand can do does not shrink with
  // the zoom. Below PX_FINE a side is no longer a step a hand can mean, and
  // the line is taken as a whole.
  const PX_COMMIT = 8;             // least travel, on screen, before a junction is taken
  const PX_OFF = 10;               // least off-line tolerance, on screen
  const PX_FINE = 12;              // shortest side, on screen, still guided junction by junction

  let state = null;
  let neighbours = null;               // adjacencies, computed once per field
  let perField = null;             // the field they were computed on
  let sides = null;                 // extra cost per side
  let banks = null;               // "col,row" -> the cells of that hex
  let graphs = null;                // "col,row" -> the atom graph, expanded

  const field = () => window.kmTravelField;

  const active = () => {
    const c = field();
    return !!(c && c.active && c.cells && c.cells.length &&
              c.travellers && c.travellers.length);
  };

  const inGroup = () => active() && field().travellers.length > 1 && field().together;

  // «Travel together» off with more than one: there is not one journey, there
  // are as many as the travellers. The ruler shows them all together — it is
  // the point of the mode: a single gesture to start every separate
  // departure, instead of redoing the same manoeuvre once per person.
  const eachAlone = () => active() && field().travellers.length > 1 &&
                            !field().together;

  // ------------------------------------------------------------- geometry
  // The cell pointed at by the mouse is the one with the nearest point, full
  // stop: every cell has its own — a shore is the centroid of its piece of
  // hex — so pointing at the bank across the water is a gesture like any
  // other. If there is no way through, the step will say so, with the red
  // arrow and the reason written; it is not this function's job to pretend
  // you pointed at something else.
  const nearestIndex = (x, y) => {
    const cells = field().cells;
    let best = -1, minimum = Infinity;
    for (let i = 0; i < cells.length; i++) {
      const dx = cells[i][2] - x, dy = cells[i][3] - y;
      const d = dx * dx + dy * dy;
      if (d < minimum) { minimum = d; best = i; }
    }
    if (best < 0) return best;
    // On the water several points can fall on exactly the same spot: it is
    // the same vertex seen from two hexes. Among those the cheapest is
    // taken, which is a stable choice — it does not depend on where the hand
    // comes from.
    if (field().water) {
      const from_ = field().travellers[0].from;
      const here_ = fromWhere();
      let chosen = best, attached = false;
      for (let i = 0; i < cells.length; i++) {
        const dx = cells[i][2] - x, dy = cells[i][3] - y;
        if (dx * dx + dy * dy > minimum + 0.01) continue;
        const here = from_[i], better = from_[chosen];
        if (here === null || here === undefined) continue;
        // Guiding by hand, among overlapping points the one attached to where
        // one is wins: it is the step the hand is making.
        const nearMe = here_ >= 0 && adjacent(here_, i);
        if (nearMe && !attached) { chosen = i; attached = true; continue; }
        if (attached) continue;
        if (better === null || better === undefined || here < better) chosen = i;
      }
      return chosen;
    }
    // The shores of a cut hex now have one point each — the centroid of
    // their piece of hex — so the nearest to the mouse is simply the one you
    // are pointing at. Before, both sat at the center and one had to be
    // picked by force: the one attached to where you were was taken, which
    // meant the other shore could not be pointed at at all. To pass a bridge
    // one had to hit its icon, and if the hand passed beyond the arrow stayed
    // on this side without a word.
    return best;
  };

  // Who touches whom is told by the server, and no longer deduced from the
  // distance between the centers. The reason is that a cell is no longer a
  // hex: where a river crosses it, its two banks are two cells *with the same
  // center*, and geometry alone could no longer tell them apart. So the ruler
  // knows where one passes knowing nothing about rivers: the closed sides
  // simply do not appear among the neighbours.
  const buildSides = () => {
    const m = new Map();
    for (const [i, j, cost] of field().sides || []) m.set(i + ':' + j, cost);
    return m;
  };

  // The cells on the same hex: a single one almost everywhere, two where the
  // river cuts. It no longer serves to pick the shore under the mouse — the
  // point says that — but it serves where one reasons by **hexes**: a
  // destination is a hex, and reaching it from one shore or the other is
  // reaching it.
  const buildBanks = () => {
    const m = new Map();
    field().cells.forEach((c, k) => {
      const key = c[0] + ',' + c[1];
      if (!m.has(key)) m.set(key, []);
      m.get(key).push(k);
    });
    return m;
  };

  const hexCells = (cell) => {
    adjacencies();
    const c = field().cells[cell];
    return banks.get(c[0] + ',' + c[1]) || [cell];
  };

  const adjacencies = () => {
    if (!neighbours || perField !== field()) {
      sides = buildSides();
      banks = buildBanks();
      neighbours = field().neighbours || [];
      graphs = new Map();
      perField = field();
    }
    return neighbours;
  };

  // How much more passing from a cell to the neighbour costs: zero almost always.
  const extraSide = (a, b) => {
    if (!sides) adjacencies();
    return sides.get(a + ':' + b) || 0;
  };

  // What **one step** costs, from a cell to the neighbour. A single place
  // that knows it, and the same rule as the server.
  //
  // Normally the hex entered is paid, plus what the side costs (a ford). But
  // between the two banks of the same hex — the two shores a bridge joins —
  // no new hex is entered: only the crossing is paid, which is often zero.
  // The ruler instead charged the hex too, and then its count did not match
  // the server's: at the bridge the backwards course found no good candidate
  // any more and stopped there. Holding the button one saw only the piece
  // after the bridge, and the rest appeared only on release — when the server
  // answers, which counts the bridge right.
  const sameHex = (a, b) => {
    const cells = field().cells;
    return cells[a][0] === cells[b][0] && cells[a][1] === cells[b][1];
  };

  const stepCost = (from, a) => {
    const cells = field().cells;
    // A step **inside** a hex costs **a quarter** of that hex, not zero. Zero
    // was a counting error dressed up as a right rule: it is true that the
    // hex is paid on entering, but passing from one shore to the other is
    // still walking, and it is a quarter of a hex — the same coin the server
    // counts atoms with (chapter 12 of the water document: entering an atom
    // costs a quarter).
    //
    // At zero, a hex with three shores and three crossings could be circled
    // forever without the count rising at all. The possibility of crossing
    // several times was not removed — it is needed, to reach a piece not
    // touching the side you entered from — its price was set: four steps
    // inside a hex make one activity, like crossing it.
    const entrance = cells[a][5] || 0;
    const entry = sameHex(from, a) ? entrance / 4 : entrance;
    return entry + extraSide(from, a);
  };

  // Backwards Dijkstra from the destination: what reaching it costs from
  // every hex. Entering a hex one pays its cost, so going back one pays the
  // one one comes from — the same rule as the server.
  const towardsTarget = (meta) => {
    const cells = field().cells;
    const nb = adjacencies();
    const costs = new Array(cells.length).fill(null);
    // The destination is a *hex*, not a bank: reaching it from one shore or
    // the other is reaching it. One starts from all its cells at zero cost,
    // which is exactly what the server does.
    const queue = [];
    for (const i of hexCells(meta)) { costs[i] = 0; queue.push([0, i]); }
    while (queue.length) {
      queue.sort((a, b) => a[0] - b[0]);
      const [cost, here] = queue.shift();
      if (cost > costs[here]) continue;
      for (const other of nb[here]) {
        const fresh = cost + stepCost(other, here);
        if (costs[other] === null || fresh < costs[other]) {
          costs[other] = fresh;
          queue.push([fresh, other]);
        }
      }
    }
    return costs;
  };

  // From a point to the origin going down the distances, one hex at a time.
  //
  // Which entry is dropped depends on how the field is built, and the two
  // directions are not equivalent. In a forward field (what reaching here
  // costs starting from me) the last step was entering `here`, so the cost of
  // `here` is removed. In a backwards field (what reaching the destination
  // from here costs) the step is entering the *neighbour*, and that one's
  // cost must be removed: using the cost of `here` anyway works only as long
  // as the two hexes cost the same, and at the first difference of terrain it
  // finds nobody and the leg stops there.
  // Among the candidates the one that *goes down the most* wins, and a cell
  // already passed through is not taken again. It is no pedantry: two points
  // of the same hex are joined by a step that costs nothing — the water
  // crossing it, the bridge hopping over it — and with a zero-cost step «go
  // back while the distance drops» never drops. Without these two lines the
  // course bounced between the same two points up to the guard, and the arrow
  // did not appear at all.
  const climbBack = (dists, arrival, back) => {
    const nb = adjacencies();
    const steps = [arrival];
    const seen = new Set([arrival]);
    let here = arrival, guard = 0;
    while (dists[here] > 0 && guard++ < MAX_STEPS) {
      const good = (a) => !seen.has(a) && (back
        ? dists[a] !== null && dists[a] !== undefined &&
          dists[a] === dists[here] - stepCost(here, a)
        : dists[a] === dists[here] - stepCost(a, here));
      let before;
      for (const a of (nb[here] || [])) {
        if (!good(a)) continue;
        if (before === undefined || dists[a] < dists[before]) before = a;
      }
      if (before === undefined) break;
      steps.push(before);
      seen.add(before);
      here = before;
    }
    return steps.reverse();
  };

  // --------------------------------------------------------------- rendezvous
  // The same formula as the server: first make nobody late, then meet as
  // soon as possible. So the dragged arrow and the plan appearing afterwards
  // do not tell two different stories.
  // The pace of the united group is decided by the server and arrives inside
  // the field. Normally it is the slowest member's, as the rule wants, but if
  // the table gets everyone aboard it is the vehicle's — and that cannot be
  // derived from the single travellers, because none of them goes that fast
  // alone. The minimum stays as a safety net for old fields.
  const paceTogether = () => field().activities_per_day ||
                             Math.min(...field().travellers.map((v) => v.activities));

  // The distances coming from the server are in the server's scale: to say
  // them in days they must be brought back to activities.
  const inActivities = (n) => n / scale();

  // The cost of a leg is the sum of the entries: the hex entered is paid, not
  // the one left from, so the first does not count.

  // What an activity is worth in the numbers coming from the server. Normally
  // one: an activity is an activity. Not in the water field — there a step
  // inside the same hex costs nothing (the bend crossing it, the bridge
  // hopping over it), and a course made of zero-cost steps cannot be walked
  // backwards: «go down while the distance drops» never drops. The server
  // then counts in hundredths and adds a hundredth per step, so every step
  // costs something and the course is found again; here one goes back to
  // activities.
  const scale = () => (field() && field().scale) || 1;

  // ------------------------------------------------------ the atom count
  // The hex is divided into 24 fixed atoms, the same for all: their geometry
  // arrives **once** (`field().atoms`). For every cut hex a mask arrives —
  // which of the 36 borders the water closes — with the openings (crossings
  // and fords) and the shore of every atom. From there the graph is rebuilt:
  // one passes by side if the border is open or reopened, and by **point** if
  // no water reaches that point. It is the copy of `atoms.graph` in Python,
  // line by line, and bench `bench10` compares it on all 1561 configurations.
  const hexKey = (cell) => {
    const c = field().cells[cell];
    return c[0] + ',' + c[1];
  };

  const graphOf = (key) => {
    adjacencies();
    if (graphs.has(key)) return graphs.get(key);
    const entry = (field().masks || {})[key];
    const geo = field().atoms;
    if (!entry || !geo) { graphs.set(key, null); return null; }
    const [mask, openings, shores, center] = entry;
    const closed = (n) => Math.floor(mask / Math.pow(2, n)) % 2 === 1;
    const open_ = new Set(openings.map((a) => a[0]));
    const toll = new Map();
    for (const [n, cost] of openings) {
      const [u, d] = geo.sides[n];
      toll.set(u + ':' + d, cost);
      toll.set(d + ':' + u, cost);
    }
    const nb = geo.points.map(() => new Set());
    geo.sides.forEach(([u, d], n) => {
      if (closed(n) && !open_.has(n)) return;
      nb[u].add(d); nb[d].add(u);
    });
    for (const [who, incident] of geo.crossings_) {
      // A bridge opens its stretch, not the point where it ends: the river
      // still passes there. So the jumps by point look at the real water.
      if (incident.some(closed)) continue;
      for (const u of who) for (const d of who) if (u !== d) nb[u].add(d);
    }
    const perShore = new Map();
    for (let a = 0; a < shores.length; a++) {
      const k = Number(shores[a]);
      if (!perShore.has(k)) perShore.set(k, new Set());
      perShore.get(k).add(a);
    }
    // Neighbours in ascending order, as the server walks them.
    const g = {nb: nb.map((s) => Array.from(s).sort((a, b) => a - b)),
               toll, perShore, center};
    graphs.set(key, g);
    return g;
  };

  // The shortest course inside a hex that touches **those waypoints, in that
  // order**, from an atom to another (or to none in particular). It is
  // `atoms.course_by_waypoints`: layered Dijkstra, state = (atom, waypoints done).
  const courseByWaypoints = (g, fromAtom, waypoints, toAtom, quarter, vincolate) => {
    const count = waypoints.length;
    const layerAfter = (atom, layer) =>
      (layer < count && waypoints[layer].has(atom)) ? layer + 1 : layer;
    // With constrained waypoints — the row of shores the hand touched, the
    // first included — between a waypoint and the next no third one is
    // entered: the road is its own, the count only asks it to be the shortest
    // among those making that tour.
    const allowed = (other, layer) => {
      if (!vincolate || !count) return true;
      if (layer && waypoints[layer - 1].has(other)) return true;
      return layer < count && waypoints[layer].has(other);
    };
    const key = (a, st) => a + ':' + st;
    const departure = [fromAtom, layerAfter(fromAtom, 0)];
    const bestOnes = new Map([[key(...departure), 0]]);
    const before = new Map([[key(...departure), null]]);
    const queue = [[0, departure]];
    while (queue.length) {
      // At equal cost the atom with the lowest number wins, then the layer:
      // the same tie-break as the server, or at equal cost two different
      // courses would be drawn.
      queue.sort((x, y) => (x[0] - y[0]) || (x[1][0] - y[1][0]) || (x[1][1] - y[1][1]));
      const [cost, state] = queue.shift();
      const [atom, layer] = state;
      if (cost > bestOnes.get(key(atom, layer))) continue;
      if (layer === count && (toAtom === null || atom === toAtom)) {
        const outside = [atom];
        let k = key(atom, layer);
        while (before.get(k) !== null) {
          const p = before.get(k);
          outside.push(p[0]);
          k = key(p[0], p[1]);
        }
        outside.reverse();
        return {cost, atoms: outside};
      }
      for (const other of g.nb[atom]) {
        if (!allowed(other, layer)) continue;
        const after = [other, layerAfter(other, layer)];
        const kd = key(...after);
        const fresh = cost + quarter + (g.toll.get(atom + ':' + other) || 0);
        if (!bestOnes.has(kd) || fresh < bestOnes.get(kd)) {
          bestOnes.set(kd, fresh);
          before.set(kd, state);
          queue.push([fresh, after]);
        }
      }
    }
    return null;
  };

  // From which side of `a` one enters coming from `from`: the side numbering
  // is that of `hexgrid.neighbours`, and arrives with the field as «compass».
  const sideTowards = (from, a) => {
    const b = field().compass;
    if (!b) return -1;
    const tie = (b.tie === 'row' ? from[1] : from[0]) & 1;
    const steps = b[String(tie)] || [];
    for (let k = 0; k < steps.length; k++) {
      if (from[0] + steps[k][0] === a[0] && from[1] + steps[k][1] === a[1]) return k;
    }
    return -1;
  };

  // The road, waypoint by waypoint: for every hex the cells touched in a row,
  // and — if the hex is cut — the atoms the count crosses and what it costs.
  // A single place the number and the drawing come out of.
  const atomStretches = (indices) => {
    const cells = field().cells;
    const geo = field().atoms;
    const waypoints = [];
    for (const i of indices) {
      const c = cells[i];
      if (waypoints.length && waypoints[waypoints.length - 1].col === c[0] &&
          waypoints[waypoints.length - 1].row === c[1]) {
        waypoints[waypoints.length - 1].cells.push(i);
      } else {
        waypoints.push({col: c[0], row: c[1], cells: [i], atoms: null, extra: 0,
                    entry: 0, toll: 0});
      }
    }
    if (waypoints.length === 1 && waypoints[0].cells.length > 1 && geo) {
      // Inside the departure hex: no hex is entered, only the road from where
      // one is to the aimed piece, through the shores touched.
      const here = waypoints[0];
      const g = graphOf(here.col + ',' + here.row);
      if (g) {
        const shores = [];
        for (const i of here.cells) {
          const r = cells[i][8] || 0;
          if (!shores.length || shores[shores.length - 1] !== r) shores.push(r);
        }
        const sets = shores.map((r) => g.perShore.get(r) || new Set());
        const fromAtom = cells[here.cells[0]][9];
        const toAtom = cells[here.cells[here.cells.length - 1]][9];
        const quarter = (cells[here.cells[0]][5] || 0) / 4;
        let outcome = courseByWaypoints(g, fromAtom, sets, toAtom, quarter, true);
        if (!outcome) outcome = courseByWaypoints(g, fromAtom, [], toAtom, quarter, false);
        if (outcome) { here.atoms = outcome.atoms; here.extra = outcome.cost; }
        else here.extra = null;
      }
      return waypoints;
    }
    for (let t = 1; t < waypoints.length; t++) {
      const here = waypoints[t], before = waypoints[t - 1];
      const firstCell = here.cells[0];
      here.entry = cells[firstCell][5] || 0;
      // The side between the two hexes (a ford on the border): paid on
      // entering, once, and not for every step inside.
      here.toll = extraSide(before.cells[before.cells.length - 1], firstCell);
      const g = graphOf(here.col + ',' + here.row);
      if (!g || !geo) continue;
      const entrance = (sideTowards([before.col, before.row], [here.col, here.row]) + 3) % 6;
      if (entrance < 0 || Number.isNaN(entrance)) continue;
      const fromAtom = geo.edge[entrance];
      // All the shores touched, the first included, once in a row.
      const shores = [];
      for (const i of here.cells) {
        const r = cells[i][8] || 0;
        if (!shores.length || shores[shores.length - 1] !== r) shores.push(r);
      }
      const sets = shores.map((r) => g.perShore.get(r) || new Set());
      let toAtom;
      if (t === waypoints.length - 1) {
        // One stops in the aimed piece: the atom of its shore's point.
        toAtom = cells[here.cells[here.cells.length - 1]][9];
        if (toAtom === undefined) toAtom = null;
      } else {
        const after = waypoints[t + 1];
        const exit = sideTowards([here.col, here.row], [after.col, after.row]);
        if (exit < 0) continue;
        toAtom = geo.edge[exit];
      }
      let outcome = courseByWaypoints(g, fromAtom, sets, toAtom, here.entry / 4, true);
      // A tour that cannot be made from this side: the shortest way counts,
      // as on the server.
      if (!outcome) outcome = courseByWaypoints(g, fromAtom, [], toAtom, here.entry / 4, false);
      if (!outcome) { here.extra = null; continue; }
      here.atoms = outcome.atoms;
      here.extra = Math.max(0, outcome.cost - here.entry * 0.75);
    }
    return waypoints;
  };

  // A number of activities written as a human reads it: in quarters.
  const inQuarters = (x) => {
    const q = Math.round(x * 4);
    const whole = Math.floor(q / 4), rest = q % 4;
    const piece = ['', '¼', '½', '¾'][rest];
    return whole && piece ? whole + piece : (piece || String(whole));
  };

  const legCost = (indices) => {
    if (field().masks && field().atoms) {
      // By atoms: the hex costs what the rules say, plus what lies beyond the
      // four atoms of a straight crossing, plus the ford on the border. The
      // same count as the server (`atom_count`), and not «a quarter per shore
      // hop»: that was an approximation, and on release the number changed.
      let cost = 0;
      const waypoints = atomStretches(indices);
      for (const t of waypoints.slice(1)) {
        cost += t.entry + (t.extra || 0) + t.toll;
      }
      if (waypoints.length === 1) cost += waypoints[0].extra || 0;
      return Math.round(cost * 4) / 4;
    }
    // On the water the cells are river points, not hexes: the count is the
    // sum of the steps, in hundredths.
    let cost = 0;
    for (let i = 1; i < indices.length; i++) {
      cost += stepCost(indices[i - 1], indices[i]);
    }
    // First back to quarters, then up to the whole. Both steps are needed:
    // the real cost is always a multiple of a quarter — an atom side — but
    // inside the scale there is also the thousandth tie-break keeping the
    // courses in order, and that dust, rounded up on its own, raised by a
    // whole activity a journey that did not cost it. It is removed by going
    // back to the nearest quarter.
    const quarters = Math.round((cost / scale()) * 4) / 4;
    return Math.ceil(quarters - 1e-9);
  };

  const rendezvous = (meta) => {
    const c = field();
    const direction = towardsTarget(meta);
    const slowest = paceTogether();
    let best = -1, score = null, bestUnion = 0;
    for (let i = 0; i < c.cells.length; i++) {
      if (direction[i] === null) continue;
      let union = 0, everyone = true;
      for (const v of c.travellers) {
        const d = v.from[i];
        if (d === null || d === undefined) { everyone = false; break; }
        union = Math.max(union, inActivities(d) / v.activities);
      }
      if (!everyone) continue;
      const total = union + direction[i] / slowest;
      const p = [Math.round(total * 1e6), Math.round(union * 1e6)];
      if (score === null || p[0] < score[0] ||
          (p[0] === score[0] && p[1] < score[1])) {
        best = i; score = p; bestUnion = union;
      }
    }
    if (best < 0) return null;
    return {
      point: best,
      days: score[0] / 1e6,
      union: bestUnion,
      branches: c.travellers.map((v) => climbBack(v.from, best)),
      common: climbBack(direction, best, true).reverse(),
    };
  };

  // -------------------------------------------------------------- drawing
  const imageCoords = (box, e) => {
    const img = box.querySelector('img');
    if (!img || !img.naturalWidth) return null;
    const r = img.getBoundingClientRect();
    const scale = img.clientWidth / img.naturalWidth;
    return {x: (e.clientX - r.left) / scale, y: (e.clientY - r.top) / scale};
  };

  const drawingGroup = (box) => {
    const svg = box.querySelector('svg');
    if (!svg) return null;
    let g = svg.querySelector('#km-arrow');
    if (!g) {
      g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('id', 'km-arrow');
      svg.appendChild(g);
    }
    return g;
  };

  // The already decided arrow is drawn by the server inside a group of its
  // own. While a new one is traced we take it away: seeing two together, the
  // old one and the one you are drawing, one cannot tell which is the good
  // one.
  const oldArrow = (box, visible) => {
    const g = box.querySelector('#km-path');
    if (g) g.style.display = visible ? '' : 'none';
  };

  const measure = () => (field() && field().size) || 40;

  // Where an arrow is born: the marker anchor of that cell, which the server
  // sends together with the point. In a cut hex the two coincide — the marker
  // sits at the point of its shore — but in a whole hex the markers sit below
  // the center, and an arrow leaving from the center looks like someone
  // else's road. On the water there is no anchor: a boat leaves from the
  // boarding point, and that is the cell's point.
  const still = (i) => {
    const c = field().cells[i];
    return c.length > 7 ? [c[6], c[7]] : [c[2], c[3]];
  };

  // Cell indices become points: it is the only step that knows about cells,
  // so all the drawing holds for the others' arrows too, which arrive in
  // pixels with no field behind them.
  const inPoints = (indices) => {
    const cells = field().cells;
    if (field().masks && field().atoms && indices.length) {
      // By atoms: the arrow passes through the atoms the count crossed, so
      // what is seen is what is paid. The first waypoint is the leaver's
      // anchor; in whole hexes the cell's point stays; the last ends on the
      // point of the aimed shore, where the marker is placed. It is
      // `course_points` with the stretches, line by line.
      const geo = field().atoms;
      const size = measure();
      const waypoints = atomStretches(indices);
      const outside = [still(indices[0])];
      if (waypoints.length === 1 && waypoints[0].atoms) {
        const g = graphOf(waypoints[0].col + ',' + waypoints[0].row);
        for (const a of waypoints[0].atoms.slice(1)) {
          outside.push([g.center[0] + geo.points[a][0] * size,
                      g.center[1] + geo.points[a][1] * size]);
        }
        const lastOne = indices[indices.length - 1];
        outside.push([cells[lastOne][2], cells[lastOne][3]]);
        return outside;
      }
      for (let t = 1; t < waypoints.length; t++) {
        const g = graphOf(waypoints[t].col + ',' + waypoints[t].row);
        if (waypoints[t].atoms && g) {
          for (const a of waypoints[t].atoms) {
            outside.push([g.center[0] + geo.points[a][0] * size,
                        g.center[1] + geo.points[a][1] * size]);
          }
        } else {
          const lastOne = waypoints[t].cells[waypoints[t].cells.length - 1];
          outside.push([cells[lastOne][2], cells[lastOne][3]]);
        }
      }
      const final = waypoints[waypoints.length - 1];
      if (waypoints.length > 1 && final.atoms) {
        const lastOne = final.cells[final.cells.length - 1];
        outside.push([cells[lastOne][2], cells[lastOne][3]]);
      }
      return outside;
    }
    // Only the **first** point is the anchor, and it is the same rule as the
    // server (`course_points`: `spot == 0`). A course may pass through the
    // departure cell again further on, and that is a waypoint like the others.
    return indices.map((i, spot) => (spot === 0 ? still(i)
                                                 : [cells[i][2], cells[i][3]]));
  };

  // How many stretches at the end take the fade, and how much of the colour
  // remains in the rest of the line. Since a course can cross itself, two
  // overlapping lines are indistinguishable: one does not know which of the
  // two was just drawn, and therefore not even which way to go back.
  //
  // The queue is **short** on purpose. Fading over fourteen stretches the
  // difference between one and the next was nothing, and precisely where it
  // matters — the last two or three — it did not show: on a long journey the
  // line looked all the same. Now the jump is sharp: three live stretches at
  // the end, and all the rest dimmed the same way. What is read is not «how
  // old is this piece», which serves nobody, but «where did I just come
  // from», which is the only question the hand asks.
  const QUEUE = 3;
  const OFF = 0.4;              // how much colour remains in the rest of the line
  const SHADOW = [11, 16, 21];      // the black of the outline: that is where it fades out

  // Blends a colour towards the shadow. `howMuch` goes from 0 (all shadow) to 1 (full).
  const blend = (color, howMuch) => {
    const s = String(color || '').trim();
    let r, g, b;
    if (/^#[0-9a-f]{6}$/i.test(s)) {
      r = parseInt(s.slice(1, 3), 16);
      g = parseInt(s.slice(3, 5), 16);
      b = parseInt(s.slice(5, 7), 16);
    } else if (/^#[0-9a-f]{3}$/i.test(s)) {
      r = parseInt(s[1] + s[1], 16);
      g = parseInt(s[2] + s[2], 16);
      b = parseInt(s[3] + s[3], 16);
    } else {
      return color;               // a colour I cannot read stays as it is
    }
    const q = Math.max(0, Math.min(1, howMuch));
    const merge = (c, o) => Math.round(o + (c - o) * q);
    return `rgb(${merge(r, SHADOW[0])},${merge(g, SHADOW[1])},${merge(b, SHADOW[2])})`;
  };

  const thread = (points, color, thickness) =>
    `<path d="M${points.map((p) => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L')}"` +
    ` fill="none" stroke="${color}" stroke-width="${thickness.toFixed(1)}"` +
    ` stroke-linecap="round" stroke-linejoin="round"/>`;

  const trace = (points, color, thickness) => {
    if (points.length < 2) return '';
    const d = 'M' + points.map((p) => p[0].toFixed(1) + ' ' + p[1].toFixed(1))
                         .join(' L');
    // The outline stays a single line: it is the arrow's shadow, not the
    // sign, and fading it together with the colour would make it look thinner
    // at the end.
    let outside = `<path d="${d}" fill="none" stroke="#0b1015" stroke-width="${(thickness * 1.6).toFixed(1)}"` +
                ` stroke-linecap="round" stroke-linejoin="round" stroke-opacity="0.55"/>`;
    const last = points.length - 1;
    const first = Math.max(0, last - QUEUE);
    // Everything before the queue is equally old: a single line, dimmed. So
    // a long course does not become four hundred nodes in the SVG.
    if (first > 0) outside += thread(points.slice(0, first + 1), blend(color, OFF), thickness);
    for (let i = first; i < last; i++) {
      const howMany = last - first;
      const t = howMany <= 1 ? 1 : (i - first + 1) / howMany;
      outside += thread([points[i], points[i + 1]], blend(color, OFF + (1 - OFF) * t),
                    thickness);
    }
    return outside;
  };

  const tip = (points, color, size) => {
    if (points.length < 2) return '';
    const a = points[points.length - 2], b = points[points.length - 1];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    const dx = (b[0] - a[0]) / len, dy = (b[1] - a[1]) / len;
    const p = size * 0.42;
    const bx = b[0] - dx * p * 0.55, by = b[1] - dy * p * 0.55;
    const a1 = [bx - dy * p * 0.42, by + dx * p * 0.42];
    const a2 = [bx + dy * p * 0.42, by - dx * p * 0.42];
    return `<path d="M${b[0].toFixed(1)} ${b[1].toFixed(1)} L${a1[0].toFixed(1)} ${a1[1].toFixed(1)}` +
           ` L${a2[0].toFixed(1)} ${a2[1].toFixed(1)} Z" fill="${color}" stroke="#0b1015"` +
           ` stroke-width="${(size * 0.03).toFixed(1)}" stroke-linejoin="round"/>`;
  };

  // Everything ending up inside an innerHTML passes through here: the
  // characters' names and the arrows' captions are written by whoever plays,
  // and a name with a tag inside would run in everyone else's browser.
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  const tagLabel = (text, cx, cy, edge, size) => {
    text = String(text == null ? '' : text);
    const wide = (text.length * 0.62 + 0.8) * size * 0.3;
    const top_ = size * 0.51;
    return `<rect x="${(cx - wide / 2).toFixed(1)}" y="${(cy - top_ / 2).toFixed(1)}"` +
           ` width="${wide.toFixed(1)}" height="${top_.toFixed(1)}" rx="${(top_ / 2).toFixed(1)}"` +
           ` fill="#0b1015e6" stroke="${edge || COLOR}" stroke-width="${(size * 0.027).toFixed(2)}"/>` +
           `<text x="${cx.toFixed(1)}" y="${(cy + size * 0.108).toFixed(1)}" text-anchor="middle"` +
           ` font-size="${(size * 0.3).toFixed(1)}" fill="#e9e0cf" font-weight="700"` +
           ` font-family="Cinzel, Georgia, serif">${esc(text)}</text>`;
  };

  // The sign of the meeting point: a dashed circle where the roads join.
  const circle_ = (point, color, size) => {
    return `<circle cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}"` +
           ` r="${(size * 0.2).toFixed(1)}" fill="none" stroke="${color}"` +
           ` stroke-width="${(size * 0.05).toFixed(1)}"` +
           ` stroke-dasharray="${(size * 0.09).toFixed(1)} ${(size * 0.07).toFixed(1)}"/>`;
  };

  const unknownOn = (indices) => {
    const cells = field().cells;
    return indices.some((i) => cells[i][4] === 1);
  };

  // The colour of whoever holds the mouse. It arrives with the field: at the
  // table the arrows are many, and recognising one's own by colour is worth
  // more than a blue equal for everyone.
  const myColor = () => (inFlash() ? RED
                           : (field() && field().player_color) || COLOR);

  // The labels, all from here: the same text goes to whoever watches from
  // another window too, and two different figures on the same journey would
  // be two journeys.
  // The words come with the field, in the language of this window; the
  // server writes the same figures with the same patterns (`plan_text`).
  const texts = () => (field() && field().texts) ||
    {day_one: '{n} day', day_other: '{n} days', plan_full: '{cost} act · {days}', max: 'max '};
  const daysText = (n) => (n === 1 ? texts().day_one : texts().day_other).replace('{n}', n);

  const legText = (steps, perDay) => {
    const cost = legCost(steps);
    const days = perDay > 0 ? Math.ceil(cost / perDay - 1e-9) : 0;
    return (unknownOn(steps) ? texts().max : '') +
           texts().plan_full.replace('{cost}', inQuarters(cost)).replace('{days}', daysText(days));
  };

  const groupText = (r) => {
    const touch = r.common.concat(...r.branches);
    return (unknownOn(touch) ? texts().max : '') +
           daysText(Math.ceil(r.days - 1e-9));
  };

  const separateText = (entry) => {
    const cost = legCost(entry.steps);
    const days = entry.activities > 0 ? Math.ceil(cost / entry.activities) : 0;
    return entry.name + ' · ' + (unknownOn(entry.steps) ? texts().max : '') +
           daysText(days);
  };

  // An approach branch ends **on the anchor** of the meeting point: where the
  // circle is and where the common road starts from. Without it, the branch
  // ended on the cell's point and the common road started from the anchor,
  // and the two arrows did not touch. Same rule as the server (`_svg_branches`).
  const branchPoints = (branch, meetingPoint) => {
    const points = inPoints(branch);
    if (points.length) points[points.length - 1] = still(meetingPoint);
    return points;
  };

  const drawGroup = (group, r) => {
    const size = measure();
    const cells = field().cells;
    const mine = myColor();
    let html = '';
    for (const branch of r.branches) html += trace(branchPoints(branch, r.point), BRANCH_COLOR, size * 0.05);
    for (const branch of r.branches) html += tip(branchPoints(branch, r.point), BRANCH_COLOR, size);
    // The circle of the meeting point sits where the server puts it, i.e. on
    // the anchor: it is the spot where they meet, and it is from there that
    // the common road leaves again.
    html += circle_(still(r.point), BRANCH_COLOR, size);
    html += trace(inPoints(r.common), mine, size * 0.085) +
            tip(inPoints(r.common), mine, size);
    const end = r.common.length > 1 ? r.common[r.common.length - 1] : r.point;
    html += tagLabel(groupText(r), cells[end][2],
                      cells[end][3] - size * 0.72, mine, size);
    write(group, html);
  };

  // Rewriting the same drawing at every mouse move makes the arrow flicker:
  // the browser throws the nodes away and redoes them. What was written is
  // kept aside and rewritten only if it changed — the comparison must be made
  // with what *we wrote*, not with the innerHTML read back, which the browser
  // re-serialises its own way and would never match.
  //
  // Whoever draws in the group must **always** pass through here, even when
  // the comparison is of no use to them. Two functions wrote the innerHTML on
  // their own, and the log stayed behind: it said «there is nothing in there»
  // while the arrows were on screen. At the end of the gesture, `write(g,'')`
  // found that «nothing» already written and did not touch the map — and the
  // arrows of a journey of two or more stayed on the map forever: choosing
  // someone else did not take them away, leaving Travel neither.
  const written = new WeakMap();

  const write = (group, html) => {
    if (written.get(group) === html) return;
    group.innerHTML = html;
    written.set(group, html);
  };

  const drawSingle = (group, steps) => {
    const cells = field().cells;
    const size = measure();
    const mine = myColor();
    const perDay = field().travellers[0].activities || 1;
    if (steps.length < 2) { write(group, ''); return; }
    const end = steps[steps.length - 1];
    write(group, trace(inPoints(steps), mine, size * 0.08) +
      tip(inPoints(steps), mine, size) +
      armedPreview(mine, size) +
      tagLabel(legText(steps, perDay),
                cells[end][2], cells[end][3] - size * 0.72, mine, size));
  };

  // The edge the hand is travelling into but has not taken yet: a dashed
  // thread from the last junction to where the cursor projects on it. One
  // sees which line is about to be taken before it is, and the arrow does
  // not look frozen while the hand earns the step.
  const armedPreview = (color, size) => {
    const armed = state && state.armed;
    if (!armed || armed.points.length < 2) return '';
    const d = 'M' + armed.points.map((p) => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L');
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${(size * 0.05).toFixed(1)}"` +
           ` stroke-dasharray="${(size * 0.12).toFixed(1)} ${(size * 0.1).toFixed(1)}"` +
           ` stroke-linecap="round" stroke-linejoin="round" stroke-opacity="0.85"/>`;
  };

  const drawSeparate = (group, listing) => {
    const cells = field().cells;
    const size = measure();
    let html = '', labels = '', count = 0;
    for (const entry of listing) {
      if (entry.steps.length < 2) continue;
      html += trace(inPoints(entry.steps), entry.color, size * 0.07) +
              tip(inPoints(entry.steps), entry.color, size);
      const end = cells[entry.steps[entry.steps.length - 1]];
      // The labels stack: the paths all end on the same cell, and one over
      // the other they would not be readable.
      labels += tagLabel(separateText(entry),
                             end[2], end[3] - size * (0.72 + 0.62 * count),
                             entry.color, size);
      count++;
    }
    write(group, html + labels);
  };

  // ------------------------------------------ the arrow seen by the others
  // While one drags, the others see the same road appear on their map, with
  // the name of whoever is drawing it. Before, the arrow was a private matter
  // and the others got only the journey already decided: at the table it
  // meant discussing a route looking at a still map.
  const TRACE_PACE = 90;        // ms between one send and the next
  let lastSend = 0;
  let pendingSend = null;

  const whoLeaves = () => (active() ? field().travellers.map((v) => v.id) : []);

  // The arrows as the others see them: the road in hexes and the label
  // hanging from it. The label is the same read here, and the days are the
  // reason one looks at someone else's arrow.
  const currentArrows = () => {
    const outside = {stretches: [], labels: []};
    if (!state || !active()) return outside;
    // The others are sent **the polyline in pixels** — the same this window
    // draws, atoms included — and not the row of hexes: so whoever watches
    // sees what whoever drags sees, even inside a single hex.
    const inHex = (indices) => inPoints(indices).map(
      (p) => [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10]);
    let roads = [], captions = [];
    if (inGroup()) {
      if (!state.rendezvous) return outside;
      roads = [state.rendezvous.common].concat(state.rendezvous.branches);
      captions = [groupText(state.rendezvous)].concat(state.rendezvous.branches.map(() => ''));
      // The branches end on the anchor of the meeting point for the watcher too.
      roads.forEach((s, i) => {
        if (i > 0 && s.length > 1) {
          outside.stretches.push(branchPoints(s, state.rendezvous.point).map(
            (p) => [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10]));
          outside.labels.push('');
        }
      });
      const common = roads[0];
      if (common.length > 1) {
        outside.stretches.unshift(inHex(common));
        outside.labels.unshift(captions[0]);
      } else if (outside.labels.length) {
        // The meeting point is the destination: the days go on the first
        // branch, which ends right there. Same rule as the server
        // (`_trace_from_plan`).
        outside.labels[0] = captions[0];
      }
      return outside;
    } else if (eachAlone()) {
      for (const entry of state.separate || []) {
        roads.push(entry.steps);
        captions.push(entry.steps.length > 1 ? separateText(entry) : '');
      }
    } else {
      roads = [state.steps];
      captions = [state.steps.length > 1
        ? legText(state.steps, field().travellers[0].activities || 1) : ''];
    }
    roads.forEach((s, i) => {
      if (s.length > 1) { outside.stretches.push(inHex(s)); outside.labels.push(captions[i]); }
    });
    return outside;
  };

  // Paced, not at every move: the mouse produces dozens a second and the
  // drawing stays smooth anyway, because it is always the dragger's browser
  // that draws. What is sent is the polyline — a few dozen pairs of numbers —
  // not the drawing.
  const sendTrace = (immediately) => {
    if (typeof emitEvent !== 'function') return;
    const dispatch = () => {
      lastSend = performance.now();
      pendingSend = null;
      const arrows = currentArrows();
      emitEvent('km_live_trace', {stretches: arrows.stretches,
                                    labels: arrows.labels,
                                    blocked: inFlash(),
                                    pc: whoLeaves()});
    };
    if (immediately) {
      if (pendingSend) { clearTimeout(pendingSend); pendingSend = null; }
      dispatch();
      return;
    }
    if (pendingSend) return;
    const remains = TRACE_PACE - (performance.now() - lastSend);
    if (remains <= 0) dispatch(); else pendingSend = setTimeout(dispatch, remains);
  };

  // What the others are drawing, as it arrives from the server: already in
  // pixels, because the grid calibration is known to it and this window may
  // have no field in hand.
  let others = {size: 40, traces: []};
  let stopFlash = null;

  const othersHtml = () => {
    if (!others.traces.length) return '';
    const size = others.size || 40;
    let html = '', labels = '';
    for (const who of others.traces) {
      let main = null, count = 0;
      // Red here too when it bumped into a river: the why stays with whoever
      // is dragging it — a written warning for every skid of someone else
      // would be a mere nuisance — but *that* it does not pass the whole
      // table sees, and it is the thing being talked about at that moment.
      const color = who.blocked ? RED : who.color;
      who.stretches.forEach((stretch, i) => {
        if (stretch.length < 2) return;
        if (!main) main = stretch;
        html += trace(stretch, color, size * 0.06) +
                tip(stretch, color, size);
        const caption = (who.labels || [])[i];
        if (caption) {
          const end = stretch[stretch.length - 1];
          labels += tagLabel(caption, end[0],
                                 end[1] - size * (0.72 + 0.62 * count),
                                 color, size);
          count++;
        }
      });
      if (main) {
        // The name below the arrow, the figure above: they read together
        // without overlapping the labels of the journey you are making.
        const end = main[main.length - 1];
        labels += tagLabel(who.title, end[0], end[1] + size * 0.78,
                               color, size);
      }
    }
    return html
      ? `<g opacity="0.8">${html}</g>${labels}`
      : '';
  };

  // What is already drawn in each box. Kept here and not read back from
  // `innerHTML`: what the browser returns is its re-serialisation, which never
  // comes back equal to the caption string — and the comparison, always
  // failing, rewrote the group at every round of the observer that brought
  // us here. The page froze.
  const drawn = new WeakMap();

  const drawOthers = () => {
    const html = othersHtml();
    document.querySelectorAll('.km-drag').forEach((box) => {
      const svg = box.querySelector('svg');
      if (!svg) return;
      const g = svg.querySelector('#km-others');
      if (!html) {
        if (g) { drawn.delete(g); g.remove(); }
        return;
      }
      if (g) {
        if (drawn.get(g) !== html) { g.innerHTML = html; drawn.set(g, html); }
        return;
      }
      const fresh = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      fresh.setAttribute('id', 'km-others');
      fresh.innerHTML = html;
      drawn.set(fresh, html);
      svg.appendChild(fresh);
    });
  };

  window.kmOthersTrace = (data) => {
    others = data && data.traces ? data : {size: 40, traces: []};
    drawOthers();
    // The flash lasts as long as it does for whoever draws, and goes out on
    // its own: if that one stops there against the river no other message
    // arrives, and without this the arrow would stay red forever.
    if (others.traces.some((who) => who.blocked)) {
      clearTimeout(stopFlash);
      stopFlash = setTimeout(() => {
        others.traces.forEach((who) => { who.blocked = false; });
        drawOthers();
      }, FLASH);
    }
  };

  // ------------------------------------------- guided course (single one)
  const adjacent = (a, b) => adjacencies()[a].includes(b);

  // When the mouse skips more than one hex, the stretch in between must be
  // filled — but **only straight ahead**, and never going around something.
  //
  // Before, here there was a real course, with the same Dijkstra as the
  // server, and it looked like the most generous choice: any gap could be
  // closed. The result however was that bringing the hand near a river —
  // where the step beyond does not exist — the arrow did not bump into it: it
  // went off looking for the bridge three hexes further, and you found
  // yourself with a road you had not drawn and had to undo by hand. The help
  // was worse than the problem it solved.
  //
  // The rule is now one, and fits in a line: **every step of the filling
  // must get closer to the destination**. A running hand skips two or three
  // hexes in a straight line, and there every step really gets closer; going
  // around a river necessarily means a step that does not get closer, and
  // then nothing is filled — the arrow stops and says why. That is the right
  // answer: there is no way through there, and the long way round is decided
  // by whoever plays, bringing the mouse over one hex at a time.
  const inStraightLine = (from, a) => {
    if (from === a) return [];
    const cells = field().cells;
    const nb = adjacencies();
    const step = field().step || 0;
    if (!step) return [];
    const mx = cells[a][2], my = cells[a][3];
    const howMuch = (i) => Math.hypot(cells[i][2] - mx, cells[i][3] - my);
    const added = [];
    let here = from;
    while (here !== a) {
      if (added.length >= MAX_FILL) return [];
      let chosen = -1, minimum = Infinity;
      for (const other of nb[here]) {
        const d = howMuch(other);
        if (d < minimum) { minimum = d; chosen = other; }
      }
      // «Getting closer» must be by a real step, not by a hair. Hopping a
      // river through the hex beside *gets closer* — by a few thousandths,
      // enough to pass a strict comparison — and it is exactly the detour we
      // do not want: the first check of this rule let it slip by four units
      // out of seventy-eight thousand, i.e. the rounding of the centers. A
      // straight step gains almost a whole hex; half a hex is half of that,
      // and no detour around water gets there.
      if (chosen < 0 || minimum > howMuch(here) - step * 0.5) return [];
      added.push(chosen);
      here = chosen;
    }
    return added;
  };

  // The piece of water between two non-adjacent junctions, if it is short:
  // the road with fewest steps, within MAX_FILL. Without the direction of the
  // current — that is counted by the price, not by the guide: the hand says
  // where, the count says how much.
  const alongWater = (from, a) => {
    if (from === a) return [];
    const nb = adjacencies();
    const fromWhere_ = new Map([[from, -1]]);
    let front = [from];
    for (let step = 0; step < MAX_FILL && front.length; step++) {
      const next = [];
      for (const here of front) {
        for (const other of (nb[here] || [])) {
          if (fromWhere_.has(other)) continue;
          fromWhere_.set(other, here);
          if (other === a) {
            const road = [];
            let x = a;
            while (x !== from) { road.push(x); x = fromWhere_.get(x); }
            return road.reverse();
          }
          next.push(other);
        }
      }
      front = next;
    }
    return [];
  };

  // --------------------------------------------- when there is no way through
  // Until yesterday the arrow just stopped: the hand kept moving and on
  // screen nothing happened, which is the best way to make one believe the
  // app froze. Now it says so in three ways together, because a single one
  // gets lost: the arrow flashes red, the phone vibrates (where vibrating
  // means something) and top right the why appears.
  const RED = '#e0705d';
  const FLASH = 450;               // ms of red arrow
  const WARN_EVERY = 2500;        // ms between one written warning and the next
  let flashUntil = 0;
  let lastWarning = 0;

  const inFlash = () => performance.now() < flashUntil;

  // If the two hexes touch but there is no way between them, there is water
  // in between: it is the only thing that removes an adjacency. Two cells
  // with the same center are the two banks of a hex cut by a river, and it is
  // the same case seen from inside.
  const blockedByWater = (from, a) => {
    const cells = field().cells;
    if (adjacent(a, from)) return false;
    // Same hex, or the next one: the compass says it, exactly. The distance
    // between the points is no longer enough — since every shore has the
    // point of its piece, two shores of the same hex can sit half a hex apart,
    // and the distance count took them for far away: against the water the
    // arrow bumped without saying «water».
    if (sameHex(a, from)) return true;
    const side = sideTowards([cells[from][0], cells[from][1]], [cells[a][0], cells[a][1]]);
    if (side >= 0) return true;
    const step = field().step || 0;
    if (!step) return false;
    const d = Math.hypot(cells[a][2] - cells[from][2], cells[a][3] - cells[from][3]);
    return d < step * 0.25 || Math.abs(d - step) < step * 0.25;
  };

  const reportBlock = (reason) => {
    flashUntil = performance.now() + FLASH;
    redraw();
    sendTrace(true);          // the flash does not wait its turn

    setTimeout(() => { if (state && !inFlash()) redraw(); }, FLASH + 30);
    if (navigator.vibrate) {
      // On the phone one feels it, on the laptop nothing happens: it is one
      // of the three ways, not the only one, precisely for that.
      try {
        navigator.vibrate(reason === 'water' ? [35, 45, 35] : 35);
      } catch (e) { /* nothing */ }
    }
    const now = performance.now();
    if (typeof emitEvent === 'function' && now - lastWarning > WARN_EVERY) {
      lastWarning = now;
      emitEvent('km_travel_blocked',
                {water: reason === 'water', reason: reason || 'ring'});
    }
  };

  // One step of the guided course: lengthens by a hex if it is adjacent,
  // shortens if you went back over your steps, and fills in a straight line
  // if the hand jumped beyond the neighbour. Edits the list in place.
  // ------------------------------------------------ guiding on the water
  const pointOf = (i) => [field().cells[i][2], field().cells[i][3]];
  // A line end: a vertex or a center, where drawn lines meet and bend — or a
  // crossing, an inner junction where more than two sides meet, which is a
  // place to turn. The inner junctions along a line are not places the hand
  // aims at for direction; they are the steps it takes once the line is
  // chosen. A field from before the flag treats every point as an end.
  const isEnd = (i) => {
    const c = field().cells[i];
    if (c.length < 7 || c[6] === 1) return true;
    return (adjacencies()[i] || []).length > 2;
  };
  // About one junction apart: a quarter of a chord.
  const spacing = () => measure() * 0.45;
  // Screen pixels into image pixels. The thresholds are what a hand can do
  // on the screen, and zoomed out the same image distance is fewer pixels.
  let screenScale = 1;
  const px = (n) => n / screenScale;
  const readScale = () => {
    const img = state && state.box ? state.box.querySelector('img') : null;
    screenScale = img && img.naturalWidth ? img.clientWidth / img.naturalWidth : 1;
  };

  // The lines leaving junction `j`: every end reachable through inner
  // junctions only, with the junctions in between. A breadth-first walk that
  // stops at the first end it meets, so a chord is one line and a lake
  // vertex has its spokes and its sides.
  const waterEdges = (j) => {
    const nb = adjacencies();
    const parent = new Map([[j, -1]]);
    const depth = new Map([[j, 0]]);
    const queue = [j];
    const ends = [];
    while (queue.length) {
      const h = queue.shift();
      if (depth.get(h) >= EDGE_HOPS) continue;
      for (const o of (nb[h] || [])) {
        if (parent.has(o)) continue;
        parent.set(o, h);
        depth.set(o, depth.get(h) + 1);
        if (isEnd(o)) ends.push(o); else queue.push(o);
      }
    }
    return ends.map((e) => {
      const path = [];
      let x = e;
      while (x !== j) { path.push(x); x = parent.get(x); }
      path.reverse();
      return {end: e, cells: path, points: [pointOf(j), ...path.map(pointOf)]};
    });
  };

  // Where the cursor falls on a polyline: the share travelled (0 at the
  // start, 1 at the end), how far off the line it is, and the point on it.
  const projectOn = (points, x, y) => {
    let total = 0;
    const lengths = [];
    for (let i = 1; i < points.length; i++) {
      const l = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
      lengths.push(l); total += l;
    }
    if (!total) return {t: 0, d: Infinity, at: points[0]};
    let best = {t: 0, d: Infinity, at: points[0]};
    let before = 0;
    for (let i = 1; i < points.length; i++) {
      const [x1, y1] = points[i - 1], [x2, y2] = points[i];
      const dx = x2 - x1, dy = y2 - y1;
      const l2 = dx * dx + dy * dy;
      const u = l2 ? Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / l2)) : 0;
      const px_ = x1 + u * dx, py_ = y1 + u * dy;
      const d = Math.hypot(x - px_, y - py_);
      if (d < best.d) best = {t: (before + u * lengths[i - 1]) / total, d, at: [px_, py_]};
      before += lengths[i - 1];
    }
    return best;
  };

  // A line in hand: its junctions, where each sits along it, and how many
  // the arrow has taken so far.
  const lineOf = (edge) => {
    const at = [0];
    let total = 0;
    for (let i = 1; i < edge.points.length; i++) {
      total += Math.hypot(edge.points[i][0] - edge.points[i - 1][0],
                          edge.points[i][1] - edge.points[i - 1][1]);
      at.push(total);
    }
    return {cells: edge.cells, points: edge.points, at, total, taken: 0};
  };
  // Junction by junction only while a side is something a hand can mean on
  // screen; otherwise the line is one step, taken and undone as a whole.
  const fineEnough = (line) => {
    let shortest = Infinity;
    for (let i = 1; i < line.at.length; i++) shortest = Math.min(shortest, line.at[i] - line.at[i - 1]);
    return shortest >= px(PX_FINE);
  };
  // How far along the line the cursor must be for junction k (1..n) to be
  // taken, and below which it is undone: two thirds of the side leading to
  // it, and never less than a few screen pixels.
  const commitAt = (line, k) => {
    if (!fineEnough(line)) return COMMIT * line.total;
    const side = line.at[k] - line.at[k - 1];
    return line.at[k - 1] + Math.min(side, Math.max(COMMIT * side, px(PX_COMMIT)));
  };
  const backAt = (line, k) => {
    if (!fineEnough(line)) return BACK * line.total;
    const side = line.at[k] - line.at[k - 1];
    return line.at[k - 1] + BACK * side;
  };
  // Advances or backs the arrow along the line in hand to where the cursor
  // projects; true if a step changed.
  const followLine = (line, s) => {
    let changed = false;
    while (line.taken < line.cells.length && s >= commitAt(line, line.taken + 1)
           && state.steps.length < MAX_STEPS) {
      state.steps.push(line.cells[line.taken]);
      line.taken++;
      changed = true;
    }
    while (line.taken > 0 && s < backAt(line, line.taken)) {
      state.steps.pop();
      line.taken--;
      changed = true;
    }
    return changed;
  };
  // The dashed thread: from the last junction taken, along the line, to
  // where the cursor projects on it.
  const previewOf = (line, pr) => {
    const s = pr.t * line.total;
    const pts = [line.points[line.taken]];
    for (let k = line.taken + 1; k < line.points.length && line.at[k] <= s; k++) pts.push(line.points[k]);
    pts.push(pr.at);
    return {points: pts};
  };

  // One mouse move on the water. The direction comes from the **line** —
  // among those leaving the last junction, the one the cursor is on — and
  // the steps from the **junctions** along it, each taken by travel and
  // undone by travel. Repeated a few times in a row, because a fast hand
  // can finish a line and enter the next in one move.
  const waterGuide = (point) => {
    if (!state || !state.steps.length) return;
    readScale();
    const offLine = Math.max(OFF_LINE * spacing(), px(PX_OFF));
    let changed = false;
    for (let round = 0; round < MAX_FILL + 2; round++) {
      const line = state.line;
      if (line) {
        const pr = projectOn(line.points, point.x, point.y);
        const s = pr.t * line.total;
        if (pr.d <= offLine) {
          if (followLine(line, s)) changed = true;
          if (line.taken === line.cells.length) {     // the line is done
            state.lines.push(line);
            state.line = null;
            state.armed = null;
            if (pr.t >= 1) continue;                  // already beyond: the next line may be armed
            break;
          }
          if (line.taken === 0 && pr.t <= 0) {        // never entered: let it go
            state.line = null;
            state.armed = null;
            continue;
          }
          state.armed = previewOf(line, pr);
          break;
        }
        // Off the line. One nothing was taken on is let go; one partly taken
        // stays in hand — the hand wandered, it did not leave.
        state.armed = null;
        if (line.taken === 0) { state.line = null; continue; }
        break;
      }
      const j = fromWhere();
      // Back onto the previous line: the cursor is behind its last junction.
      const prev = state.lines[state.lines.length - 1];
      if (prev && prev.taken > 0) {
        const pr = projectOn(prev.points, point.x, point.y);
        if (pr.d <= offLine && pr.t * prev.total < backAt(prev, prev.taken)) {
          state.lines.pop();
          state.line = prev;
          continue;
        }
      }
      // A new line from here: the one the cursor is on. Never the side just
      // travelled, backwards: a hand going back over it is retracing its
      // steps, and the arrow must shrink, not double back on itself.
      const before = state.steps.length >= 2 ? state.steps[state.steps.length - 2] : -1;
      const beforeAt = before >= 0 ? pointOf(before) : null;
      let armed = null;
      let nearest = Infinity;
      for (const e of waterEdges(j)) {
        if (before >= 0 && e.cells.length && (e.cells[0] === before
            || (Math.abs(e.points[1][0] - beforeAt[0]) < 0.6
                && Math.abs(e.points[1][1] - beforeAt[1]) < 0.6))) continue;
        const pr = projectOn(e.points, point.x, point.y);
        nearest = Math.min(nearest, pr.d);
        if (pr.t <= 0 || pr.d > offLine) continue;
        if (!armed || pr.d < armed.pr.d) armed = {edge: e, pr};
      }
      if (armed) {
        state.line = lineOf(armed.edge);
        continue;
      }
      state.armed = null;
      // Far from every line: the hand ran ahead, and the gap is filled along
      // the water up to the nearest junction, if it is a few hops away.
      if (nearest > Math.max(RUN_AHEAD * spacing(), 2 * px(PX_OFF))) {
        const cell = nearestIndex(point.x, point.y);
        if (cell >= 0 && cell !== j && !state.steps.includes(cell)) {
          const along = alongWater(j, cell);
          if (along.length && state.steps.length + along.length <= MAX_STEPS) {
            const filled = lineOf({end: cell, cells: along, points: [pointOf(j), ...along.map(pointOf)]});
            for (const i of along) state.steps.push(i);
            filled.taken = along.length;
            state.lines.push(filled);
            changed = true;
          } else if (!inFlash()) {
            reportBlock('ring');
          }
        }
      }
      break;
    }
    redraw();
    if (changed) sendTrace(false);
  };

  const manualStep = (steps, cell) => {
    if (!steps.length) return false;
    const last = steps[steps.length - 1];
    if (cell === last) return false;
    // Going back eats **the last** steps, it does not cut back to the first.
    // Before, the search started from the beginning, and by hex on top of
    // that: re-entering an already crossed hex — even from the other shore,
    // passing a bridge — threw away the whole course made in between. And it
    // is precisely the road one wants to be able to make: leave from a shore,
    // go around, re-enter the same cell as before from the other side of the
    // river.
    //
    // The **cell** is looked at, not the hex: the two shores of a cut hex are
    // two different cells, and passing from one to the other is a real step,
    // not a loop.
    //
    // And **only the second to last** is looked at, which is the only thing
    // that tells the two intentions apart with certainty. Going back means
    // re-entering the cell one just left; reaching a cell already seen from
    // elsewhere is a loop closing, and there the course lengthens. Looking
    // further back — five steps, ten — could no longer tell the two apart,
    // and would eat the loops.
    if (steps.length >= 2 && steps[steps.length - 2] === cell) {
      steps.pop();                             // you went back over your steps
      return true;
    }
    if (adjacent(cell, last)) {
      steps.push(cell);                       // one hex at a time
      return true;
    }
    // On the water the gap is filled **along the water**: a running hand
    // skips a few junctions, and the few missing are taken following the
    // river, if they are few. There is no straight line to draw, the water
    // turns.
    if (field().water) {
      const along = alongWater(last, cell);
      if (!along.length) {
        reportBlock('ring');
        return false;
      }
      for (const i of along) steps.push(i);
      if (steps.length > MAX_STEPS) steps.length = MAX_STEPS;
      return true;
    }
    // The gap between two non-neighbouring hexes is filled only if it is a
    // gap: a running hand skips two or three, and there one goes straight.
    // If reaching it means going around something — a river, almost always —
    // it is no longer the hand that ran, and it is a road nobody asked for:
    // the arrow does not lengthen, says so, and follows you again as soon as
    // you come back to where there is a way through.
    const added = inStraightLine(last, cell);
    if (!added.length || added.length > MAX_FILL) {
      reportBlock(blockedByWater(last, cell) ? 'water' : 'ring');
      return false;
    }
    for (const i of added) steps.push(i);
    if (steps.length > MAX_STEPS) steps.length = MAX_STEPS;
    return true;
  };

  // With the group too the hand guides, but it guides *one* line: the road
  // made as one. The meeting point and the approach branches are chosen by
  // the algorithm at the moment you press, and from there on they stay
  // still. It is the same rule as the lone traveller — press and you have the
  // shortest way, drag and it becomes yours — applied to the piece of journey
  // that really is one: a meeting point moving at every shift of the mouse
  // would make the road dance under the fingers while you draw it.
  const refreshGroup = (cell) => {
    if (!state.rendezvous) {
      const fresh = rendezvous(cell);
      if (!fresh) return false;
      state.rendezvous = fresh;
      return true;
    }
    const r = state.rendezvous;
    if (!manualStep(r.common, cell)) return false;
    // The branches do not change, so neither does the wait at the meeting
    // point: only the count of the common road is redone.
    r.days = r.union + legCost(r.common) / paceTogether();
    return true;
  };

  // With «together» off the hand guides all the arrows together. On pressing
  // everyone takes their shortest way there; from that moment every step of
  // the hand applies to all the roads, as if k rulers were guided in
  // parallel. They all end anyway on the hex under the mouse — lengthening
  // if it is new, shortening if they had already passed there — so the
  // destination stays one for everyone, which is the point of the mode.
  const refreshSeparate = (cell) => {
    if (!state.separate) {
      const listing = [];
      for (const v of field().travellers) {
        const d = v.from[cell];
        if (d === null || d === undefined) continue;
        listing.push({id: v.id, name: v.name, color: v.color || COLOR,
                     activities: v.activities, steps: climbBack(v.from, cell)});
      }
      if (!listing.length) return false;
      state.separate = listing;
      state.meta = cell;
      return true;
    }
    let changed = false;
    for (const entry of state.separate) {
      if (manualStep(entry.steps, cell)) changed = true;
    }
    if (changed) state.meta = cell;
    return changed;
  };

  const refresh = (cell) => {
    if (inGroup()) return refreshGroup(cell);
    if (eachAlone()) return refreshSeparate(cell);
    const dists = field().travellers[0].from;
    if (dists[cell] === null || dists[cell] === undefined) return false;
    // On the water the road is not guided by hand, and it is not laziness:
    // between two points of a river the road is that one, and there is no
    // other to prefer. Guiding by hand instead advances *one cell at a time*,
    // and since the cells are the water points there are plenty inside the
    // same hex: the hand ran ahead, the step stayed behind, and to get
    // anywhere one had to drag much further than where one wanted to go.
    // Here the course is redone up to the point indicated, and that is all.
    if (field().water) {
      // On the water the land rule holds too: pressing gives at once the
      // shortest way to the junction pressed; from there on the hand guides,
      // from one junction to the next. Before, the road was redone from
      // scratch at every move, and there was no way to choose one bend rather
      // than another.
      if (!state.steps.length) {
        state.steps = climbBack(dists, cell);
        state.line = null;
        state.lines = [];
        if (state.steps.length > 1) {
          const first = lineOf({end: state.steps[state.steps.length - 1],
                                cells: state.steps.slice(1), points: state.steps.map(pointOf)});
          first.taken = first.cells.length;
          state.lines = [first];
        }
        return state.steps.length > 0;
      }
      return manualStep(state.steps, cell);
    }
    if (!state.steps.length) {
      // The first step is the «press and you have the road» gesture: the
      // shortest way to the pressed cell, as with the right button.
      // **Always**, even for the next cell. Before, the next cell followed the
      // hand-guiding rule — one step, or nothing — so as not to see the arrow
      // run off looking for a far bridge. But from inside a small piece of
      // hex «one step» often does not exist, and the arrow stayed glued to the
      // marker: better a road that exists and can be undone by hand, than no
      // road. Hand guiding holds from the second step on.
      state.steps = climbBack(dists, cell);
      if (state.steps.length > 1) return true;
      state.steps = [fromWhere()];
      return manualStep(state.steps, cell);
    }
    return manualStep(state.steps, cell);
  };

  const redraw = () => {
    if (inGroup()) {
      if (state.rendezvous) drawGroup(state.group, state.rendezvous);
    } else if (eachAlone()) {
      if (state.separate) drawSeparate(state.group, state.separate);
    } else {
      drawSingle(state.group, state.steps);
    }
  };

  // From «I am choosing» to «I am tracing»: one passes through here, no more.
  // From which cell one is going on. `nearestIndex` needs it to pick the
  // right bank when the mouse lands on a hex the river cuts: the point does
  // not say which side you are on, where you come from does.
  const fromWhere = () => {
    if (!state) return -1;
    if (state.steps && state.steps.length) return state.steps[state.steps.length - 1];
    if (state.rendezvous && state.rendezvous.common && state.rendezvous.common.length) {
      return state.rendezvous.common[state.rendezvous.common.length - 1];
    }
    const travellers = field() ? field().travellers : null;
    return travellers && travellers.length ? travellers[0].origin : -1;
  };

  const forgetHalt = () => {
    if (state && state.halt) {
      clearTimeout(state.halt.timer);
      state.halt = null;
    }
  };

  // Near the cell's point there is nothing to wait for. It holds for the
  // shores too: since each has the point of its piece of hex, «how far in you
  // are» means something there too — and it is precisely there that it is
  // needed, because passing a bridge is entering the other half of the same
  // hex, and waiting a tenth of a second for every bridge is felt.
  const reallyInside = (cell, point) => {
    const cells = field().cells;
    const step = field().step || 0;
    if (!step) return false;
    const dx = cells[cell][2] - point.x, dy = cells[cell][3] - point.y;
    return dx * dx + dy * dy < (step * INSIDE) * (step * INSIDE);
  };

  // The mouse points at a cell; the arrow enters it only if the pointing lasts.
  const propose = (cell, point) => {
    if (!state || cell < 0) return;
    if (cell === fromWhere()) {       // you are already there: nothing to wait for
      forgetHalt();
      return;
    }
    // Against the water there is no waiting. The halt serves not to enter a
    // cell for a jitter, not to delay a no: if the cell pointed at is the
    // next hex — or the other shore of this one — and between the two there
    // is no way through, the arrow flashes **at once**, without the
    // thousandths of wait. It holds with a road already in hand: the first
    // step is «press and you have the shortest way», and there a river ahead
    // is gone around by the bridge, not bumped into.
    const guided = state.steps.length > 1 ||
      (state.rendezvous && state.rendezvous.common && state.rendezvous.common.length > 1);
    if (guided && !field().water && blockedByWater(fromWhere(), cell)) {
      forgetHalt();
      if (!inFlash()) reportBlock('water');
      return;
    }
    // On the water the first step is «press and you have the road», at once;
    // from there the hand guides junction by junction, and the junctions are
    // close together: without the pause a hand crossing the river drew loops
    // by itself. So the same wait as on land, and no «well inside» shortcut,
    // because there is no inside to a point.
    if (field().water) {
      forgetHalt();
      if (!state.steps.length) decide(cell);
      else waterGuide(point);
      return;
    } else if (reallyInside(cell, point)) {
      forgetHalt();
      decide(cell);
      return;
    }
    if (state.halt && state.halt.cell === cell) return;   // already waiting
    forgetHalt();
    const mine = state;
    state.halt = {cell, timer: setTimeout(() => {
      // Every different cell cancels the previous wait, so if the clock ran
      // out it means the hand stayed there.
      if (state !== mine || !active()) return;
      state.halt = null;
      decide(cell);
    }, HALT)};
  };

  const decide = (cell) => {
    if (!state || cell < 0) return false;
    if (!state.decided) {
      // The already decided arrow is removed only now: a click choosing
      // someone must not make the existing path vanish.
      oldArrow(state.box, false);
      state.decided = true;
    }
    if (refresh(cell)) {
      redraw();
      sendTrace(false);
      return true;
    }
    // No road reaches there, and there is no arrow yet: with the right button
    // the app says so, pressing it stayed mute. With an arrow already in hand
    // instead the hand guiding has already taken care of saying no.
    const empty = !(state.steps && state.steps.length) &&
      !state.rendezvous && !state.separate;
    if (empty) reportBlock('unreachable');
    return false;
  };

  // --------------------------------------------------------------- events
  const connect = (box) => {
    if (box.dataset.kmArrow) return;
    box.dataset.kmArrow = '1';

    box.addEventListener('mousedown', (e) => {
      // With ctrl pressed one is putting a group together, one marker at a
      // time: the arrow has nothing to do with it, and seeing it flash is
      // just a nuisance.
      if (e.button !== 0 || e.ctrlKey || !active()) return;
      const group = drawingGroup(box);
      const point = imageCoords(box, e);
      if (!group || !point) return;
      state = {box, group, steps: [], moved: 0, rendezvous: null,
               separate: null, meta: -1, decided: false, wait: null,
               halt: null, lines: [], line: null, armed: null};
      // A flag left over from a previous drag (mouseup outside the map, hence
      // no click afterwards) would swallow this click.
      delete box.dataset.kmJustTraced;

      // Merely pressing is the gesture to *choose* who leaves, and as long as
      // it is that nothing is drawn: otherwise choosing one marker after the
      // other the arrow flashes at every click. It becomes a drag either when
      // the hand moves, or when you stay pressed still for WAIT: from that
      // moment the arrow appears, and appearing means that releasing decides
      // the journey. What you see and what happens are the same thing, and it
      // is the only way for the gesture to be learnt on its own.
      const cell = nearestIndex(point.x, point.y);
      const mine = state;
      state.wait = setTimeout(() => {
        if (state !== mine || !active()) return;
        decide(cell);
      }, WAIT);
      e.preventDefault();
    });

    window.addEventListener('mousemove', (e) => {
      if (!state || !active()) return;
      state.moved = Math.max(state.moved, Math.abs(e.movementX) + Math.abs(e.movementY));
      // Below the threshold the hand is just holding badly: it is still a click.
      if (!state.decided && state.moved <= THRESHOLD) return;
      const point = imageCoords(state.box, e);
      if (!point) return;
      propose(nearestIndex(point.x, point.y), point);
    });

    const close = (e) => {
      if (!state) return;
      // The cell that was waiting is taken anyway: you let go of the button in
      // there, and that is the spot where you wanted to end. Without this,
      // letting go just after entering stopped the arrow one hex before where
      // the hand had got to.
      if (state.halt) {
        const wait = state.halt.cell;
        forgetHalt();
        decide(wait);
      }
      const finished = state;
      const group = inGroup();
      const separate = eachAlone();
      state = null;
      sendTrace(true);          // no more arrow: the others remove it
      if (finished.wait) clearTimeout(finished.wait);
      write(finished.group, '');
      const cells = field() ? field().cells : [];
      const hasSomething = group ? finished.rendezvous !== null
                        : separate ? finished.meta >= 0
                        : finished.steps.length > 1;
      // If the arrow was seen, releasing confirms it; if it was not seen it
      // was a click, and the usual gesture to choose who leaves remains.
      if (hasSomething && finished.decided && cells.length) {
        finished.box.dataset.kmJustTraced = '1';
        if (typeof emitEvent === 'function') {
          if (separate) {
            // The drawn roads must all be sent: redoing them here would be
            // choosing others, and whoever just drew the arrows by hand would
            // see a journey other than the one they were looking at appear.
            const m = cells[finished.meta];
            const roads = finished.separate
              .filter((v) => v.steps.length > 1)
              .map((v) => ({id: v.id,
                            path: v.steps.map((i) => [cells[i][0], cells[i][1]])}));
            emitEvent('km_travel_target',
                      {col: m[0], row: m[1], separate: roads});
          } else if (group) {
            // The common road must be sent as it was drawn, otherwise the
            // server redoes the shortest one and the hand would have worked
            // for nothing. If only the meeting point is left there is nothing
            // to guide: the destination is enough, and the server redoes the
            // count.
            const common = finished.rendezvous.common;
            const end = cells[common[common.length - 1]];
            if (common.length > 1) {
              // The shores too: the first says which shore of the meeting
              // point one is on, and from there the server starts the common
              // road. And **the branches**, one per traveller: at equal cost
              // the roads are more than one, and if the server recomputed
              // them from scratch it could pick others — on release the
              // branches changed shape.
              const branches = field().travellers.map((v, k) => ({
                id: v.id,
                path: (finished.rendezvous.branches[k] || []).map(
                  (i) => [cells[i][0], cells[i][1]]),
                nodes: (finished.rendezvous.branches[k] || []).map(
                  (i) => [cells[i][0], cells[i][1], cells[i][8] || 0]),
              }));
              emitEvent('km_travel_target',
                        {col: end[0], row: end[1], common: true,
                         path: common.map((i) => [cells[i][0], cells[i][1]]),
                         nodes: common.map((i) => [cells[i][0], cells[i][1], cells[i][8] || 0]),
                         branches: branches});
            } else {
              emitEvent('km_travel_target', {col: end[0], row: end[1]});
            }
          } else {
            const road = finished.steps.map((i) => [cells[i][0], cells[i][1]]);
            const last = road[road.length - 1];
            const end = cells[finished.steps[finished.steps.length - 1]];
            // On the water the hex is not enough to say where you ended up:
            // inside the same hex there are several points, and on an edge
            // stretch there are two sitting in different cells. Without the
            // point the server redid the route towards *another* end, and
            // letting go a journey other than the one being looked at
            // appeared.
            // On the water the whole drawn road is sent, point by point: the
            // server walks it again instead of redoing a cheaper one. Whoever
            // followed the river with a finger does not want to see the road
            // replaced by another, and with the hex alone the server would
            // not even know which side of the edge one had passed on.
            const points = field().water
              ? finished.steps.map((i) => [cells[i][2], cells[i][3],
                                         cells[i][0], cells[i][1]])
              : null;
            // The point of the arrival cell is **always** sent, not only on
            // the water: inside a hex a river divides there are several
            // pieces, and the hex alone does not say in which you let go of
            // the button. Without it, one could aim at the shore beyond and
            // then the marker stopped on this one — the arrow seemed to
            // correct itself, and what happened was not what you had drawn.
            // And **the shores** the hand passed through: the hex alone does
            // not say them, and where a hex has several crossings the server,
            // rebuilding them, finds another road — on release the arrow
            // changed shape on its own. Here they are handed to it.
            const nodes = finished.steps.map(
              (i) => [cells[i][0], cells[i][1], cells[i][8] || 0]);
            emitEvent('km_travel_target',
                      {col: last[0], row: last[1], path: road,
                       nodes: nodes, point: [end[2], end[3]], points: points});
          }
        }
        if (e) { e.preventDefault(); e.stopPropagation(); }
      } else {
        oldArrow(finished.box, true);   // it was a click: you go back as before
      }
    };

    window.addEventListener('mouseup', (e) => { if (e.button === 0) close(e); });
    window.addEventListener('blur', () => close(null));

    // The click following a drag must not also select someone.
    box.addEventListener('click', (e) => {
      if (box.dataset.kmJustTraced === '1') {
        delete box.dataset.kmJustTraced;
        e.preventDefault();
        e.stopPropagation();
      }
    }, true);
  };

  // The map redraw redoes the whole content of the SVG and takes away the
  // group of the others' arrows too: here it is put back, and it is the same
  // round that hooks the new boxes up.
  const search = () => {
    document.querySelectorAll('.km-drag').forEach(connect);
    drawOthers();
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', search);
  } else {
    search();
  }
  new MutationObserver(search).observe(document.documentElement,
                                      {childList: true, subtree: true});
})();
