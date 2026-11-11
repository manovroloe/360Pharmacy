
const state = {
  catalog: { products: [], categories: [], branches: [], deals: [], manufacturers: [] },
  user: null,
  favorites: new Set(),
  cart: JSON.parse(localStorage.getItem('360pharmacy_cart') || '[]'),
  category: 'all',
  search: '',
  dealKind: 'hot_deal',
  addresses: []
};

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

const peso = n => new Intl.NumberFormat('en-PH', {
  style: 'currency',
  currency: 'PHP'
}).format(Number(n || 0));

const dateTime = value => value
  ? new Date(value).toLocaleString('en-PH', {
      dateStyle: 'medium',
      timeStyle: 'short'
    })
  : '—';

const escapeHTML = value => String(value ?? '').replace(
  /[&<>'"]/g,
  c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;'
  }[c])
);

function icons() {
  window.lucide?.createIcons();
}

function toast(message, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<i data-lucide="${type === 'error' ? 'circle-alert' : 'circle-check'}"></i><span>${escapeHTML(message)}</span>`;
  $('#toastArea').appendChild(el);
  icons();
  setTimeout(() => el.remove(), 3800);
}

function openModal(id) {
  const el = $(`#${id}`);
  if (!el) return;
  el.classList.add('open');
  el.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  icons();
}

function closeModal(id) {
  const el = $(`#${id}`);
  if (!el) return;
  el.classList.remove('open');
  el.setAttribute('aria-hidden', 'true');
  if (!$('.modal.open')) {
    document.body.classList.remove('modal-open');
  }
}

function productById(id) {
  return state.catalog.products.find(p => String(p.id) === String(id));
}

function requireCustomer() {
  if (!state.user) {
    location.assign('/login?next=' + encodeURIComponent('/'));
    return false;
  }
  if (state.user.profile.role !== 'customer') {
    toast('Customer-only feature. Open your assigned workspace instead.', 'error');
    return false;
  }
  return true;
}

function renderSession() {
  const text = $('#accountText');
  if (state.user) {
    text.textContent = state.user.profile.full_name?.split(' ')[0] || 'Account';
  } else {
    text.textContent = 'Login';
  }
}

async function restoreSession() {
  if (!API.token()) return;
  try {
    state.user = await API.me();
    if (state.user.profile.role === 'customer') {
      await loadFavorites();
    }
  } catch (_) {
    API.clearSession();
    state.user = null;
  }
  renderSession();
}

async function loadCatalog() {
  try {
    const data = await API.catalog();
    state.catalog = data;
    $('#dataMode').innerHTML = '<i data-lucide="database-zap"></i> Live Supabase PostgreSQL';
    $('#dataMode').classList.add('live');
    $('#catalogMessage').textContent = data.products.length
      ? ''
      : 'No medicines available yet.';
  } catch (err) {
    state.catalog = {
      products: [],
      categories: [],
      branches: [],
      deals: [],
      manufacturers: []
    };
    $('#dataMode').innerHTML = '<i data-lucide="database-x"></i> Setup needed';
    $('#catalogMessage').textContent = err.message;
    toast(err.message, 'error');
  }

  renderCategories();
  renderProducts();
  renderDeals();
  renderBranches();
  renderPartners();
  populateProductSelects();
  renderCart();
  icons();
}

function renderCategories() {
  const wrap = $('#categoryChips');
  wrap.innerHTML = `<button class="chip active" data-category="all"><i data-lucide="layout-grid"></i>All</button>` +
    state.catalog.categories.map(c =>
      `<button class="chip" data-category="${escapeHTML(c.slug)}"><i data-lucide="${escapeHTML(c.icon || 'pill')}"></i>${escapeHTML(c.name)}</button>`
    ).join('');

  $$('.chip', wrap).forEach(btn => btn.onclick = () => {
    $$('.chip', wrap).forEach(x => x.classList.remove('active'));
    btn.classList.add('active');
    state.category = btn.dataset.category;
    renderProducts();
  });
  icons();
}

function productImage(p) {
  if (p.image_url) {
    return `<img src="${escapeHTML(p.image_url)}" alt="${escapeHTML(p.name)}" loading="lazy">`;
  }
  return `<div class="product-placeholder"><i data-lucide="pill"></i><span>${escapeHTML(p.generic_name || p.name)}</span></div>`;
}

