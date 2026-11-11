(() => {
  const base = String(window.APP_CONFIG?.apiBaseUrl || '').replace(/\/$/, '');
  const endpoint = path => `${base}${path}`;
  // Supabase Auth JWT and rotated refresh token from our FastAPI Auth gateway.
  // The service key is NEVER present here. For public production deployment,
  // move the refresh token into an HttpOnly cookie with CSRF protection.
  const sessionKey = '360pharmacy_supabase_session_v5';
  let renewal = null;
  function session() {
    try { return JSON.parse(localStorage.getItem(sessionKey) || 'null'); }
    catch (_) { return null; }
  }
  function token() { return session()?.access_token || ''; }
  function setSession(data) {
    if (!data?.access_token) throw new Error('Supabase did not return an access token.');
    const previous = session() || {};
    const next = {
      access_token: data.access_token,
      refresh_token: data.refresh_token || previous.refresh_token || '',
      expires_at: Math.floor(Date.now() / 1000) + Math.max(30, Number(data.expires_in || 3600))
    };
    localStorage.setItem(sessionKey, JSON.stringify(next));
    return next;
  }
  function clearSession() {
    localStorage.removeItem(sessionKey);
    localStorage.removeItem('360pharmacy_access_token');
    localStorage.removeItem('360pharmacy_profile');
  }
  async function renew() {
    if (renewal) return renewal;
    const current = session();
    if (!current?.refresh_token) { clearSession(); return false; }
    renewal = (async () => {
      try {
        const response = await fetch(endpoint('/api/auth/refresh'), {
          method:'POST', headers:{'Content-Type':'application/json', Accept:'application/json'},
          body:JSON.stringify({refresh_token:current.refresh_token})
        });
        if (!response.ok) throw new Error('Session expired');
        setSession(await response.json());
        return true;
      } catch (_) { clearSession(); return false; }
      finally { renewal = null; }
    })();
    return renewal;
  }
  async function ready() {
    const s = session();
    if (!s?.access_token) return false;
    return s.expires_at > Math.floor(Date.now()/1000)+45 ? true : await renew();
  }
  async function request(path, options = {}, retry = true) {
    const headers = {Accept:'application/json', ...(options.headers || {})};
    const existing = session();
    if (existing?.refresh_token && existing.expires_at <= Math.floor(Date.now()/1000)+30) {
      await renew();
    }
    if (token()) headers.Authorization = `Bearer ${token()}`;
    let body = options.body;
    if (body && !(body instanceof FormData) && typeof body !== 'string') {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    const response = await fetch(endpoint(path), {...options, body, headers});
    if (response.status === 401 && retry && session()?.refresh_token && !path.startsWith('/api/auth/')) {
      if (await renew()) return request(path, options, false);
    }
    let output = null;
    try { output = (response.headers.get('content-type')||'').includes('application/json') ? await response.json() : await response.text(); }
    catch (_) { /* empty response */ }
    if (!response.ok) {
      const e = new Error(output?.detail || output?.message || (typeof output==='string' && output) || `Request failed (${response.status})`);
      e.status = response.status;
      throw e;
    }
    return output;
  }

  async function downloadPDF(path, filename) {
    if (session()?.refresh_token && !await ready()) throw new Error('Please sign in again.');
    const attempt = () => fetch(endpoint(path), {headers: {Authorization: `Bearer ${token()}`, Accept: 'application/pdf'}});
    let response = await attempt();
    if (response.status === 401 && await renew()) response = await attempt();
    if (!response.ok) {
      let message = `Download failed (${response.status})`;
      try { const body = await response.json(); message = body.detail || message; } catch (_) {}
      throw new Error(message);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  window.API = {
    token,
    setSession,
    ready,
    clearSession,
    async logout() { try { if (token()) await request('/api/auth/logout', {method:'POST'}); } catch (_) {} clearSession(); },
    health: () => request('/api/health'),
    catalog: () => request('/api/catalog'),
    register: data => request('/api/auth/register', { method: 'POST', body: data }),
    verifyEmail: data => request('/api/auth/verify-email', { method: 'POST', body: data }),
    resendVerification: data => request('/api/auth/resend-verification', { method: 'POST', body: data }),
    forgotPassword: data => request('/api/auth/forgot-password', { method: 'POST', body: data }),
    updatePassword: data => request('/api/auth/update-password', {method:'POST',body:data}),
    login: data => request('/api/auth/login', { method: 'POST', body: data }),
    me: () => request('/api/auth/me'),
    setupStatus: () => request('/api/setup/status'),
    bootstrapAdmin: data => request('/api/setup/head-admin', { method: 'POST', body: data }),

    favorites: () => request('/api/me/favorites'),
    addFavorite: id => request(`/api/me/favorites/${id}`, { method: 'POST' }),
    removeFavorite: id => request(`/api/me/favorites/${id}`, { method: 'DELETE' }),
    addresses: () => request('/api/me/addresses'),
    addressRegions: () => request('/api/locations/regions'),
    addressProvinces: code => request(`/api/locations/regions/${encodeURIComponent(code)}/provinces`),
    addressRegionCities: code => request(`/api/locations/regions/${encodeURIComponent(code)}/cities-municipalities`),
    addressCities: code => request(`/api/locations/provinces/${encodeURIComponent(code)}/cities-municipalities`),
    addressBarangays: code => request(`/api/locations/cities-municipalities/${encodeURIComponent(code)}/barangays`),
    addAddress: data => request('/api/me/addresses', { method: 'POST', body: data }),
    updateAddress: (id, data) => request(`/api/me/addresses/${id}`, { method: 'PATCH', body: data }),
    deleteAddress: id => request(`/api/me/addresses/${id}`, { method: 'DELETE' }),
    uploadPrescription: formData => request('/api/me/prescriptions', { method: 'POST', body: formData }),
    prescriptions: () => request('/api/me/prescriptions'),
    consultations: () => request('/api/me/consultations'),
    createConsultation: data => request('/api/me/consultations', { method: 'POST', body: data }),
    customerReply: (id, data) => request(`/api/me/consultations/${id}/messages`, { method: 'POST', body: data }),
    checkout: data => request('/api/checkout', { method: 'POST', body: data }),
    myOrders: () => request('/api/me/orders'),
    tracking: id => request(`/api/me/orders/${id}/tracking`),
    confirmOrderReceipt: id => request(`/api/me/orders/${id}/confirm-receipt`, { method: 'POST' }),

    portalBootstrap: () => request('/api/portal/bootstrap'),
    portalReports: () => request('/api/portal/reports'),
    submitReport: data => request('/api/portal/reports', { method: 'POST', body: data }),
    reviewReport: id => request(`/api/admin/reports/${id}`, { method: 'PATCH' }),
    portalBadges: () => request('/api/portal/badges'),
    notifications: () => request('/api/portal/notifications'),
    acknowledgeNotification: id => request(`/api/portal/notifications/${id}`, { method: 'PATCH' }),
    attendance: () => request('/api/portal/attendance'),
    clockIn: () => request('/api/portal/attendance/clock-in', { method: 'POST' }),
    clockOut: () => request('/api/portal/attendance/clock-out', { method: 'POST' }),
    verifyAttendance: (id, data) => request(`/api/admin/attendance/${id}`, { method: 'PATCH', body: data }),

    pharmacistPrescriptions: () => request('/api/pharmacist/prescriptions'),
    prescriptionFile: id => request(`/api/pharmacist/prescriptions/${id}/file`),
    reviewPrescription: (id, data) => request(`/api/pharmacist/prescriptions/${id}`, { method: 'PATCH', body: data }),
    pharmacistConsultations: () => request('/api/pharmacist/consultations'),
    pharmacistReply: (id, data) => request(`/api/pharmacist/consultations/${id}/messages`, { method: 'POST', body: data }),
    pharmacistProduct: (id, data) => request(`/api/pharmacist/products/${id}`, { method: 'PATCH', body: data }),

    inventory: () => request('/api/inventory'),
    inventoryPDF: () => downloadPDF('/api/inventory/report.pdf', 'pharmacy360-inventory.pdf'),
    stockDeliveries: () => request('/api/stock-deliveries'),
    createStockDelivery: data => request('/api/admin/stock-deliveries', { method: 'POST', body: data }),
    updateStockDelivery: (id, data) => request(`/api/admin/stock-deliveries/${id}`, { method: 'PATCH', body: data }),
    receiveStockDelivery: (id, data) => request(`/api/stock-deliveries/${id}/receive`, { method: 'POST', body: data }),
    receiveStock: data => request('/api/inventory/receive', { method: 'POST', body: data }),
    merchProduct: (id, data) => request(`/api/inventory/products/${id}`, { method: 'PATCH', body: data }),
    uploadProductImage: formData => request('/api/portal/product-image', { method: 'POST', body: formData }),

    adminDashboard: (period, date) => request(`/api/admin/dashboard?period=${encodeURIComponent(period)}&date=${encodeURIComponent(date || '')}`),
    financialPDF: (period, date) => downloadPDF(`/api/admin/financial-report.pdf?period=${encodeURIComponent(period)}&date=${encodeURIComponent(date || '')}`, `pharmacy360-financial-${period}.pdf`),
    staff: () => request('/api/admin/staff'),
    createStaff: data => request('/api/admin/staff', { method: 'POST', body: data }),
    updateStaff: (id, data) => request(`/api/admin/staff/${id}`, { method: 'PATCH', body: data }),
    sendStaffPasswordLink: id => request(`/api/admin/staff/${id}/password-link`, {method:'POST'}),
        promotions: () => request('/api/admin/promotions'),
    createPromotion: data => request('/api/admin/promotions', { method: 'POST', body: data }),
    updatePromotion: (id, data) => request(`/api/admin/promotions/${id}`, { method: 'PATCH', body: data }),
    deletePromotion: id => request(`/api/admin/promotions/${id}`, { method: 'DELETE' }),
    getMaster: table => request(`/api/admin/master/${table}`),
    createMaster: (table, data) => request(`/api/admin/master/${table}`, { method: 'POST', body: data }),
    updateMaster: (table, id, data) => request(`/api/admin/master/${table}/${id}`, { method: 'PATCH', body: data }),
    createProduct: data => request('/api/admin/products', { method: 'POST', body: data }),
    updateProduct: (id, data) => request(`/api/admin/products/${id}`, { method: 'PATCH', body: data }),
    addExpense: data => request('/api/admin/expenses', { method: 'POST', body: data }),
    addPayroll: data => request('/api/admin/payroll', { method: 'POST', body: data }),
    adminOrders: () => request('/api/admin/orders'),
    updateOrderStatus: (id, data) => request(`/api/admin/orders/${id}/status`, { method: 'PATCH', body: data }),
    updatePayment: (id, data) => request(`/api/admin/orders/${id}/payment`, { method: 'PATCH', body: data }),
    activity: () => request('/api/admin/activity'),
    integrations: () => request('/api/admin/integrations'),
    deliveryPackages: () => request('/api/delivery/packages'),
    deliveryReceipt: id => request(`/api/delivery/packages/${encodeURIComponent(id)}/receipt`),
    claimPackage: id => request(`/api/delivery/packages/${id}/claim`, { method: 'POST' }),
    deliveryStatus: (id, data) => request(`/api/delivery/packages/${id}/status`, { method: 'PATCH', body: data }),
    riderLocation: (id, data) => request(`/api/delivery/packages/${id}/location`, { method: 'POST', body: data }),
    deliveryPaymentSent: id => request(`/api/delivery/packages/${id}/payment-sent`, { method: 'POST' })
  };
})();
