// Placeholder page behaviour. Nothing is wired to a backend yet.

// Summarize: swap the summary body for a three-dot loader. There is no model
// connected, so the loader runs indefinitely by design — reload to reset.
function initSummarize() {
  const button = document.getElementById('summarize');
  const body = document.querySelector('.summary-body');
  if (!button || !body) return;

  button.addEventListener('click', () => {
    button.disabled = true;

    const dots = document.createElement('span');
    dots.className = 'dots';
    dots.setAttribute('role', 'status');
    dots.setAttribute('aria-label', 'Generating summary');
    for (let i = 0; i < 3; i++) {
      dots.appendChild(document.createElement('span'));
    }

    body.classList.remove('meta');
    body.replaceChildren(dots);
  });
}

// Refresh: spin the icon while an ingest runs. No ETL is connected yet, so it
// spins indefinitely — removing .spinning is what returns it to resting grey.
function initRefresh() {
  const button = document.getElementById('refresh');
  if (!button) return;

  button.addEventListener('click', () => {
    if (button.classList.contains('spinning')) return;
    button.classList.add('spinning');
    button.setAttribute('aria-busy', 'true');
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initSummarize();
  initRefresh();
});