function renderProducts(list = null) {
  const search = state.search.trim().toLowerCase();
  let products = list || state.catalog.products.filter(p => {
    const categoryOk = state.category === 'all' || p.category_slug === state.category;
    const hay = `${p.name || ''} ${p.generic_name || ''} ${p.brand || ''} ${p.short_use || ''}`.toLowerCase();
    return categoryOk && hay.includes(search);
  });

  $('#productCount').textContent = `${products.length} medicine${products.length === 1 ? '' : 's'}`;
  const grid = $('#productGrid');

  if (!products.length) {
    grid.innerHTML = `<div class="empty-state"><i data-lucide="package-search"></i><h3>No medicines to show</h3><p>${state.catalog.products.length ? 'Try another search or category.' : 'Admin can add the first real product from the 360 Pharmacy Workspace.'}</p></div>`;
    icons();
    return;
  }

  grid.innerHTML = products.map(p => {
    const saved = state.favorites.has(String(p.id));
    const sale = Number(p.sale_price) < Number(p.selling_price);

    return `<article class="product-card">
      <div class="product-media">${productImage(p)}
        <button class="save-btn ${saved ? 'saved' : ''}" data-save="${p.id}" aria-label="Save ${escapeHTML(p.name)}"><i data-lucide="heart"></i></button>
        <span class="${p.requires_prescription ? 'rx-badge' : 'otc-badge'}">${p.requires_prescription ? 'Rx' : 'OTC'}</span>
        ${p.promotion ? `<span class="deal-badge">${escapeHTML(p.promotion.kind.replace('_', ' '))}</span>` : ''}
      </div>
      <div class="product-body">
        <div class="product-meta">${escapeHTML(p.manufacturer_name || p.brand || 'Pharmacy product')} · ${escapeHTML(p.dosage_form || 'Medicine')}</div>
        <h3>${escapeHTML(p.name)}</h3>
        <p>${escapeHTML(p.short_use || p.generic_name || 'Ask the pharmacist for appropriate medicine information.')}</p>
        <div class="stock-row"><span class="status-dot ${p.available_quantity <= 0 ? 'off' : ''}"></span>${escapeHTML(p.stock_label || 'Check stock')}</div>
        <div class="product-footer">
          <div class="price-stack">
            ${sale ? `<small>${peso(p.selling_price)}</small>` : ''}
            <strong>${peso(p.sale_price ?? p.selling_price)}</strong>
          </div>
          <button class="add-btn" data-add="${p.id}" ${p.available_quantity <= 0 ? 'disabled' : ''}>
            <i data-lucide="${p.requires_prescription ? 'file-up' : 'plus'}"></i>
            ${p.requires_prescription ? 'Prescription' : 'Add'}
          </button>
        </div>
      </div>
    </article>`;
  }).join('');

  $$('[data-save]', grid).forEach(btn =>
    btn.onclick = () => toggleFavorite(btn.dataset.save)
  );

  $$('[data-add]', grid).forEach(btn =>
    btn.onclick = () => addProduct(btn.dataset.add)
  );

  icons();
}

