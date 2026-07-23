(() => {
  const button = document.getElementById('downloadDiagnostics');
  if (!button) return;

  button.addEventListener('click', () => {
    button.disabled = true;
    button.textContent = 'Preparing diagnostic logs…';

    const link = document.createElement('a');
    link.href = `/api/diagnostics/download?ts=${Date.now()}`;
    link.download = '';
    link.hidden = true;
    document.body.appendChild(link);
    link.click();
    link.remove();

    window.setTimeout(() => {
      button.disabled = false;
      button.textContent = 'Download diagnostic logs';
    }, 1500);
  });
})();
