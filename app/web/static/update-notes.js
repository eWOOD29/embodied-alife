(() => {
  function escapeHtml(value) {
    const element = document.createElement('div');
    element.textContent = value;
    return element.innerHTML;
  }

  function renderInlineMarkdown(value) {
    let html = escapeHtml(value);
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return html;
  }

  function releaseNotesHtml(markdown) {
    const lines = String(markdown || '').replace(/\r\n?/g, '\n').split('\n');
    const output = [];
    let listOpen = false;

    const closeList = () => {
      if (listOpen) output.push('</ul>');
      listOpen = false;
    };

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        closeList();
        continue;
      }
      if (line.startsWith('### ')) {
        closeList();
        output.push(`<h4>${renderInlineMarkdown(line.slice(4))}</h4>`);
        continue;
      }
      if (line.startsWith('## ')) {
        closeList();
        output.push(`<h3>${renderInlineMarkdown(line.slice(3))}</h3>`);
        continue;
      }
      if (line.startsWith('# ')) {
        closeList();
        output.push(`<h3>${renderInlineMarkdown(line.slice(2))}</h3>`);
        continue;
      }
      if (/^[-*]\s+/.test(line)) {
        if (!listOpen) {
          output.push('<ul>');
          listOpen = true;
        }
        output.push(`<li>${renderInlineMarkdown(line.replace(/^[-*]\s+/, ''))}</li>`);
        continue;
      }
      closeList();
      output.push(`<p>${renderInlineMarkdown(line)}</p>`);
    }
    closeList();
    return output.join('');
  }

  function renderNotes(status) {
    const notes = document.getElementById('updateNotes');
    if (!notes) return;
    notes.hidden = !status?.release_notes;
    notes.innerHTML = status?.release_notes ? releaseNotesHtml(status.release_notes) : '';
  }

  async function renderCachedNotes() {
    try {
      const response = await fetch('/api/update/status', {cache: 'no-store'});
      if (!response.ok) return;
      renderNotes(await response.json());
    } catch (_) {}
  }

  window.renderReleaseNotesMarkdown = releaseNotesHtml;

  const originalRenderUpdateStatus = window.renderUpdateStatus;
  window.renderUpdateStatus = function renderUpdateStatusWithFormattedNotes() {
    originalRenderUpdateStatus();
    void renderCachedNotes();
  };

  // Perform one real release check on page load so the current release summary is
  // available immediately rather than only after the user presses Check now.
  queueMicrotask(() => {
    if (typeof window.refreshUpdateStatus === 'function') {
      void window.refreshUpdateStatus(true);
    }
  });
})();
