// Line charts, drawn as inline SVG.
//
// Hand-rolled rather than a charting library: the page needs one line, a few
// labels and a crosshair, and every library that does that also brings a
// bundle, a build step and its own opinions about colour. This reads the same
// CSS custom properties as the rest of the site, so it follows the theme —
// including the day/night toggle — with no extra work.
//
// Layout rule: nothing that can change length is drawn inside the plot. The
// value readout lives in its own row above the frame and the date span in a
// row below, so hovering can never collide with an axis label. Inside the SVG
// only the two price labels appear, and they sit in a reserved right gutter
// the line never enters.

const PAD = { left: 8, right: 64, top: 14, bottom: 10 };

function css(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function fmt(v) {
  const a = Math.abs(v);
  const digits = a >= 10000 ? 0 : a >= 1 ? 2 : 4;
  return v.toLocaleString(undefined, { minimumFractionDigits: digits,
                                       maximumFractionDigits: digits });
}

function fmtDate(s) {
  return s.length > 10 ? s.slice(5, 16).replace('T', ' ') : s;
}

function svgEl(svg, name, attrs) {
  const node = document.createElementNS(svg.namespaceURI, name);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  return node;
}

function draw(panel, data) {
  const svg = panel.querySelector('.chart-svg');
  const readout = panel.querySelector('.chart-readout');
  const foot = panel.querySelector('.chart-span');
  const points = data.points || [];

  svg.replaceChildren();
  foot.textContent = '';

  if (points.length < 2) {
    const t = svgEl(svg, 'text', { x: '50%', y: '50%', class: 'chart-empty',
                                   'text-anchor': 'middle' });
    t.textContent = 'not enough history for this range';
    svg.appendChild(t);
    return;
  }

  const W = svg.clientWidth || 700;
  const H = svg.clientHeight || 220;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

  const values = points.map(p => p[1]);
  const dataLo = Math.min(...values);
  const dataHi = Math.max(...values);
  // Pad the *scale* so the line never touches the edge, but label the real
  // extremes — printing the padded bounds would show prices that never traded.
  const spread = (dataHi - dataLo) || Math.abs(dataHi) || 1;
  const lo = dataLo - spread * 0.08;
  const hi = dataHi + spread * 0.08;

  const x = i => PAD.left + (i / (points.length - 1)) * (W - PAD.left - PAD.right);
  const y = v => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);

  const rising = values[values.length - 1] >= values[0];
  const stroke = rising ? css('--up', '#7fc9a0') : css('--down', '#e0796b');
  const rule = css('--rule', '#333');
  const muted = css('--muted', '#8a8a8a');

  const d = points
    .map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`)
    .join('');

  // Baseline at the window's opening value — the reference the move is against.
  svg.appendChild(svgEl(svg, 'line', {
    x1: PAD.left, x2: W - PAD.right, y1: y(values[0]), y2: y(values[0]),
    stroke: rule, 'stroke-dasharray': '2 4',
  }));

  svg.appendChild(svgEl(svg, 'path', {
    d: `${d}L${x(points.length - 1)},${y(lo)}L${PAD.left},${y(lo)}Z`,
    fill: stroke, opacity: '0.07',
  }));

  svg.appendChild(svgEl(svg, 'path', {
    d, fill: 'none', stroke, 'stroke-width': '1.5', 'stroke-linejoin': 'round',
  }));

  // Price labels in the reserved gutter, nudged inward so neither clips.
  const hiLabel = svgEl(svg, 'text', { x: W - PAD.right + 7, y: Math.max(y(dataHi), 11),
                                       class: 'chart-axis' });
  hiLabel.textContent = fmt(dataHi);
  const loLabel = svgEl(svg, 'text', { x: W - PAD.right + 7, y: Math.min(y(dataLo), H - 4),
                                       class: 'chart-axis' });
  loLabel.textContent = fmt(dataLo);
  svg.append(hiLabel, loLabel);

  foot.textContent = `${fmtDate(points[0][0])} → ${fmtDate(points[points.length - 1][0])}`;

  attachCrosshair(svg, { points, x, y, H, muted, stroke, readout,
                         rest: readout.textContent });
}

function attachCrosshair(svg, ctx) {
  const { points, x, y, H, muted, stroke, readout, rest } = ctx;

  const g = svgEl(svg, 'g', { opacity: '0' });
  const vline = svgEl(svg, 'line', { y1: PAD.top, y2: H - PAD.bottom, stroke: muted });
  const dot = svgEl(svg, 'circle', { r: '3', fill: stroke });
  g.append(vline, dot);
  svg.appendChild(g);

  svg.addEventListener('pointermove', ev => {
    const box = svg.getBoundingClientRect();
    const px = (ev.clientX - box.left) * (svg.viewBox.baseVal.width / box.width);
    let best = 0, bestD = Infinity;
    for (let i = 0; i < points.length; i++) {
      const dist = Math.abs(x(i) - px);
      if (dist < bestD) { bestD = dist; best = i; }
    }
    const [when, value] = points[best];
    vline.setAttribute('x1', x(best));
    vline.setAttribute('x2', x(best));
    dot.setAttribute('cx', x(best));
    dot.setAttribute('cy', y(value));
    g.setAttribute('opacity', '1');
    readout.textContent = `${fmtDate(when)}   ${fmt(value)}`;
    readout.classList.add('hovering');
  });

  svg.addEventListener('pointerleave', () => {
    g.setAttribute('opacity', '0');
    readout.textContent = rest;          // back to the window summary
    readout.classList.remove('hovering');
  });
}

async function load(panel) {
  const key = panel.dataset.key;
  const range = panel.dataset.range || 'YTD';
  const title = panel.querySelector('.chart-title');
  const readout = panel.querySelector('.chart-readout');
  if (!key) return;

  readout.textContent = 'loading…';
  readout.className = 'chart-readout';

  try {
    const res = await fetch(`/api/history?key=${encodeURIComponent(key)}&range=${range}`);
    const data = await res.json();
    if (!res.ok) { readout.textContent = data.error || 'unavailable'; return; }

    title.textContent = [data.name, data.unit].filter(Boolean).join(' · ');

    // The resting readout: last value and the move across the window. The
    // crosshair borrows this slot and hands it back on pointerleave.
    const last = data.points.length ? data.points[data.points.length - 1][1] : null;
    const pct = data.change_pct;
    readout.textContent = last == null ? 'no data'
      : `${fmt(last)}${pct == null ? '' :
          `   ${pct >= 0 ? '+' : ''}${pct.toFixed(2)}% ${data.range}`}`;
    readout.className = 'chart-readout ' + (pct == null ? '' : pct >= 0 ? 'up' : 'down');

    draw(panel, data);
  } catch (err) {
    readout.textContent = 'could not load history';
  }
}

function initCharts() {
  document.querySelectorAll('.chart').forEach(panel => {
    const select = (group, attr, value) => {
      panel.dataset[attr === 'data-range' ? 'range' : 'key'] = value;
      panel.querySelectorAll(`${group} button`).forEach(b =>
        b.classList.toggle('on', b.getAttribute(attr) === value));
      load(panel);
    };

    panel.querySelectorAll('.chart-range button').forEach(btn =>
      btn.addEventListener('click', () => select('.chart-range', 'data-range',
                                                 btn.dataset.range)));
    panel.querySelectorAll('.chart-pick button').forEach(btn =>
      btn.addEventListener('click', () => select('.chart-pick', 'data-key',
                                                 btn.dataset.key)));

    // Clicking a row in any table on the page charts that instrument.
    document.querySelectorAll('tr[data-symbol]').forEach(tr => {
      tr.addEventListener('click', () => {
        const target = panel.querySelector(
          `.chart-pick button[data-key="${CSS.escape(tr.dataset.symbol)}"]`);
        if (!target) return;
        target.click();
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    });

    load(panel);

    // Redraw on resize so the SVG keeps its proportions instead of stretching.
    let timer;
    window.addEventListener('resize', () => {
      clearTimeout(timer);
      timer = setTimeout(() => load(panel), 200);
    });
  });
}

document.addEventListener('DOMContentLoaded', initCharts);