async function toggleFavorite(id) {
  if (!requireCustomer()) return;

  try {
    if (state.favorites.has(String(id))) {
      await API.removeFavorite(id);
      state.favorites.delete(String(id));
      toast('Removed from saved medicines.');
    } else {
      await API.addFavorite(id);
      state.favorites.add(String(id));
      toast('Saved for future review.');
    }
    renderProducts();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function loadFavorites() {
  try {
    const rows = await API.favorites();
    state.favorites = new Set(rows.map(x => String(x.product_id)));
  } catch (_) {
    state.favorites = new Set();
  }
}

function addProduct(id) {
  if (!requireCustomer()) return;

  const p = productById(id);
  if (!p) return;

  if (p.requires_prescription) {
    $('#rxProductSelect').value = p.id;
    openModal('prescriptionModal');
    return;
  }

  const existing = state.cart.find(x => String(x.product_id) === String(id));

  if (existing) {
    existing.quantity += 1;
  } else {
    state.cart.push({ product_id: p.id, quantity: 1 });
  }

  saveCart();
  toast(`${p.name} added to your basket.`);
}

function saveCart() {
  localStorage.setItem('360pharmacy_cart', JSON.stringify(state.cart));
  renderCart();
}

function cartPrice(item) {
  const p = productById(item.product_id);
  return Number(p?.sale_price ?? p?.selling_price ?? 0);
}

function renderCart() {
  const qty = state.cart.reduce((a, b) => a + Number(b.quantity || 0), 0);
  $('#cartCount').textContent = qty;

  const body = $('#cartItems');

  if (!state.cart.length) {
    body.innerHTML = `<div class="empty-state mini"><i data-lucide="shopping-basket"></i><h3>Your basket is empty</h3><p>Choose an OTC medicine to begin.</p></div>`;
  } else {
    body.innerHTML = state.cart.map(i => {
      const p = productById(i.product_id);
      if (!p) return '';

      return `<div class="cart-item">
        <div class="cart-icon">${p.image_url ? `<img src="${escapeHTML(p.image_url)}" alt="">` : '<i data-lucide="pill"></i>'}</div>
        <div>
          <strong>${escapeHTML(p.name)}</strong>
          <small>${peso(cartPrice(i))} each</small>
          <div class="qty-control">
            <button data-cart-op="minus" data-id="${p.id}">−</button>
            <span>${i.quantity}</span>
            <button data-cart-op="plus" data-id="${p.id}">+</button>
          </div>
        </div>
        <strong>${peso(cartPrice(i) * i.quantity)}</strong>
      </div>`;
    }).join('');
  }

  $$('[data-cart-op]', body).forEach(btn => btn.onclick = () => {
    const item = state.cart.find(x => String(x.product_id) === String(btn.dataset.id));
    if (!item) return;

    item.quantity += btn.dataset.cartOp === 'plus' ? 1 : -1;

    if (item.quantity <= 0) {
      state.cart = state.cart.filter(x => String(x.product_id) !== String(btn.dataset.id));
    }

    saveCart();
  });

  const subtotal = state.cart.reduce(
    (sum, i) => sum + cartPrice(i) * i.quantity,
    0
  );

  $('#cartSubtotal').textContent = peso(subtotal);
  $('#checkoutTotal').textContent = peso(subtotal);
  $('#checkoutBtn').disabled = !state.cart.length;
  icons();
}

function renderDeals() {
  const list = state.catalog.deals.filter(d => d.kind === state.dealKind);
  const wrap = $('#dealGrid');

  if (!list.length) {
    wrap.innerHTML = `<div class="empty-state deal-empty"><i data-lucide="badge-percent"></i><h3>No active ${state.dealKind.replace('_', ' ')} right now</h3><p>When the admin schedules a promotion in Supabase PostgreSQL, it appears here automatically.</p></div>`;
    icons();
    return;
  }

  wrap.innerHTML = list.map(d =>
    `<article class="deal-card">
      ${d.banner_image_url
        ? `<img src="${escapeHTML(d.banner_image_url)}" alt="">`
        : `<div class="deal-art"><i data-lucide="badge-percent"></i></div>`}
      <div>
        <span>${escapeHTML(d.kind.replace('_', ' '))}</span>
        <h3>${escapeHTML(d.title)}</h3>
        <p>${escapeHTML(d.subtitle || `${d.product_count || 0} linked medicine(s)`)}</p>
        <strong>${d.discount_type === 'percentage'
          ? `${Number(d.discount_value)}% OFF`
          : `${peso(d.discount_value)} OFF`}</strong>
      </div>
    </article>`
  ).join('');

  icons();
}

function branchMapUrl(branch) {
  const lat = Number(branch.latitude);
  const lng = Number(branch.longitude);
  const valid =
    branch.latitude !== null &&
    branch.latitude !== undefined &&
    branch.longitude !== null &&
    branch.longitude !== undefined &&
    Number.isFinite(lat) &&
    Number.isFinite(lng) &&
    Math.abs(lat) <= 90 &&
    Math.abs(lng) <= 180;

  const address = valid
    ? `${lat},${lng}`
    : [
        branch.name,
        branch.address_line,
        branch.barangay,
        branch.city,
        branch.province,
        'Philippines'
      ].filter(Boolean).join(', ');

  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;
}

function renderBranches() {
  const wrap = $('#branchGrid');

  if (!state.catalog.branches.length) {
    wrap.innerHTML = `<div class="empty-state"><i data-lucide="store"></i><h3>No branch addresses yet</h3><p>The admin must add real branch/pickup addresses first.</p></div>`;
    icons();
    return;
  }

  wrap.innerHTML = state.catalog.branches.map(b =>
    `<article class="branch-card">
      <div class="branch-icon"><i data-lucide="store"></i></div>
      <div>
        <h3>${escapeHTML(b.name)}</h3>
        <p>${escapeHTML([
          b.address_line,
          b.barangay,
          b.city,
          b.province,
          b.postal_code
        ].filter(Boolean).join(', '))}</p>
        <div class="branch-flags">
          ${b.is_pickup_enabled ? '<span><i data-lucide="shopping-bag"></i>Pickup</span>' : ''}
          ${b.is_delivery_enabled ? '<span><i data-lucide="truck"></i>Delivery source</span>' : ''}
        </div>
        ${b.pickup_instructions ? `<small>${escapeHTML(b.pickup_instructions)}</small>` : ''}
        <div class="stack-actions">
          <a class="outline-btn small" target="_blank" rel="noopener noreferrer" href="${escapeHTML(branchMapUrl(b))}">
            <i data-lucide="map-pin"></i>View location
          </a>
        </div>
      </div>
    </article>`
  ).join('');

  icons();
}

function renderPartners() {
  const wrap = $('#partnerGrid');

  if (!state.catalog.manufacturers.length) {
    wrap.innerHTML = `<div class="empty-inline">Partner manufacturers added by the admin will appear here.</div>`;
    return;
  }

  wrap.innerHTML = state.catalog.manufacturers.map(m =>
    `<article class="partner-card">
      ${m.logo_url
        ? `<img src="${escapeHTML(m.logo_url)}" alt="${escapeHTML(m.name)}">`
        : '<i data-lucide="factory"></i>'}
      <strong>${escapeHTML(m.name)}</strong>
    </article>`
  ).join('');

  icons();
}

// Customer address location dropdowns
let addressLocationsLoaded = false;

const addressOptions = (rows, hint) =>
  `<option value="">${hint}</option>` +
  rows.map(r =>
    `<option value="${escapeHTML(r.name)}" data-code="${escapeHTML(r.code)}">${escapeHTML(r.name)}</option>`
  ).join('');

async function setupAddressLocations() {
  const region = $('#addressRegion');
  const province = $('#addressProvince');

  if (!region || addressLocationsLoaded) return;

  region.innerHTML = '<option value="">Loading regions…</option>';

  try {
    region.innerHTML = addressOptions(
      await API.addressRegions(),
      'Select region'
    );
    addressLocationsLoaded = true;
  } catch (err) {
    region.innerHTML = '<option value="">Regions unavailable</option>';
    toast(err.message, 'error');
  }
}

function resetAddressSelect(el, hint) {
  el.disabled = true;
  el.required = true;
  el.innerHTML = `<option value="">${hint}</option>`;
}

function selectedCode(el) {
  return el.selectedOptions[0]?.dataset.code || '';
}

async function onRegionChanged() {
  const region = $('#addressRegion');
  const prov = $('#addressProvince');
  const city = $('#addressCity');
  const brgy = $('#addressBarangay');

  resetAddressSelect(prov, 'Select province');
  resetAddressSelect(city, 'Select city');
  resetAddressSelect(brgy, 'Select barangay');

  const code = selectedCode(region);
  if (!code) return;

  const ticket = region.value;

  try {
    const provinces = await API.addressProvinces(code);
    if (region.value !== ticket) return;

    if (provinces.length) {
      prov.innerHTML = addressOptions(provinces, 'Select province');
      prov.disabled = false;
    } else {
      prov.innerHTML = '<option value="Metro Manila">Metro Manila</option>';
      prov.disabled = false;

      const cities = await API.addressRegionCities(code);
      if (region.value !== ticket) return;

      city.innerHTML = addressOptions(cities, 'Select city');
      city.disabled = false;
    }
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function onProvinceChanged() {
  const province = $('#addressProvince');
  const city = $('#addressCity');
  const brgy = $('#addressBarangay');

  resetAddressSelect(city, 'Select city');
  resetAddressSelect(brgy, 'Select barangay');

  const code = selectedCode(province);
  if (!code) return;

  try {
    const cities = await API.addressCities(code);
    if (selectedCode(province) !== code) return;

    city.innerHTML = addressOptions(cities, 'Select city');
    city.disabled = false;
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function onCityChanged() {
  const city = $('#addressCity');
  const brgy = $('#addressBarangay');

  resetAddressSelect(brgy, 'Select barangay');

  const code = selectedCode(city);
  if (!code) return;

  try {
    const rows = await API.addressBarangays(code);
    if (selectedCode(city) !== code) return;

    brgy.innerHTML = addressOptions(rows, 'Select barangay');
    brgy.disabled = false;
  } catch (err) {
    toast(err.message, 'error');
  }
}

function populateProductSelects() {
  const rxProducts = state.catalog.products.filter(
    p => p.requires_prescription
  );

  $('#rxProductSelect').innerHTML =
    `<option value="">Choose medicine</option>` +
    rxProducts.map(p =>
      `<option value="${p.id}">${escapeHTML(p.name)}</option>`
    ).join('');

  $('#consultProductSelect').innerHTML =
    `<option value="">No specific medicine</option>` +
    state.catalog.products.map(p =>
      `<option value="${p.id}">${escapeHTML(p.name)}</option>`
    ).join('');
}

async function prepareCheckout() {
  if (!requireCustomer()) return;

  if (!state.cart.length) {
    return toast('Your basket is empty.', 'error');
  }

  try {
    state.addresses = await API.addresses();
  } catch (err) {
    return toast(err.message, 'error');
  }

  renderPickupChoices();
  renderAddressChoices();
  renderPaymentChoices('pickup');
  openModal('checkoutModal');
}

function renderPickupChoices() {
  const branches = state.catalog.branches.filter(
    b => b.is_pickup_enabled
  );

  $('#pickupChoices').innerHTML = branches.length
    ? branches.map((b, i) =>
        `<label class="choice-card">
          <input type="radio" name="branch_id" value="${b.id}" ${i === 0 ? 'checked' : ''}>
          <span>
            <strong>${escapeHTML(b.name)}</strong>
            <small>${escapeHTML([
              b.address_line,
              b.barangay,
              b.city,
              b.province
            ].filter(Boolean).join(', '))}</small>
            ${b.pickup_instructions
              ? `<em>${escapeHTML(b.pickup_instructions)}</em>`
              : ''}
          </span>
          <i data-lucide="map-pin"></i>
        </label>`
      ).join('')
    : `<div class="empty-inline">No pickup address has been configured by the admin.</div>`;

  icons();
}

function renderAddressChoices() {
  $('#addressChoices').innerHTML = state.addresses.length
    ? state.addresses.map((a, i) =>
        `<label class="choice-card address-choice">
          <input type="radio" name="address_id" value="${a.id}" ${(a.is_default || i === 0) ? 'checked' : ''}>
          <span>
            <strong>${escapeHTML(a.label)} · ${escapeHTML(a.recipient_name)}</strong>
            <small>${escapeHTML(a.recipient_phone)}</small>
            <small>${escapeHTML([
              a.street_address,
              a.barangay,
              a.city,
              a.province,
              a.postal_code
            ].filter(Boolean).join(', '))}</small>
            ${a.landmark
              ? `<em>Landmark: ${escapeHTML(a.landmark)}</em>`
              : ''}
          </span>
          <i data-lucide="map-pin-house"></i>
        </label>`
      ).join('')
    : `<div class="empty-inline">No saved delivery address yet. Add one to continue.</div>`;

  icons();
}

function renderPaymentChoices(fulfillment) {
  const cash = fulfillment === 'pickup'
    ? 'cash_on_pickup'
    : 'cash_on_delivery';

  const cashLabel = fulfillment === 'pickup'
    ? 'Cash on Pickup'
    : 'Cash on Delivery';

  $('#paymentChoices').innerHTML = `
    <label class="payment-card">
      <input type="radio" name="payment_method" value="${cash}" checked>
      <i data-lucide="banknote"></i>
      <span>
        <strong>${cashLabel}</strong>
        <small>Pay when the order is received</small>
      </span>
    </label>
    <label class="payment-card">
      <input type="radio" name="payment_method" value="online" disabled>
      <i data-lucide="wallet-cards"></i>
      <span>
        <strong>Online Payment (coming soon)</strong>
        <small>Gateway integration is not connected. Please use cash for now.</small>
      </span>
    </label>
  `;

  icons();
}

async function showAccount(tab = 'orders') {
  if (!requireCustomer()) return;

  $('#accountName').textContent = state.user.profile.full_name || 'Customer';
  $('#accountEmail').textContent = state.user.profile.email || '';

  openModal('accountModal');
  await renderAccountTab(tab);
}

async function renderAccountTab(tab) {
  $$('.account-tabs button').forEach(b =>
    b.classList.toggle('active', b.dataset.accountTab === tab)
  );

  const panel = $('#accountPanel');
  panel.innerHTML = `<div class="loading-state"><i data-lucide="loader-circle"></i>Loading…</div>`;
  icons();

  try {
    if (tab === 'orders') {
      const orders = await API.myOrders();

      panel.innerHTML = orders.length
        ? `<div class="account-list">${orders.map(o =>
            `<article class="account-card">
              <div>
                <span class="status-tag">${escapeHTML(o.status.replaceAll('_', ' '))}</span>
                <h3>${escapeHTML(o.order_number)}</h3>
                <p>${dateTime(o.created_at)} · ${escapeHTML(o.fulfillment)}</p>
                <small>${o.items.map(i =>
                  `${escapeHTML(i.product_name_snapshot)} × ${i.quantity}`
                ).join(' · ')}</small>
              </div>
              <div class="account-card-end">
                <strong>${peso(o.total_amount)}</strong>
                <small>${escapeHTML(o.payment_status)}</small>
                <button class="outline-btn small" data-track="${o.id}">
                  <i data-lucide="route"></i>Track
                </button>
                ${o.fulfillment === 'pickup' && o.status === 'ready_for_pickup'
                  ? `<button class="primary-btn small" data-confirm-order="${o.id}">Picked Up</button>`
                  : o.fulfillment === 'delivery' && o.status === 'delivered'
                  ? `<button class="primary-btn small" data-confirm-order="${o.id}">Order Received</button>`
                  : ''}
              </div>
            </article>`
          ).join('')}</div>`
        : `<div class="empty-state mini"><i data-lucide="package-open"></i><h3>No orders yet</h3><p>Your real orders will appear here.</p></div>`;

      $$('[data-track]', panel).forEach(b =>
        b.onclick = () => showTracking(b.dataset.track)
      );

      $$('[data-confirm-order]', panel).forEach(b => b.onclick = async () => {
        try {
          await API.confirmOrderReceipt(b.dataset.confirmOrder);
          toast('Order confirmation recorded.');
          renderAccountTab('orders');
        } catch (err) {
          toast(err.message, 'error');
        }
      });

    } else if (tab === 'favorites') {
      await loadFavorites();

      const list = state.catalog.products.filter(
        p => state.favorites.has(String(p.id))
      );

      panel.innerHTML = `<div class="product-grid account-products" id="savedProductGrid"></div>`;
      const temp = $('#savedProductGrid');

      temp.innerHTML = list.length
        ? list.map(p =>
            `<article class="mini-product">
              <div>${productImage(p)}</div>
              <span>
                <strong>${escapeHTML(p.name)}</strong>
                <small>${escapeHTML(p.short_use || p.generic_name || '')}</small>
              </span>
              <button class="outline-btn small" data-remove-save="${p.id}">Remove</button>
            </article>`
          ).join('')
        : `<div class="empty-inline">No saved medicines yet.</div>`;

      $$('[data-remove-save]', temp).forEach(b => b.onclick = async () => {
        await toggleFavorite(b.dataset.removeSave);
        renderAccountTab('favorites');
      });

    } else if (tab === 'prescriptions') {
      const rows = await API.prescriptions();

      panel.innerHTML = rows.length
        ? `<div class="account-list">${rows.map(r =>
            `<article class="account-card">
              <div>
                <span class="status-tag ${r.status}">${escapeHTML(r.status.replace('_', ' '))}</span>
                <h3>${escapeHTML(productById(r.product_id)?.name || 'Prescription')}</h3>
                <p>${dateTime(r.created_at)}</p>
                ${r.pharmacist_note
                  ? `<small>Pharmacist: ${escapeHTML(r.pharmacist_note)}</small>`
                  : ''}
              </div>
            </article>`
          ).join('')}</div>`
        : `<div class="empty-inline">No prescription submissions yet.</div>`;

    } else if (tab === 'consultations') {
      const rows = await API.consultations();

      panel.innerHTML = rows.length
        ? `<div class="consult-list">${rows.map(c =>
            `<article class="consult-card">
              <div class="consult-head">
                <div>
                  <span class="status-tag">${escapeHTML(c.status.replace('_', ' '))}</span>
                  <h3>${escapeHTML(c.subject)}</h3>
                </div>
                <small>${dateTime(c.created_at)}</small>
              </div>

              <div class="message-thread">
                ${c.messages.map(m =>
                  `<div class="message ${m.sender_role === 'customer' ? 'mine' : 'staff'}">
                    <strong>${escapeHTML(m.sender_role)}</strong>
                    <p>${escapeHTML(m.message)}</p>
                    <small>${dateTime(m.created_at)}</small>
                  </div>`
                ).join('')}
              </div>

              <form class="inline-reply" data-customer-reply="${c.id}">
                <input name="message" placeholder="Reply to pharmacist" required>
                <button class="primary-btn small">Send</button>
              </form>
            </article>`
          ).join('')}</div>`
        : `<div class="empty-inline">No pharmacist consultations yet.</div>`;

      $$('[data-customer-reply]', panel).forEach(f => f.onsubmit = async e => {
        e.preventDefault();

        try {
          await API.customerReply(f.dataset.customerReply, {
            message: new FormData(f).get('message')
          });
          toast('Reply sent.');
          renderAccountTab('consultations');
        } catch (err) {
          toast(err.message, 'error');
        }
      });

    } else if (tab === 'addresses') {
      // DELETE ADDRESS FEATURE
      state.addresses = await API.addresses();

      panel.innerHTML = `
        <div class="block-head">
          <h3>Saved delivery addresses</h3>

          <button class="primary-btn small" id="accountAddAddress">
            <i data-lucide="plus"></i>Add address
          </button>
        </div>

        <div class="account-list">
          ${state.addresses.map(a => `
            <article class="account-card">
              <div>
                <span class="status-tag">${escapeHTML(a.label)}</span>
                <h3>${escapeHTML(a.recipient_name)}</h3>
                <p>${escapeHTML(a.recipient_phone)}</p>
                <small>${escapeHTML([
                  a.street_address,
                  a.barangay,
                  a.city,
                  a.province,
                  a.postal_code
                ].filter(Boolean).join(', '))}</small>
              </div>

              <div class="account-card-end">
                ${a.is_default
                  ? '<strong class="default-badge">Default</strong>'
                  : ''}

                <button
                  type="button"
                  class="outline-btn small"
                  data-delete-address="${escapeHTML(a.id)}"
                  aria-label="Delete ${escapeHTML(a.label)} address">
                  <i data-lucide="trash-2"></i>Delete
                </button>
              </div>
            </article>
          `).join('') || '<div class="empty-inline">No saved address yet.</div>'}
        </div>
      `;

      $('#accountAddAddress').onclick = () => {
        openModal('addressModal');
        setupAddressLocations();
      };

      $$('[data-delete-address]', panel).forEach(button => {
        button.onclick = async () => {
          if (!window.confirm('Delete this saved address?')) {
            return;
          }

          button.disabled = true;

          try {
            await API.deleteAddress(button.dataset.deleteAddress);
            await renderAccountTab('addresses');
            renderAddressChoices();
            toast('Address deleted.');
          } catch (err) {
            button.disabled = false;
            toast(err.message, 'error');
          }
        };
      });
    }
  } catch (err) {
    panel.innerHTML = `<div class="error-state">${escapeHTML(err.message)}</div>`;
  }

  icons();
}

async function showTrackOrders() {
  if (!requireCustomer()) return;

  const panel = $('#trackOrdersPanel');
  openModal('trackOrdersModal');
  panel.innerHTML = '<div class="loading-state"><i data-lucide="loader-circle"></i>Loading orders…</div>';
  icons();

  try {
    const orders = await API.myOrders();

    panel.innerHTML = orders.length
      ? `<div class="account-list">${orders.map(o =>
          `<article class="account-card">
            <div>
              <span class="status-tag ${o.status}">${escapeHTML(o.status.replaceAll('_', ' '))}</span>
              <h3>${escapeHTML(o.order_number)}</h3>
              <p>${dateTime(o.created_at)} · ${escapeHTML(o.fulfillment)}</p>
            </div>

            <div class="account-card-end">
              <strong>${peso(o.total_amount)}</strong>

              <button class="outline-btn small" data-service-track="${o.id}">
                <i data-lucide="route"></i>Track
              </button>

              ${o.fulfillment === 'pickup' && o.status === 'ready_for_pickup'
                ? `<button class="primary-btn small" data-service-confirm="${o.id}">Picked Up</button>`
                : o.fulfillment === 'delivery' && o.status === 'delivered'
                ? `<button class="primary-btn small" data-service-confirm="${o.id}">Order Received</button>`
                : ''}
            </div>
          </article>`
        ).join('')}</div>`
      : `<div class="empty-state mini"><i data-lucide="package-open"></i><h3>No orders yet</h3><p>Your orders will appear here.</p></div>`;

    $$('[data-service-track]', panel).forEach(
      b => b.onclick = () => showTracking(b.dataset.serviceTrack)
    );

    $$('[data-service-confirm]', panel).forEach(b => b.onclick = async () => {
      try {
        await API.confirmOrderReceipt(b.dataset.serviceConfirm);
        toast('Order confirmation recorded.');
        showTrackOrders();
      } catch (err) {
        toast(err.message, 'error');
      }
    });

    icons();
  } catch (err) {
    panel.innerHTML = `<div class="error-state">${escapeHTML(err.message)}</div>`;
  }
}

async function showTracking(orderId) {
  if (!requireCustomer()) return;

  try {
    const data = await API.tracking(orderId);
    const order = data.order;

    $('#trackingTitle').textContent = order.order_number;

    const canonical = order.fulfillment === 'pickup'
      ? ['placed', 'confirmed', 'preparing', 'ready_for_pickup', 'picked_up', 'completed']
      : ['placed', 'confirmed', 'preparing', 'handed_to_courier', 'in_transit', 'out_for_delivery', 'delivered', 'order_received', 'completed'];

    const reached = new Set(data.history.map(h => h.status));
    const currentIndex = canonical.indexOf(order.status);

    const simpleStages = order.fulfillment === 'pickup'
      ? ['Ship out', 'Ready for pickup', 'Completed']
      : ['Ship out', 'Shipping', 'Out for delivery', 'Completed'];

    const stageIndex = order.fulfillment === 'pickup'
      ? (['placed', 'confirmed', 'preparing'].includes(order.status)
          ? 0
          : order.status === 'ready_for_pickup'
          ? 1
          : 2)
      : (['placed', 'confirmed', 'preparing', 'handed_to_courier'].includes(order.status)
          ? 0
          : order.status === 'in_transit'
          ? 1
          : order.status === 'out_for_delivery'
          ? 2
          : ['delivered', 'order_received', 'completed'].includes(order.status)
          ? 3
          : 0);

    const lat = Number(data.branch?.latitude || 0);
    const lng = Number(data.branch?.longitude || 0);

    const location = data.branch
      ? escapeHTML([
          data.branch.address_line,
          data.branch.city,
          data.branch.province
        ].filter(Boolean).join(', '))
      : '';

    const map = lat && lng
      ? `<section class="tracking-map">
          <div class="tracking-map-head">
            <div>
              <strong>${escapeHTML(data.branch?.name || 'Order branch')}</strong>
              <small>${location}</small>
            </div>
            <i data-lucide="map-pinned"></i>
          </div>
          <iframe
            title="Order branch location"
            loading="lazy"
            src="https://www.openstreetmap.org/export/embed.html?bbox=${lng - 0.02}%2C${lat - 0.02}%2C${lng + 0.02}%2C${lat + 0.02}&amp;layer=mapnik&amp;marker=${lat}%2C${lng}">
          </iframe>
        </section>`
      : (data.branch
          ? `<div class="empty-inline">
              Ordered from ${escapeHTML(data.branch.name)} · ${location}
              <a href="${escapeHTML(branchMapUrl(data.branch))}" target="_blank" rel="noopener noreferrer">View map</a>
            </div>`
          : '');

    $('#trackingBody').innerHTML = `
      <div class="tracking-summary">
        <span>${escapeHTML(order.fulfillment)}</span>
        <strong>${peso(order.total_amount)}</strong>
        <small>Payment: ${escapeHTML(order.payment_status)}</small>
      </div>

      <div class="simple-track-stages">
        ${simpleStages.map((label, i) =>
          `<span class="${i <= stageIndex ? 'done' : ''} ${i === stageIndex ? 'current' : ''}">
            ${escapeHTML(label)}
          </span>`
        ).join('')}
      </div>

      ${map}

      <div class="tracking-timeline">
        ${canonical.map((s, i) => {
          const hist = data.history.find(h => h.status === s);
          const done = reached.has(s) || i <= currentIndex;

          return `<div class="track-step ${done ? 'done' : ''} ${s === order.status ? 'current' : ''}">
            <div class="track-dot">
              <i data-lucide="${['delivered', 'picked_up', 'order_received', 'completed'].includes(s) ? 'check' : 'circle'}"></i>
            </div>
            <div>
              <strong>${escapeHTML(s.replaceAll('_', ' '))}</strong>
              <small>${hist ? dateTime(hist.created_at) : 'Waiting'}</small>
              ${hist?.note ? `<p>${escapeHTML(hist.note)}</p>` : ''}
            </div>
          </div>`;
        }).join('')}
      </div>

      ${data.delivery?.tracking_url
        ? `<a class="primary-btn" href="${escapeHTML(data.delivery.tracking_url)}" target="_blank" rel="noopener">Open courier tracking</a>`
        : ''}

      ${order.fulfillment === 'pickup' && order.status === 'ready_for_pickup'
        ? `<button class="primary-btn" data-tracking-confirm="${order.id}">Picked Up</button>`
        : order.fulfillment === 'delivery' && order.status === 'delivered'
        ? `<button class="primary-btn" data-tracking-confirm="${order.id}">Order Received</button>`
        : ''}
    `;

    openModal('trackingModal');

    const confirmBtn = $('[data-tracking-confirm]');

    if (confirmBtn) {
      confirmBtn.onclick = async () => {
        try {
          await API.confirmOrderReceipt(confirmBtn.dataset.trackingConfirm);
          toast('Order confirmation recorded.');
          closeModal('trackingModal');
          showTrackOrders();
        } catch (err) {
          toast(err.message, 'error');
        }
      };
    }

    icons();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function setupEvents() {
  $$('.modal-close,[data-close]').forEach(b =>
    b.onclick = () => closeModal(
      b.dataset.close || b.closest('.modal')?.id
    )
  );

  $$('.modal').forEach(m => m.addEventListener('click', e => {
    if (e.target === m) closeModal(m.id);
  }));

  const menuBtn = $('#mobileMenuBtn');
  const quickMenu = $('#mobileNav');

  const setQuickMenu = open => {
    quickMenu.classList.toggle('open', open);
    menuBtn.setAttribute('aria-expanded', String(open));
  };

  menuBtn.onclick = e => {
    e.stopPropagation();
    setQuickMenu(!quickMenu.classList.contains('open'));
  };

  $$('#mobileNav a').forEach(
    a => a.onclick = () => setQuickMenu(false)
  );

  document.addEventListener('click', e => {
    if (
      !quickMenu.contains(e.target) &&
      e.target !== menuBtn &&
      !menuBtn.contains(e.target)
    ) {
      setQuickMenu(false);
    }
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') setQuickMenu(false);
  });

  $('#cartOpenBtn').onclick = () => {
    $('#cartDrawer').classList.add('open');
    $('#drawerBackdrop').classList.add('show');
  };

  $('#cartCloseBtn').onclick = $('#drawerBackdrop').onclick = () => {
    $('#cartDrawer').classList.remove('open');
    $('#drawerBackdrop').classList.remove('show');
  };

  $('#checkoutBtn').onclick = prepareCheckout;

  $('#accountBtn').onclick = () => {
    if (!state.user) {
      location.assign('/login?next=/');
      return;
    }

    state.user.profile.role === 'customer'
      ? showAccount()
      : location.assign('/workspace');
  };

  $('#serviceRxBtn').onclick = $('#uploadRxBtn').onclick = () =>
    requireCustomer() && openModal('prescriptionModal');

  $('#askPharmacistBtn').onclick = () =>
    requireCustomer() && openModal('consultModal');

  $('#trackOrderBtn').onclick = () =>
    requireCustomer() && showTrackOrders();

  $('#favoritesBtn').onclick = () =>
    requireCustomer() && showAccount('favorites');

  $('#heroSearch').addEventListener('input', e => {
    $('#medicineSearch').value = e.target.value;
    state.search = e.target.value;
    renderProducts();
  });

  $('#medicineSearch').addEventListener('input', e => {
    state.search = e.target.value;
    renderProducts();
  });

  $$('#dealTabs button').forEach(btn => btn.onclick = () => {
    $$('#dealTabs button').forEach(x => x.classList.remove('active'));
    btn.classList.add('active');
    state.dealKind = btn.dataset.kind;
    renderDeals();
  });

  $$('.account-tabs button').forEach(
    btn => btn.onclick = () => renderAccountTab(btn.dataset.accountTab)
  );

  $('#logoutBtn').onclick = async () => {
    await API.logout();
    state.user = null;
    state.favorites.clear();
    state.cart = [];
    saveCart();
    renderSession();
    closeModal('accountModal');
    toast('Logged out.');
  };

  $('#addAddressBtn').onclick = () => {
    openModal('addressModal');
    setupAddressLocations();
  };

  $('#addressRegion').addEventListener('change', onRegionChanged);
  $('#addressProvince').addEventListener('change', onProvinceChanged);
  $('#addressCity').addEventListener('change', onCityChanged);

  $$('.fulfillment-tabs button').forEach(btn => btn.onclick = () => {
    $$('.fulfillment-tabs button').forEach(
      x => x.classList.remove('active')
    );

    btn.classList.add('active');
    const f = btn.dataset.fulfillment;

    $('#checkoutForm [name=fulfillment]').value = f;
    $('#pickupBlock').classList.toggle('active', f === 'pickup');
    $('#deliveryBlock').classList.toggle('active', f === 'delivery');
    renderPaymentChoices(f);
  });

  $('#prescriptionForm').onsubmit = async e => {
    e.preventDefault();
    if (!requireCustomer()) return;

    const form = new FormData(e.target);

    try {
      await API.uploadPrescription(form);
      closeModal('prescriptionModal');
      e.target.reset();
      toast('Prescription sent to the pharmacist for review.');
    } catch (err) {
      toast(err.message, 'error');
    }
  };

  $('#consultForm').onsubmit = async e => {
    e.preventDefault();
    if (!requireCustomer()) return;

    const data = Object.fromEntries(new FormData(e.target));
    if (!data.product_id) delete data.product_id;

    try {
      await API.createConsultation(data);
      closeModal('consultModal');
      e.target.reset();
      toast('Your inquiry was sent to the pharmacist.');
    } catch (err) {
      toast(err.message, 'error');
    }
  };

  $('#addressForm').onsubmit = async e => {
    e.preventDefault();

    const fd = new FormData(e.target);
    const data = Object.fromEntries(fd);
    data.is_default = fd.get('is_default') === 'on';

    try {
      await API.addAddress(data);
      state.addresses = await API.addresses();
      renderAddressChoices();

      closeModal('addressModal');
      e.target.reset();

      resetAddressSelect($('#addressProvince'), 'Select province');
      resetAddressSelect($('#addressCity'), 'Select city');
      resetAddressSelect($('#addressBarangay'), 'Select barangay');

      toast('Delivery address saved.');

      if ($('#accountModal').classList.contains('open')) {
        renderAccountTab('addresses');
      }
    } catch (err) {
      toast(err.message, 'error');
    }
  };

  $('#checkoutForm').onsubmit = async e => {
    e.preventDefault();
    if (!requireCustomer()) return;

    const fd = new FormData(e.target);
    const fulfillment = fd.get('fulfillment');

    const payload = {
      fulfillment,
      payment_method: fd.get('payment_method'),
      notes: fd.get('notes'),
      items: state.cart
    };

    if (fulfillment === 'pickup') {
      payload.branch_id = fd.get('branch_id');
    } else {
      payload.address_id = fd.get('address_id');
    }

    try {
      const result = await API.checkout(payload);

      state.cart = [];
      saveCart();
      closeModal('checkoutModal');

      $('#cartDrawer').classList.remove('open');
      $('#drawerBackdrop').classList.remove('show');

      toast(`Order ${result.order.order_number} placed.`);

      await showTracking(result.order.id);
      await loadCatalog();
    } catch (err) {
      toast(err.message, 'error');
    }
  };
}

window.addEventListener('DOMContentLoaded', async () => {
  setupEvents();
  await Promise.all([restoreSession(), loadCatalog()]);
  renderSession();
  icons();
});
