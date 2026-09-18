(() => {
  const storeSelect = document.getElementById('scanStore');
  const video = document.getElementById('scanVideo');
  const statusEl = document.getElementById('scannerStatus');
  const supportEl = document.getElementById('scannerSupport');
  const startButton = document.getElementById('startCamera');
  const stopButton = document.getElementById('stopCamera');
  const focusButton = document.getElementById('focusBarcode');
  const barcodeInput = document.getElementById('barcodeInput');
  const lookupButton = document.getElementById('lookupButton');
  const overlay = document.getElementById('cameraOverlay');
  const productPreview = document.getElementById('productPreview');
  const itemMode = document.getElementById('itemMode');
  const previewName = document.getElementById('previewName');
  const previewMeta = document.getElementById('previewMeta');
  const productIdInput = document.getElementById('productId');
  const nameInput = document.getElementById('nameInput');
  const quantityInput = document.getElementById('quantityInput');
  const currentStock = document.getElementById('currentStock');
  const afterStock = document.getElementById('afterStock');
  const saveButton = document.getElementById('saveButton');
  const form = document.getElementById('scanForm');
  const saveMessage = document.getElementById('saveMessage');
  const refreshList = document.getElementById('refreshList');
  const toggleList = document.getElementById('toggleList');
  const recentList = document.getElementById('recentList');
  const choiceWrap = document.getElementById('choiceWrap');
  const productChoices = document.getElementById('productChoices');

  let stream = null;
  let detector = null;
  let scanLoop = null;
  let scanning = false;
  let lastCode = '';
  let lastDetectedAt = 0;
  let currentBarcode = '';
  let selectedProduct = null;
  let supportedFormats = [];

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

  function setStatus(text, state = '') {
    statusEl.textContent = text;
    statusEl.className = `scan-status ${state}`.trim();
  }

  function fmtNumber(value) {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return '0';
    return n.toLocaleString(undefined, { maximumFractionDigits: 3 });
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function showMessage(message, type = '') {
    saveMessage.hidden = !message;
    saveMessage.textContent = message || '';
    saveMessage.className = `scan-message ${type}`.trim();
  }

  function updateTotals() {
    const stock = Number(currentStock.dataset.value || 0);
    const rawQty = quantityInput.value.trim();
    const qty = rawQty === '' ? 0 : Number(rawQty);
    afterStock.textContent = Number.isFinite(stock + qty) ? fmtNumber(stock + qty) : '—';
  }

  function updateSaveAvailability() {
    saveButton.disabled = !(currentBarcode && nameInput.value.trim());
  }

  function setProduct(product, barcode) {
    selectedProduct = product;
    currentBarcode = barcode;
    productIdInput.value = product?.id || '';
    nameInput.value = product?.name || '';
    currentStock.dataset.value = String(product?.stock || 0);
    currentStock.textContent = fmtNumber(product?.stock || 0);
    itemMode.textContent = product ? 'Existing product' : 'New product';
    previewName.textContent = product?.name || 'New scanned item';
    previewMeta.textContent = `${barcode} · ${storeSelect.options[storeSelect.selectedIndex]?.text || 'Selected mart'}`;
    productPreview.classList.toggle('empty', !product);
    updateSaveAvailability();
    updateTotals();
  }

  function showChoices(products, barcode) {
    choiceWrap.hidden = false;
    productChoices.innerHTML = '';
    products.forEach(product => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'product-choice';
      button.innerHTML = `<strong>${escapeHtml(product.name)}</strong><span>${escapeHtml(product.source_store || '')} · stock ${escapeHtml(fmtNumber(product.stock))}</span>`;
      button.addEventListener('click', () => {
        choiceWrap.hidden = true;
        setProduct(product, barcode);
        nameInput.focus();
      });
      productChoices.appendChild(button);
    });
  }

  async function lookupBarcode(barcode) {
    barcode = String(barcode || '').trim();
    if (!barcode) return;
    barcodeInput.value = barcode;
    setStatus('Looking up…');
    showMessage('');
    try {
      const params = new URLSearchParams({ barcode, store_id: storeSelect.value || '' });
      const response = await fetch(`/scan/api/lookup?${params}`, { credentials: 'same-origin' });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || 'Lookup failed.');
      currentBarcode = barcode;
      choiceWrap.hidden = true;
      if (data.multiple) {
        setProduct(null, barcode);
        previewName.textContent = 'Choose the correct product';
        previewMeta.textContent = `${barcode} appears on more than one product.`;
        itemMode.textContent = 'Multiple matches';
        showChoices(data.products, barcode);
      } else if (data.found) {
        setProduct(data.product, barcode);
        setStatus('Product found', 'ok');
      } else {
        setProduct(null, barcode);
        setStatus('New barcode', 'partial');
        nameInput.focus();
      }
    } catch (error) {
      setStatus('Lookup failed', 'error');
      showMessage(error.message || 'Could not look up that barcode.', 'error');
    }
  }

  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('Camera unavailable', 'error');
      supportEl.textContent = 'This browser cannot access the camera. A USB/Bluetooth barcode scanner will still work through the Barcode field below.';
      return;
    }
    if (!('BarcodeDetector' in globalThis)) {
      setStatus('Camera scanner unavailable', 'error');
      supportEl.textContent = 'This browser does not provide BarcodeDetector. Use Chrome/Edge on a supported device, or use a handheld scanner in the Barcode field.';
      barcodeInput.focus();
      return;
    }
    try {
      supportedFormats = await BarcodeDetector.getSupportedFormats();
      const preferred = ['ean_13','ean_8','upc_a','upc_e','code_128','code_39','code_93','itf_14','codabar'].filter(x => supportedFormats.includes(x));
      detector = new BarcodeDetector({ formats: preferred.length ? preferred : supportedFormats });
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
      video.srcObject = stream;
      await video.play();
      scanning = true;
      startButton.disabled = true;
      stopButton.disabled = false;
      overlay.classList.add('active');
      setStatus('Scanning…', 'ok');
      supportEl.textContent = `Formats detected: ${preferred.length ? preferred.join(', ') : 'browser supported formats'}.`;
      scanFrame();
    } catch (error) {
      stopCamera();
      setStatus('Camera permission needed', 'error');
      supportEl.textContent = error?.message || 'Camera could not be opened.';
    }
  }

  function stopCamera() {
    scanning = false;
    if (scanLoop) cancelAnimationFrame(scanLoop);
    scanLoop = null;
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
    video.srcObject = null;
    startButton.disabled = false;
    stopButton.disabled = true;
    overlay.classList.remove('active');
    if (detector) setStatus('Camera stopped');
  }

  async function scanFrame() {
    if (!scanning || !detector || video.readyState < 2) {
      if (scanning) scanLoop = requestAnimationFrame(scanFrame);
      return;
    }
    try {
      const results = await detector.detect(video);
      if (results?.length) {
        const value = String(results[0].rawValue || '').trim();
        const nowMs = Date.now();
        if (value && (value !== lastCode || nowMs - lastDetectedAt > 1800)) {
          lastCode = value;
          lastDetectedAt = nowMs;
          barcodeInput.value = value;
          setStatus('Barcode captured', 'ok');
          if (navigator.vibrate) navigator.vibrate(100);
          await lookupBarcode(value);
        }
      }
    } catch (_) {
      // Camera frames can temporarily fail while the device autofocuses; keep scanning.
    }
    if (scanning) scanLoop = requestAnimationFrame(scanFrame);
  }

  async function loadRecent() {
    const params = new URLSearchParams({ store_id: storeSelect.value || '' });
    recentList.innerHTML = '<div class="scan-empty">Loading…</div>';
    try {
      const response = await fetch(`/scan/api/recent?${params}`, { credentials: 'same-origin' });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error('Could not load recent scans.');
      if (!data.items?.length) {
        recentList.innerHTML = '<div class="scan-empty">Nothing scanned yet.</div>';
        return;
      }
      recentList.innerHTML = data.items.map(item => `
        <div class="recent-row">
          <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.barcode)} · ${new Date(item.created_at).toLocaleString()}</small></div>
          <strong>+${escapeHtml(fmtNumber(item.quantity))}</strong>
        </div>`).join('');
    } catch (error) {
      recentList.innerHTML = `<div class="scan-empty error">${escapeHtml(error.message)}</div>`;
    }
  }

  startButton.addEventListener('click', startCamera);
  stopButton.addEventListener('click', stopCamera);
  focusButton.addEventListener('click', () => { barcodeInput.focus(); barcodeInput.select(); });
  lookupButton.addEventListener('click', () => lookupBarcode(barcodeInput.value));
  barcodeInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      lookupBarcode(barcodeInput.value);
    }
  });
  quantityInput.addEventListener('input', updateTotals);
  nameInput.addEventListener('input', updateSaveAvailability);
  storeSelect.addEventListener('change', () => {
    setProduct(null, '');
    loadRecent();
  });
  refreshList.addEventListener('click', loadRecent);
  toggleList.addEventListener('click', () => {
    const hidden = recentList.hidden;
    recentList.hidden = !hidden;
    toggleList.textContent = hidden ? 'Hide list' : 'Show list';
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!currentBarcode) return;
    saveButton.disabled = true;
    showMessage('Saving…');
    try {
      const payload = {
        barcode: currentBarcode,
        product_id: productIdInput.value || '',
        name: nameInput.value.trim(),
        quantity: quantityInput.value,
        store_id: storeSelect.value,
      };
      const response = await fetch('/scan/api/save', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...(csrfToken ? {'X-CSRFToken': csrfToken} : {}) },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.message || 'Could not save this item.');
      const stockMessage = data.product.stock_changed
        ? `${fmtNumber(data.product.added)} added. Stock is now ${fmtNumber(data.product.stock)} at ${data.product.store}.`
        : `Saved to the database. Stock was left unchanged at ${fmtNumber(data.product.stock)}.`;
      showMessage(`${data.product.name}: ${stockMessage}`, 'success');
      setStatus('Saved ', 'ok');
      await loadRecent();
      barcodeInput.value = '';
      currentBarcode = '';
      productIdInput.value = '';
      selectedProduct = null;
      itemMode.textContent = 'Ready for next item';
      previewName.textContent = 'Scan the next barcode';
      previewMeta.textContent = 'Camera can keep running.';
      currentStock.textContent = '—';
      currentStock.dataset.value = '0';
      afterStock.textContent = '—';
      nameInput.value = '';
      quantityInput.value = '';
      updateSaveAvailability();
      if (scanning) setStatus('Scanning…', 'ok');
    } catch (error) {
      showMessage(error.message || 'Save failed.', 'error');
      saveButton.disabled = false;
    }
  });

  loadRecent();
  if (window.isSecureContext !== false) {
    supportEl.textContent = 'Camera scanning works here over HTTPS. A handheld scanner can also send codes into the Barcode field.';
  } else {
    supportEl.textContent = 'Camera scanning requires HTTPS. Use the hosted /scan URL rather than an HTTP address.';
  }
})();
