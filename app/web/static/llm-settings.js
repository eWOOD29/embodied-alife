(() => {
  let modelCatalog = [];

  function formatBytes(value) {
    const size = Number(value);
    if (!Number.isFinite(size) || size <= 0) return null;
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let amount = size;
    let unit = 0;
    while (amount >= 1024 && unit < units.length - 1) {
      amount /= 1024;
      unit += 1;
    }
    return `${amount.toFixed(unit >= 3 ? 1 : 0)} ${units[unit]}`;
  }

  function modelLabel(model) {
    const extras = [];
    if (model.quantization) extras.push(model.quantization);
    if (model.max_context_length) extras.push(`${Number(model.max_context_length).toLocaleString()} ctx`);
    return extras.length ? `${model.display_name} — ${extras.join(' · ')}` : model.display_name;
  }

  function renderModelDetails() {
    const select = document.getElementById('llmModel');
    const details = document.getElementById('llmModelDetails');
    const model = modelCatalog.find(item => item.id === select.value);
    if (!model) {
      details.textContent = modelCatalog.length
        ? 'Choose a model that LM Studio reports as loaded.'
        : 'No loaded LLM is currently available.';
      return;
    }
    const parts = [`Exact API ID: ${model.id}`, `state: ${model.state}`];
    if (model.publisher) parts.push(`publisher: ${model.publisher}`);
    if (model.quantization) parts.push(`quantization: ${model.quantization}`);
    if (model.max_context_length) parts.push(`max context: ${Number(model.max_context_length).toLocaleString()}`);
    if (model.size_bytes) parts.push(`size: ${formatBytes(model.size_bytes)}`);
    details.textContent = parts.join(' · ');
  }

  async function discoverLoadedModels(showMessage = true) {
    const button = document.getElementById('discoverModels');
    const select = document.getElementById('llmModel');
    const summary = document.getElementById('llmSettingsSummary');
    button.disabled = true;
    try {
      const apiKey = document.getElementById('llmApiKey').value.trim();
      const [configuration, result] = await Promise.all([
        apiRequest('/api/llm/settings'),
        apiRequest('/api/llm/models', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            base_url: document.getElementById('llmBaseUrl').value.trim(),
            api_key: apiKey || null
          })
        })
      ]);

      const allModels = Array.isArray(result.models) ? result.models : [];
      const loadedModels = result.loaded_state_available
        ? allModels.filter(model => model.state === 'loaded')
        : allModels;
      modelCatalog = loadedModels;

      const placeholder = new Option(
        loadedModels.length ? 'Select a loaded model' : 'No loaded LLMs found',
        ''
      );
      select.replaceChildren(placeholder, ...loadedModels.map(model => new Option(modelLabel(model), model.id)));

      const configured = configuration.model || result.selected_model || '';
      if (loadedModels.some(model => model.id === configured)) {
        select.value = configured;
      } else if (loadedModels.length === 1) {
        select.value = loadedModels[0].id;
      } else {
        select.value = '';
      }
      select.disabled = loadedModels.length === 0;
      renderModelDetails();

      if (result.loaded_state_available) {
        const total = allModels.length;
        if (loadedModels.length === 1) {
          const suffix = configured !== loadedModels[0].id
            ? ' The exact loaded ID was selected; click Save and apply.'
            : '';
          summary.textContent = `LM Studio reports 1 loaded LLM out of ${total} available model${total === 1 ? '' : 's'}.${suffix}`;
        } else if (loadedModels.length > 1) {
          summary.textContent = `LM Studio reports ${loadedModels.length} loaded LLMs out of ${total} available models. Choose which one Ari should use.`;
        } else {
          summary.textContent = `LM Studio responded, but none of the ${total} available models is currently loaded.`;
        }
      } else {
        summary.textContent = 'This LM Studio version did not expose loaded-state metadata; showing OpenAI-compatible model IDs without verified memory state.';
      }

      if (showMessage) {
        showToast(loadedModels.length === 1 ? 'Found 1 loaded LLM' : `Found ${loadedModels.length} loaded LLMs`);
      }
    } catch (error) {
      modelCatalog = [];
      select.replaceChildren(new Option('Model discovery failed', ''));
      select.disabled = true;
      document.getElementById('llmModelDetails').textContent = error.message;
      summary.textContent = error.message;
      if (showMessage) showToast(error.message);
    } finally {
      button.disabled = false;
    }
  }

  document.getElementById('discoverModels').onclick = () => discoverLoadedModels(true);
  document.getElementById('llmModel').onchange = renderModelDetails;
  document.getElementById('saveLlmSettings').onclick = async () => {
    await saveLlmSettings();
    await discoverLoadedModels(false);
  };

  window.setTimeout(() => discoverLoadedModels(false), 100);
})();
