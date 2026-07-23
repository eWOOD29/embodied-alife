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

  window.renderReleaseNotesMarkdown = releaseNotesHtml;

  const originalRenderUpdateStatus = window.renderUpdateStatus;
  window.renderUpdateStatus = function renderUpdateStatusWithFormattedNotes() {
    originalRenderUpdateStatus();
    const notes = document.getElementById('updateNotes');
    if (!notes || notes.hidden) return;
    const markdown = notes.textContent;
    notes.innerHTML = releaseNotesHtml(markdown);
  };

  // The ordinary status endpoint is intentionally cheap and cached. Perform one real
  // release check on page load so the latest version and summary are immediately shown.
  queueMicrotask(() => {
    if (typeof window.refreshUpdateStatus === 'function') {
      window.refreshUpdateStatus(true);
    }
  });
})();
