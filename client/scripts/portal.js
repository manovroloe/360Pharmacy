const portalState = {
  user: null,
  bootstrap: null,
  staff: [],
  section: null
};

// A completed request from an older screen must never overwrite the current one.
let navigationTicket = 0;
const isCurrentNavigation = ticket => ticket === undefined || ticket === navigationTicket;

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const peso = n => new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP' }).format(Number(n || 0));
const escapeHTML = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const fmtDate = v => v ? new Date(v).toLocaleString('en-PH',{dateStyle:'medium',timeStyle:'short'}) : '—';
const titleize = value => String(value || '').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
const today = () => new Date().toISOString().slice(0,10);
function icons(){ window.lucide?.createIcons(); }
function toast(message,type='success'){const e=document.createElement('div');e.className=`toast ${type}`;e.innerHTML=`<i data-lucide="${type==='error'?'circle-alert':'circle-check'}"></i><span>${escapeHTML(message)}</span>`;$('#toastArea').appendChild(e);icons();setTimeout(()=>e.remove(),3800);}
function openModal(html){$('#portalModalBody').innerHTML=html;$('#portalModal').classList.add('open');document.body.classList.add('modal-open');icons();}
function closeModal(){ $('#portalModal').classList.remove('open'); document.body.classList.remove('modal-open'); }
function optionRows(rows,label='name'){return rows.map(r=>`<option value="${r.id}">${escapeHTML(r[label]||r.name||r.id)}</option>`).join('');}
function staffRole(){return portalState.user?.profile?.role;}
function setLoading(){ $('#portalContent').innerHTML='<div class="loading-state portal-loading"><i data-lucide="loader-circle"></i>Loading pharmacy records…</div>'; icons(); }
function errorPanel(err){ $('#portalContent').innerHTML=`<div class="error-state panel-error"><i data-lucide="triangle-alert"></i><h3>Could not load this section</h3><p>${escapeHTML(err.message)}</p></div>`; icons(); }

const navByRole = {
  admin: [
    ['overview','layout-dashboard','Dashboard'],['staff','users-round','Staff Accounts'],['reports','clipboard-check','Staff Reports'],['attendance','clock-3','Attendance'],
    ['orders','shopping-bag','Orders & Shipping'],['finance','chart-no-axes-combined','Finance'],['promotions','badge-percent','Deals & Promotions'],
    ['products','pill','Products'],['inventory','boxes','Inventory'],['stockdeliveries','truck','Stock Deliveries'],['master','database','Master Data'],['activity','history','Activity']
  ],
  pharmacist: [['prescriptions','file-check-2','Prescription Queue'],['support','messages-square','Customer Support'],['medicine','pill-bottle','Medicine Guidance'],['attendance','clock-3','Attendance'],['reports','clipboard-pen-line','Report']],
  merchandiser: [['incoming','truck','Incoming Stocks'],['inventory','boxes','Inventory'],['merchproducts','image-up','Product Assets'],['attendance','clock-3','Attendance'],['reports','clipboard-pen-line','Report']],
  delivery: [['packages','package-check','Packages']]
};

async function sessionStart(){
  if (!await API.ready()) { location.replace('/login?next=/workspace'); return; }
  try {
    portalState.user = await API.me();
    if (portalState.user.profile.role === 'customer') { location.replace('/'); return; }
    // Bootstrap lists load only on screens that need them.
    showShell();
  } catch (err) {
    if ([401,403].includes(err.status)) {
      API.clearSession(); location.replace('/login?next=/workspace'); return;
    }
    $('#workspaceLoading').innerHTML = `<div class="gate-card"><h2>Workspace unavailable</h2><p>${escapeHTML(err.message)}</p><a class="primary-btn" href="/">Back to storefront</a></div>`;
  }
}

function showShell(){
  const notifyButton=$('#openNotifications');
  if(notifyButton) notifyButton.onclick=showNotifications;
  $('#workspaceLoading').classList.add('hidden'); $('#portalShell').classList.remove('hidden');
  const p=portalState.user.profile; $('#staffName').textContent=p.full_name;$('#staffEmail').textContent=p.role==='admin' ? p.email : (p.staff_id || 'Staff');$('#staffInitial').textContent=(p.full_name||'S').slice(0,1).toUpperCase();$('#roleLabel').textContent=titleize(p.role);
  const nav=navByRole[p.role]||[]; $('#portalNav').innerHTML=nav.map(([id,icon,label],i)=>`<button data-section="${id}" class="${i===0?'active':''}"><i data-lucide="${icon}"></i><span>${label}</span><b class="nav-badge hidden" data-badge="${id}">0</b></button>`).join('');
  $$('[data-section]').forEach(b=>b.onclick=()=>navigate(b.dataset.section));
  // An administrator always opens the Admin Dashboard after signing in.
  navigate(p.role === 'admin' ? 'overview' : nav[0]?.[0]); icons();
}
async function navigate(section){
  const ticket = ++navigationTicket;
  portalState.section=section; $$('[data-section]').forEach(b=>b.classList.toggle('active',b.dataset.section===section));
  const item=(navByRole[staffRole()]||[]).find(x=>x[0]===section); $('#pageTitle').textContent=item?.[2]||'Portal'; $('#pageKicker').textContent=titleize(staffRole()); setLoading();
  try{
    const handlers={overview:renderOverview,staff:renderStaff,reports:renderReports,orders:renderOrders,shipping:renderShipping,finance:renderFinance,promotions:renderPromotions,products:renderAdminProducts,inventory:renderInventory,stockdeliveries:renderStockDeliveries,incoming:renderIncomingStock,master:renderMaster,activity:renderActivity,attendance:renderAttendance,prescriptions:renderPrescriptions,support:renderSupport,medicine:renderPharmacistMedicine,receive:renderReceiveStock,merchproducts:renderMerchProducts,packages:renderDeliveryPackages};
    await handlers[section]?.(ticket);
    if (isCurrentNavigation(ticket)) refreshBadges();
  }catch(err){
    // A late error from the previous page must not replace the new page.
    if (isCurrentNavigation(ticket)) errorPanel(err);
  }
}


async function refreshNotifications(){
  const button=$('#openNotifications');
  if(!button || !portalState.user) return;
  try {
    const rows=await API.notifications();
    portalState.notifications=rows;
    const count=$('#notificationCount');
    count.textContent=rows.length>99?'99+':String(rows.length);
    count.classList.toggle('hidden',rows.length===0);
  } catch(_){ /* Notification errors must not block the portal. */ }
}
async function showNotifications(){
  let rows=[];
  try{rows=await API.notifications();}catch(err){toast(err.message,'error');return;}
  openModal(`<div class="panel-head"><div><span class="section-kicker">STAFF NOTIFICATIONS</span><h2>Recent assignments</h2><p>Stock deliveries assigned to you and other action reminders.</p></div></div>
    <div class="task-grid">${rows.length?rows.map(n=>`<article class="task-card"><h3>${escapeHTML(n.title)}</h3><p>${escapeHTML(n.details||'')}</p><small>${fmtDate(n.created_at)}</small><button class="outline-btn small" data-notification-done="${n.id}">Mark as read</button></article>`).join(''):'<div class="empty-inline">No unread notifications.</div>'}</div>`);
  $$('[data-notification-done]').forEach(button=>button.onclick=async()=>{
    try{await API.acknowledgeNotification(button.dataset.notificationDone);toast('Notification marked as read.');await refreshNotifications();showNotifications();}
    catch(err){toast(err.message,'error');}
  });
  icons();
}

async function refreshBootstrap(){ portalState.bootstrap=await API.portalBootstrap(); }
let lastBadgeRequest = 0;
async function refreshBadges(force=false){
  if (!force && Date.now()-lastBadgeRequest<12000) return;
  lastBadgeRequest=Date.now();
  try{
    const counts=await API.portalBadges();
    $$('[data-badge]').forEach(b=>{const n=Number(counts[b.dataset.badge]||0);b.textContent=n>99?'99+':String(n);b.classList.toggle('hidden',n<=0);});
    refreshNotifications();
  }catch(_){ }
}

async function renderOverview(ticket){
  if (!isCurrentNavigation(ticket)) return;
  const content=$('#portalContent');
  content.innerHTML=`<div class="filter-bar"><div><strong>Financial period</strong><span>Choose a day, month, or year using the reference date.</span></div><label>View<select id="periodSelect"><option value="day">Day</option><option value="month">Month</option><option value="year">Year</option></select></label><label>Reference date<input type="date" id="periodDate" value="${today()}"></label><button class="primary-btn small" id="applyPeriod"><i data-lucide="filter"></i>Apply</button><button class="outline-btn small" id="dashboardDownloadPDF" type="button"><i data-lucide="download"></i>Download PDF</button></div><div id="dashboardData"></div>`;
  $('#dashboardDownloadPDF').onclick=async()=>{try{await API.financialPDF($('#periodSelect').value,$('#periodDate').value);}catch(err){toast(err.message,'error');}};
  $('#applyPeriod').onclick=()=>{
    const period=$('#periodSelect').value, date=$('#periodDate').value;
    loadDashboard(period,date,ticket).catch(err=>{
      if (isCurrentNavigation(ticket)) errorPanel(err);
    });
  };
  await loadDashboard('day',today(),ticket);
  if (isCurrentNavigation(ticket)) icons();
}
async function loadDashboard(period,date,ticket){
  const d=await API.adminDashboard(period,date);
  if (!isCurrentNavigation(ticket)) return;
  const box=$('#dashboardData');
  if (!box) return; // The user has navigated away from the dashboard.
  box.innerHTML=`
  <div class="metric-grid six">
    <article><span>Sales Income</span><strong>${peso(d.income)}</strong><small>${d.salesCount} paid sale(s)</small></article>
    <article><span>Gross Profit</span><strong>${peso(d.grossProfit)}</strong><small>Sales − cost of goods sold</small></article>
    <article><span>Cash Outflow</span><strong>${peso(d.cashOutflow)}</strong><small>Stock + expenses + wages</small></article>
    <article><span>Operating Result</span><strong>${peso(d.operatingResult)}</strong><small>Gross profit − expenses − wages</small></article>
    <article><span>Low Stock</span><strong>${d.lowStockCount}</strong><small>At or below reorder level</small></article>
    <article><span>Pharmacy Queue</span><strong>${d.pendingPrescriptionCount+d.openConsultationCount}</strong><small>${d.pendingPrescriptionCount} Rx · ${d.openConsultationCount} support</small></article>
  </div>
  <div class="dashboard-grid">
    <section class="panel"><div class="panel-head"><div><span class="section-kicker">BREAKDOWN</span><h2>Business flow</h2></div></div><div class="finance-breakdown"><div><span>Sales revenue</span><strong>${peso(d.income)}</strong></div><div><span>Cost of goods sold</span><strong>${peso(d.cogs)}</strong></div><div><span>Stock purchases / cash out</span><strong>${peso(d.stockPurchases)}</strong></div><div><span>Operating expenses</span><strong>${peso(d.operatingExpenses)}</strong></div><div><span>Employee wages</span><strong>${peso(d.wages)}</strong></div></div></section>
    <section class="panel"><div class="panel-head"><div><span class="section-kicker">RECENT</span><h2>Staff activity</h2></div></div><div class="activity-list">${d.activity.length?d.activity.slice(0,8).map(a=>`<div><i data-lucide="history"></i><span><strong>${escapeHTML(titleize(a.action))}</strong><small>${escapeHTML(titleize(a.actor_role))} · ${fmtDate(a.created_at)}</small></span></div>`).join(''):'<div class="empty-inline">No activity yet.</div>'}</div></section>
  </div>
  <section class="panel"><div class="panel-head"><div><span class="section-kicker">ORDERS</span><h2>Orders in this period</h2></div></div>${tableOrders(d.orders)}</section>`; icons();
}
function tableOrders(rows){return rows.length?`<div class="table-wrap"><table><thead><tr><th>Order</th><th>Date</th><th>Fulfillment</th><th>Status</th><th>Payment</th><th>Total</th></tr></thead><tbody>${rows.map(o=>`<tr><td><strong>${escapeHTML(o.order_number)}</strong></td><td>${fmtDate(o.created_at)}</td><td>${escapeHTML(titleize(o.fulfillment))}</td><td><span class="status-tag">${escapeHTML(titleize(o.status))}</span></td><td>${escapeHTML(titleize(o.payment_status))}</td><td>${peso(o.total_amount)}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty-inline">No orders in this period.</div>';}

async function renderStaff(ticket){
  const staff = await API.staff();
  if (!isCurrentNavigation(ticket)) return;
  portalState.staff=staff;
  $('#portalContent').innerHTML=`<div class="split-layout"><section class="panel">
    <div class="panel-head"><div><span class="section-kicker">ADMIN ONLY</span><h2>Create pharmacy staff account</h2><p>Assign a position and initial password. Staff sign in using the same page as customers; no invitation email is sent.</p></div></div>
    <form class="form-stack" id="staffForm">
      <label>Position<select name="role" required><option value="pharmacist">Pharmacist</option><option value="merchandiser">Merchandiser</option><option value="delivery">Delivery Staff</option></select></label>
      <label>Staff ID<input name="staff_id" required minlength="3" maxlength="32" placeholder="MERCH-001"></label>
      <label>Staff full name<input name="full_name" required maxlength="160" autocomplete="name" placeholder="Staff name"></label>
      <label>Staff email address<input type="email" name="email" required autocomplete="email" placeholder="person@example.com"></label>
      <label>Phone (optional)<input name="phone" type="tel"></label>
      <div class="form-grid two"><label>Initial password<input type="password" name="password" minlength="8" maxlength="128" autocomplete="new-password" required placeholder="At least 8 characters"></label><label>Confirm password<input type="password" name="confirm_password" minlength="8" maxlength="128" autocomplete="new-password" required placeholder="Repeat initial password"></label></div>
      <div class="notice-strip"><i data-lucide="shield-check"></i><div><strong>Admin-created staff account</strong>Check the staff email address, then share the initial password privately. Supabase confirms this Admin-created email without sending an invite; staff can change their password with Forgot Password. Staff cannot choose their own position.</div></div>
      <button class="primary-btn" type="submit"><i data-lucide="user-plus"></i>Create staff account</button>
    </form></section>
    <section class="panel"><div class="panel-head"><div><span class="section-kicker">PEOPLE & PERMISSIONS</span><h2>Staff accounts</h2></div></div>
      <div class="staff-list">${portalState.staff.length?portalState.staff.map(person=>`<article class="staff-row">
        <div class="staff-avatar">${escapeHTML((person.full_name||'S')[0])}</div>
        <div><strong>${escapeHTML(person.full_name)}</strong><span>${escapeHTML(person.email||'No email')}</span>
          <small>${escapeHTML(person.staff_id||'—')} · ${escapeHTML(titleize(person.role))}</small>
          <span class="status-tag ${person.is_active?'completed':'cancelled'}">${person.is_active?'Active':'Disabled'}</span>
        </div>
        <div class="stack-actions">
          <select aria-label="Assigned position" data-staff-role="${person.id}">
            ${['pharmacist','merchandiser','delivery'].map(role=>`<option value="${role}" ${role===person.role?'selected':''}>${titleize(role)}</option>`).join('')}
          </select>
          <button class="outline-btn small" data-staff-save-role="${person.id}">Save role</button>
          <button class="outline-btn small" data-staff-recovery="${person.id}">Send password link</button>
          <button class="${person.is_active?'danger-btn':'outline-btn'} small" data-staff-toggle="${person.id}" data-active="${person.is_active}">${person.is_active?'Disable':'Enable'}</button>
        </div>
      </article>`).join(''):'<div class="empty-inline">No staff accounts yet.</div>'}</div>
    </section></div>`;
  $('#staffForm').onsubmit=async e=>{
    e.preventDefault();
    const form=e.target;
    const data=Object.fromEntries(new FormData(form));
    if(data.password!==data.confirm_password){toast('Initial passwords do not match.','error');return;}
    delete data.confirm_password;
    // Clear credentials from the form immediately after reading them.
    form.elements.password.value='';
    form.elements.confirm_password.value='';
    const submit=form.querySelector('[type="submit"]');
    if(submit)submit.disabled=true;
    try { await API.createStaff(data); toast('Staff account created. Share the initial password privately.'); if (isCurrentNavigation(ticket) && portalState.section==='staff') await renderStaff(ticket); }
    catch (err) { toast(err.message,'error'); }
    finally { if(submit)submit.disabled=false; }
  };
  $$('[data-staff-save-role]').forEach(btn=>btn.onclick=async()=>{
    const role=$(`[data-staff-role="${btn.dataset.staffSaveRole}"]`).value;
    if(!confirm(`Assign this staff member as ${titleize(role)}?`)) return;
    try { await API.updateStaff(btn.dataset.staffSaveRole,{role});toast('Position updated.');if (isCurrentNavigation(ticket) && portalState.section==='staff') await renderStaff(ticket); }
    catch(err){toast(err.message,'error');}
  });
  $$('[data-staff-recovery]').forEach(btn=>btn.onclick=async()=>{
    if(!confirm('Send this staff member a password recovery email?'))return;
    try {const r=await API.sendStaffPasswordLink(btn.dataset.staffRecovery);toast(r.message);}
    catch(err){toast(err.message,'error');}
  });
  $$('[data-staff-toggle]').forEach(btn=>btn.onclick=async()=>{
    try {await API.updateStaff(btn.dataset.staffToggle,{is_active:btn.dataset.active!=='true'});toast('Staff access updated.');if (isCurrentNavigation(ticket) && portalState.section==='staff') await renderStaff(ticket);}
    catch(err){toast(err.message,'error');}
  });icons();
}

async function renderReports(){
  const rows=await API.portalReports(); const admin=staffRole()==='admin';
  if(admin){
    $('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">STAFF REPORT</span><h2>Completed work reports</h2><p>Pharmacists and Merchandisers submit what they accomplished during their work hours. New submissions remain marked Submitted until reviewed.</p></div></div><div class="task-grid">${rows.length?rows.map(r=>`<article class="task-card"><span class="status-tag ${r.status}">${escapeHTML(titleize(r.status))}</span><h3>${escapeHTML(r.title)}</h3><p>${escapeHTML(r.details)}</p><small>${escapeHTML(r.staff?.full_name||'Staff')} · ${escapeHTML(titleize(r.staff?.role||''))}</small><small>Work date: ${escapeHTML(r.report_date||'—')} · Submitted ${fmtDate(r.created_at)}</small>${r.status==='submitted'?`<button class="primary-btn small" data-review-report="${r.id}">Mark Reviewed</button>`:''}</article>`).join(''):'<div class="empty-inline">No staff reports submitted yet.</div>'}</div></section>`;
    $$('[data-review-report]').forEach(b=>b.onclick=async()=>{try{await API.reviewReport(b.dataset.reviewReport);toast('Staff report marked reviewed.');renderReports();}catch(err){toast(err.message,'error');}});
  }else{
    $('#portalContent').innerHTML=`<div class="split-layout"><section class="panel"><div class="panel-head"><div><span class="section-kicker">REPORT</span><h2>Submit accomplished work</h2><p>Record what you completed during your work hours. This replaces the old My Task screen.</p></div></div><form id="reportForm" class="form-stack"><label>Work date<input type="date" name="report_date" value="${today()}" required></label><label>Report title<input name="title" required placeholder="What did you accomplish?"></label><label>Completed work<textarea name="details" rows="7" required placeholder="Describe the work you completed during your shift."></textarea></label><button class="primary-btn">Submit Report</button></form></section><section class="panel"><div class="panel-head"><div><span class="section-kicker">MY REPORTS</span><h2>Submitted work</h2></div></div><div class="task-grid">${rows.length?rows.map(r=>`<article class="task-card"><span class="status-tag ${r.status}">${escapeHTML(titleize(r.status))}</span><h3>${escapeHTML(r.title)}</h3><p>${escapeHTML(r.details)}</p><small>${escapeHTML(r.report_date||'—')} · ${fmtDate(r.created_at)}</small></article>`).join(''):'<div class="empty-inline">No reports submitted yet.</div>'}</div></section></div>`;
    $('#reportForm').onsubmit=async e=>{e.preventDefault();try{await API.submitReport(Object.fromEntries(new FormData(e.target)));toast('Work report submitted.');e.target.reset();renderReports();}catch(err){toast(err.message,'error');}};
  }
  icons();
}

function adminOrderAction(o){
  if(o.status==='cancelled'||o.status==='completed') return '';
  let next=''; let label='';
  if(['placed','confirmed'].includes(o.status)){next='preparing';label='Preparing Package';}
  else if(o.fulfillment==='pickup'&&o.status==='preparing'){next='ready_for_pickup';label='Ready for Pick Up';}
  else if(o.fulfillment==='delivery'&&o.status==='preparing'){next='handed_to_courier';label='Handed to Courier';}
  else if(o.fulfillment==='pickup'&&o.status==='picked_up'){next='completed';label='Mark Completed';}
  else if(o.fulfillment==='delivery'&&o.status==='order_received'){next='completed';label='Mark Completed';}
  if(!next) return '';
  const completing=next==='completed';
  const disabled=completing&&o.payment_status!=='paid';
  return `<button class="primary-btn small" data-order-next="${o.id}" data-next="${next}" ${disabled?'disabled title="Mark the order Paid first"':''}>${label}</button>`;
}
async function renderOrders(){
  const rows=await API.adminOrders();
  $('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">ORDERS & SHIPPING</span><h2>Orders and delivery monitoring</h2><p>Pickup and delivery orders are managed together. Completed is available only after the order is Paid. For cash-on-delivery orders, wait for the rider's Payment Sent confirmation before marking Paid.</p></div></div>${rows.length?`<div class="table-wrap"><table><thead><tr><th>Order</th><th>Type</th><th>Status</th><th>Rider Payment</th><th>Payment</th><th>Total</th><th>Actions</th></tr></thead><tbody>${rows.map(o=>{const d=o.delivery;const riderPayment=o.fulfillment==='delivery'?(o.payment_method!=='cash_on_delivery'?'<span class="status-tag">Not Required</span>':(d?.payment_sent_at?`<span class="status-tag completed">Payment Sent</span><small>${fmtDate(d.payment_sent_at)}</small>`:(o.payment_status==='paid'?'<span class="status-tag completed">Already Paid</span>':'<span class="status-tag pending">Waiting</span>'))):'—';const canMarkPaid=o.payment_status!=='paid'&&(o.fulfillment!=='delivery'||o.payment_method!=='cash_on_delivery'||!!d?.payment_sent_at);return `<tr><td><strong>${escapeHTML(o.order_number)}</strong><small>${fmtDate(o.created_at)}</small></td><td>${escapeHTML(titleize(o.fulfillment))}</td><td><span class="status-tag ${o.status}">${escapeHTML(titleize(o.status))}</span></td><td>${riderPayment}</td><td><span class="status-tag ${o.payment_status==='paid'?'completed':''}">${escapeHTML(titleize(o.payment_status))}</span></td><td>${peso(o.total_amount)}</td><td><div class="stack-actions">${adminOrderAction(o)}<button class="outline-btn small" data-mark-paid="${o.id}" ${o.payment_status==='paid'||!canMarkPaid?'disabled':''}>Mark Paid</button>${!['completed','cancelled'].includes(o.status)?`<button class="danger-btn small" data-cancel-order="${o.id}">Cancel</button>`:''}</div></td></tr>`}).join('')}</tbody></table></div>`:'<div class="empty-inline">No orders yet.</div>'}</section>`;
  $$('[data-order-next]').forEach(b=>b.onclick=async()=>{try{await API.updateOrderStatus(b.dataset.orderNext,{status:b.dataset.next});toast('Order flow updated.');renderOrders();}catch(err){toast(err.message,'error');}});
  $$('[data-cancel-order]').forEach(b=>b.onclick=async()=>{if(!confirm('Cancel this order?'))return;try{await API.updateOrderStatus(b.dataset.cancelOrder,{status:'cancelled'});toast('Order cancelled.');renderOrders();}catch(err){toast(err.message,'error');}});
  $$('[data-mark-paid]').forEach(b=>b.onclick=async()=>{try{await API.updatePayment(b.dataset.markPaid,{status:'paid'});toast('Payment marked paid.');renderOrders();}catch(err){toast(err.message,'error');}});icons();
}

async function renderShipping(){
  const rows=(await API.adminOrders()).filter(o=>o.fulfillment==='delivery');
  $('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">SHIPPING</span><h2>Delivery monitoring</h2><p>Delivery staff update Transit → Out for Delivery → Delivered. Customers then confirm Order Received before Admin marks the order Completed.</p></div></div>${rows.length?`<div class="table-wrap"><table><thead><tr><th>Order</th><th>Status</th><th>Payment</th><th>Total</th><th>Admin action</th></tr></thead><tbody>${rows.map(o=>`<tr><td><strong>${escapeHTML(o.order_number)}</strong><small>${fmtDate(o.created_at)}</small></td><td><span class="status-tag ${o.status}">${escapeHTML(titleize(o.status))}</span></td><td>${escapeHTML(titleize(o.payment_status))}</td><td>${peso(o.total_amount)}</td><td>${o.status==='order_received'?`<button class="primary-btn small" data-shipping-complete="${o.id}">Mark Completed</button>`:'Monitor delivery progress'}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty-inline">No delivery orders yet.</div>'}</section>`;
  $$('[data-shipping-complete]').forEach(b=>b.onclick=async()=>{try{await API.updateOrderStatus(b.dataset.shippingComplete,{status:'completed'});toast('Delivery order completed.');renderShipping();}catch(err){toast(err.message,'error');}});icons();
}

async function renderFinance(){
  if(!portalState.staff.length) try{portalState.staff=await API.staff();}catch(_){ }
  $('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><h2>Financial report</h2></div></div><div class="filter-bar"><label>Period<select id="financePeriod"><option value="day">Day</option><option value="month">Month</option><option value="year">Year</option></select></label><label>Date<input id="financeDate" type="date" value="${today()}"></label><button type="button" class="primary-btn small" id="financeDownloadPDF"><i data-lucide="download"></i>Download PDF</button></div></section><div class="split-layout"><section class="panel"><div class="panel-head"><div><span class="section-kicker">OUTCOME</span><h2>Record operating expense</h2></div></div><form id="expenseForm" class="form-stack"><label>Date<input type="date" name="expense_date" value="${today()}" required></label><label>Category<select name="category"><option>Utilities</option><option>Rent</option><option>Delivery / Transport</option><option>Supplies</option><option>Repairs</option><option>Marketing</option><option>Other</option></select></label><label>Description<input name="description" required></label><label>Amount<input type="number" name="amount" min="0" step="0.01" required></label><button class="primary-btn">Save expense</button></form></section><section class="panel"><div class="panel-head"><div><span class="section-kicker">WAGES</span><h2>Record employee wage</h2></div></div><form id="payrollForm" class="form-stack"><label>Employee<select name="employee_id" required><option value="">Select staff</option>${portalState.staff.filter(s=>s.is_active).map(s=>`<option value="${s.id}">${escapeHTML(s.full_name)} · ${escapeHTML(titleize(s.role))}</option>`).join('')}</select></label><div class="form-grid two"><label>Period start<input type="date" name="period_start" required></label><label>Period end<input type="date" name="period_end" required></label></div><div class="form-grid two"><label>Gross wage<input type="number" name="gross_wage" min="0" step="0.01" required></label><label>Deductions<input type="number" name="deductions" min="0" step="0.01" value="0"></label></div><label>Status<select name="status"><option value="pending">Pending</option><option value="paid">Paid</option></select></label><button class="primary-btn">Save payroll</button></form></section></div><section class="panel"><div class="panel-head"><div><span class="section-kicker">AUTOMATIC</span><h2>How the dashboard calculates the business</h2></div></div><div class="formula-grid"><div><strong>Sales Income</strong><span>Paid customer payments</span></div><div><strong>Gross Profit</strong><span>Sales Income − COGS</span></div><div><strong>Cash Outflow</strong><span>Stock purchases + expenses + wages</span></div><div><strong>Operating Result</strong><span>Gross Profit − expenses − wages</span></div></div></section>`;
  $('#financeDownloadPDF').onclick=async()=>{try{await API.financialPDF($('#financePeriod').value,$('#financeDate').value);}catch(err){toast(err.message,'error');}};
  $('#expenseForm').onsubmit=async e=>{e.preventDefault();try{await API.addExpense(Object.fromEntries(new FormData(e.target)));toast('Expense recorded.');e.target.reset();}catch(err){toast(err.message,'error');}};
  $('#payrollForm').onsubmit=async e=>{e.preventDefault();try{await API.addPayroll(Object.fromEntries(new FormData(e.target)));toast('Payroll record saved.');e.target.reset();}catch(err){toast(err.message,'error');}};icons();
}

async function renderPromotions(){
  await refreshBootstrap();
  const promos=await API.promotions(); const products=portalState.bootstrap.products;
  $('#portalContent').innerHTML=`<div class="split-layout promo-layout"><section class="panel"><div class="panel-head"><div><span class="section-kicker">CONTROL</span><h2>Create Hot Deal / Sale / Promo</h2></div></div><form id="promoForm" class="form-stack"><label>Type<select name="kind"><option value="hot_deal">Hot Deal</option><option value="sale">Sale</option><option value="promo">Promo Deal</option></select></label><label>Title<input name="title" required></label><label>Short message<input name="subtitle"></label><div class="form-grid two"><label>Discount<select name="discount_type"><option value="percentage">Percentage</option><option value="fixed">Fixed amount</option></select></label><label>Value<input type="number" name="discount_value" min="0" step="0.01" required></label></div><div class="form-grid two"><label>Starts<input type="datetime-local" name="starts_at"></label><label>Ends<input type="datetime-local" name="ends_at"></label></div><label>Banner image URL (optional)<input type="url" name="banner_image_url"></label><label>Products<select name="product_ids" multiple size="7">${optionRows(products)}</select><small>Hold Ctrl to select more than one product.</small></label><button class="primary-btn">Publish deal</button></form></section><section class="panel"><div class="panel-head"><div><span class="section-kicker">ACTIVE & SCHEDULED</span><h2>Promotion control</h2></div></div><div class="promo-admin-list">${promos.length?promos.map(p=>`<article class="promo-admin-card"><span class="status-tag">${escapeHTML(titleize(p.kind))}</span><h3>${escapeHTML(p.title)}</h3><p>${escapeHTML(p.subtitle||'')}</p><strong>${p.discount_type==='percentage'?`${p.discount_value}%`:peso(p.discount_value)} OFF</strong><small>${p.product_ids?.length||0} linked product(s)</small><div><button class="outline-btn small" data-promo-toggle="${p.id}" data-active="${p.is_active}">${p.is_active?'Pause':'Activate'}</button><button class="danger-btn small" data-promo-delete="${p.id}">Delete</button></div></article>`).join(''):'<div class="empty-inline">No promotions yet.</div>'}</div></section></div>`;
  $('#promoForm').onsubmit=async e=>{e.preventDefault();const fd=new FormData(e.target);const d=Object.fromEntries(fd);d.product_ids=[...e.target.elements.product_ids.selectedOptions].map(o=>o.value);d.is_active=true;if(!d.starts_at)delete d.starts_at;if(!d.ends_at)delete d.ends_at;try{await API.createPromotion(d);toast('Promotion published.');renderPromotions();}catch(err){toast(err.message,'error');}};
  $$('[data-promo-toggle]').forEach(b=>b.onclick=async()=>{try{await API.updatePromotion(b.dataset.promoToggle,{is_active:b.dataset.active!=='true'});renderPromotions();}catch(err){toast(err.message,'error');}});
  $$('[data-promo-delete]').forEach(b=>b.onclick=async()=>{if(!confirm('Delete this promotion?'))return;try{await API.deletePromotion(b.dataset.promoDelete);renderPromotions();}catch(err){toast(err.message,'error');}});icons();
}

function adminProductForm(){const b=portalState.bootstrap;return `<form id="productForm" class="form-stack"><div class="form-grid two"><label>Name<input name="name" required></label><label>SKU<input name="sku"></label></div><div class="form-grid two"><label>Generic name<input name="generic_name"></label><label>Brand<input name="brand"></label></div><div class="form-grid two"><label>Category<select name="category_id"><option value="">None</option>${optionRows(b.categories)}</select></label><label>Manufacturer<select name="manufacturer_id"><option value="">None</option>${optionRows(b.manufacturers)}</select></label></div><div class="form-grid three"><label>Dosage form<input name="dosage_form"></label><label>Strength<input name="strength"></label><label>Selling price<input type="number" name="selling_price" min="0" step="0.01" required></label></div><label>Short use / what it is for<input name="short_use" placeholder="Short customer-friendly description"></label><label>Description<textarea name="description" rows="3"></textarea></label><label>Image URL<input type="url" name="image_url" placeholder="Or upload after creating the product"></label><label class="check-row"><input type="checkbox" name="requires_prescription">Requires prescription</label><button class="primary-btn">Add product</button></form>`;}
async function renderAdminProducts(){
  await refreshBootstrap(); const p=portalState.bootstrap.products;
  $('#portalContent').innerHTML=`<div class="split-layout"><section class="panel"><div class="panel-head"><div><span class="section-kicker">CATALOG</span><h2>Add a product</h2></div></div>${adminProductForm()}</section><section class="panel"><div class="panel-head"><div><span class="section-kicker">PRODUCTS</span><h2>Current catalog</h2></div></div><div class="compact-product-list">${p.length?p.map(x=>`<article><div class="tiny-product-img">${x.image_url?`<img src="${escapeHTML(x.image_url)}" alt="">`:'<i data-lucide="pill"></i>'}</div><span><strong>${escapeHTML(x.name)}</strong><small>${escapeHTML(x.generic_name||'')} · ${peso(x.selling_price)}</small></span><button class="outline-btn small" data-product-image="${x.id}">Image</button></article>`).join(''):'<div class="empty-inline">No products yet.</div>'}</div></section></div>`;
  $('#productForm').onsubmit=async e=>{e.preventDefault();const fd=new FormData(e.target);const d=Object.fromEntries(fd);d.requires_prescription=fd.get('requires_prescription')==='on';if(!d.category_id)delete d.category_id;if(!d.manufacturer_id)delete d.manufacturer_id;try{await API.createProduct(d);toast('Product added.');await refreshBootstrap();renderAdminProducts();}catch(err){toast(err.message,'error');}};
  $$('[data-product-image]').forEach(b=>b.onclick=()=>imageUploadModal(b.dataset.productImage)); icons();
}

function imageUploadModal(productId){const p=portalState.bootstrap.products.find(x=>x.id===productId);openModal(`<div class="modal-heading"><span class="section-kicker">PRODUCT IMAGE</span><h2>${escapeHTML(p?.name||'Medicine')}</h2><p>Paste an image URL or upload JPG/PNG/WEBP to the local Python storage folder.</p></div><form id="imageUrlForm" class="form-stack"><label>Image URL<input type="url" name="image_url" placeholder="https://..."></label><button class="outline-btn">Save URL</button></form><div class="or-divider"><span>OR</span></div><form id="imageUploadForm" class="form-stack"><label class="file-drop">Upload image<input type="file" name="file" accept="image/jpeg,image/png,image/webp" required><span><i data-lucide="image-up"></i>Maximum 5 MB</span></label><button class="primary-btn">Upload locally</button></form>`);
  $('#imageUrlForm').onsubmit=async e=>{e.preventDefault();const url=new FormData(e.target).get('image_url');try{if(staffRole()==='pharmacist')await API.pharmacistProduct(productId,{image_url:url});else if(staffRole()==='merchandiser')await API.merchProduct(productId,{image_url:url});else await API.updateProduct(productId,{image_url:url});toast('Image URL saved.');closeModal();await refreshBootstrap();navigate(portalState.section);}catch(err){toast(err.message,'error');}};
  $('#imageUploadForm').onsubmit=async e=>{e.preventDefault();const fd=new FormData(e.target);fd.append('product_id',productId);try{await API.uploadProductImage(fd);toast('Image uploaded.');closeModal();await refreshBootstrap();navigate(portalState.section);}catch(err){toast(err.message,'error');}};icons();
}

async function renderInventory(){
  const data=await API.inventory(); const now=new Date();
  $('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">STOCK LEVELS</span><h2>Branch inventory</h2></div><button class="outline-btn small" id="downloadInventoryPDF" type="button"><i data-lucide="download"></i>Download PDF</button></div>${data.inventory.length?`<div class="table-wrap"><table><thead><tr><th>Product</th><th>Branch</th><th>On Hand</th><th>Reserved</th><th>Available</th><th>Reorder At</th></tr></thead><tbody>${data.inventory.map(i=>`<tr class="${Number(i.on_hand)-Number(i.reserved)<=Number(i.reorder_level)?'warning-row':''}"><td><strong>${escapeHTML(i.product?.name||i.product_id)}</strong></td><td>${escapeHTML(i.branch?.name||'')}</td><td>${i.on_hand}</td><td>${i.reserved}</td><td>${Number(i.on_hand)-Number(i.reserved)}</td><td>${i.reorder_level}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty-inline">No stock records yet. Receive the first delivery.</div>'}</section><section class="panel"><div class="panel-head"><div><span class="section-kicker">BATCH & EXPIRY</span><h2>Delivered stock arranged by expiration</h2></div></div>${data.batches.length?`<div class="table-wrap"><table><thead><tr><th>Expiry</th><th>Product</th><th>Manufacturer</th><th>Delivered</th><th>Batch</th><th>Remaining</th><th>Cost/Unit</th></tr></thead><tbody>${data.batches.map(b=>{const exp=b.expiration_date?new Date(`${b.expiration_date}T00:00:00`):null;const days=exp?Math.ceil((exp-now)/(86400000)):null;return `<tr class="${days!==null&&days<=90?'warning-row':''}"><td><strong>${escapeHTML(b.expiration_date||'No expiry')}</strong>${days!==null?`<small>${days<0?'Expired':`${days} days`}</small>`:''}</td><td>${escapeHTML(b.product?.name||'')}</td><td>${escapeHTML(b.manufacturer?.name||'—')}</td><td>${escapeHTML(b.delivery_date)}</td><td>${escapeHTML(b.batch_number||'—')}</td><td>${b.quantity_remaining} / ${b.quantity_received}</td><td>${peso(b.cost_per_unit)}</td></tr>`}).join('')}</tbody></table></div>`:'<div class="empty-inline">No delivery batches yet.</div>'}</div></section>`;
  $('#downloadInventoryPDF').onclick=async()=>{try{await API.inventoryPDF();}catch(err){toast(err.message,'error');}};
  icons();
}

async function renderMaster(){
  await refreshBootstrap(); const b=portalState.bootstrap;
  $('#portalContent').innerHTML=`<div class="master-grid">
  <section class="panel"><div class="panel-head"><div><span class="section-kicker">PICKUP / BRANCHES</span><h2>Branch addresses</h2></div></div><form class="form-stack" id="branchForm"><label>Name<input name="name" required></label><label>Address line<input name="address_line" required></label><div class="form-grid two"><label>Barangay<input name="barangay"></label><label>City<input name="city" required></label></div><div class="form-grid two"><label>Province<input name="province"></label><label>Postal code<input name="postal_code"></label></div><label>Pickup instructions<input name="pickup_instructions"></label><div class="form-grid two"><label class="check-row"><input type="checkbox" name="is_pickup_enabled" checked>Pickup enabled</label><label class="check-row"><input type="checkbox" name="is_delivery_enabled" checked>Delivery source</label></div><button class="primary-btn">Add branch</button></form><div class="master-list">${b.branches.map(x=>`<span><strong>${escapeHTML(x.name)}</strong><small>${escapeHTML([x.address_line,x.city].filter(Boolean).join(', '))}</small></span>`).join('')||'<div class="empty-inline">None yet.</div>'}</div></section>
  <section class="panel"><div class="panel-head"><div><span class="section-kicker">CATEGORIES</span><h2>Medicine categories</h2></div></div><form class="inline-form" id="categoryForm"><label>Name<input name="name" required></label><label>Slug<input name="slug" required placeholder="pain-fever"></label><button class="primary-btn">Add</button></form><div class="master-list">${b.categories.map(x=>`<span><strong>${escapeHTML(x.name)}</strong><small>${escapeHTML(x.slug)}</small></span>`).join('')||'<div class="empty-inline">None yet.</div>'}</div></section>
  <section class="panel"><div class="panel-head"><div><span class="section-kicker">MANUFACTURERS</span><h2>Manufacturers / partners</h2></div></div><form class="form-stack" id="manufacturerForm"><label>Name<input name="name" required></label><label>Logo URL<input name="logo_url" type="url"></label><label>Website URL<input name="website_url" type="url"></label><label class="check-row"><input type="checkbox" name="is_partner">Show as public partner manufacturer</label><button class="primary-btn">Add manufacturer</button></form><div class="master-list">${b.manufacturers.map(x=>`<span><strong>${escapeHTML(x.name)}</strong><small>${x.is_partner?'Public partner':'Internal manufacturer'}</small></span>`).join('')||'<div class="empty-inline">None yet.</div>'}</div></section>
  <section class="panel"><div class="panel-head"><div><span class="section-kicker">SUPPLIERS</span><h2>Stock suppliers</h2></div></div><form class="form-stack" id="supplierForm"><label>Name<input name="name" required></label><div class="form-grid two"><label>Contact<input name="contact_name"></label><label>Phone<input name="phone"></label></div><label>Email<input name="email" type="email"></label><button class="primary-btn">Add supplier</button></form><div class="master-list">${b.suppliers.map(x=>`<span><strong>${escapeHTML(x.name)}</strong><small>${escapeHTML(x.phone||x.email||'')}</small></span>`).join('')||'<div class="empty-inline">None yet.</div>'}</div></section></div>`;
  $('#branchForm').onsubmit=e=>submitMaster(e,'branches',['is_pickup_enabled','is_delivery_enabled']);$('#categoryForm').onsubmit=e=>submitMaster(e,'categories');$('#manufacturerForm').onsubmit=e=>submitMaster(e,'manufacturers',['is_partner']);$('#supplierForm').onsubmit=e=>submitMaster(e,'suppliers');icons();
}
async function submitMaster(e,table,checkboxes=[]){e.preventDefault();const fd=new FormData(e.target);const d=Object.fromEntries(fd);checkboxes.forEach(k=>d[k]=fd.get(k)==='on');try{await API.createMaster(table,d);toast('Saved to Supabase PostgreSQL.');await refreshBootstrap();renderMaster();}catch(err){toast(err.message,'error');}}

async function renderActivity(){const rows=await API.activity();$('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">AUDIT TRAIL</span><h2>Staff & customer activity</h2></div></div><div class="activity-list large">${rows.length?rows.map(a=>`<div><i data-lucide="history"></i><span><strong>${escapeHTML(titleize(a.action))}</strong><small>${escapeHTML(titleize(a.actor_role))} · ${escapeHTML(a.entity_type)} · ${fmtDate(a.created_at)}</small></span></div>`).join(''):'<div class="empty-inline">No recorded activity yet.</div>'}</div></section>`;icons();}
async function renderIntegrations(){const rows=await API.integrations();$('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">EXTERNAL MICROSERVICES</span><h2>API / microservice configuration slots</h2><p>Secret values stay in <code>server/.env</code>. This page shows only which slots exist and which base URLs are configured.</p></div></div><div class="integration-admin-grid">${rows.map(x=>`<article><i data-lucide="plug-zap"></i><div><strong>${escapeHTML(x.name)}</strong><small>${x.configured?'Base URL configured':'Waiting for provider integration'}</small><small>${(x.env_fields||[]).map(escapeHTML).join(' · ')}</small></div><span class="status-tag ${x.configured?'completed':''}">${x.configured?'Connected slot':'Not configured'}</span></article>`).join('')}</div></section>`;icons();}

async function renderPrescriptions(){const rows=await API.pharmacistPrescriptions();$('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">PHARMACIST</span><h2>Prescription verification queue</h2><p>The pharmacist—not the system—makes the final prescription decision.</p></div></div><div class="rx-queue">${rows.length?rows.map(r=>`<article><div><span class="status-tag ${r.status}">${escapeHTML(titleize(r.status))}</span><h3>${escapeHTML(r.product?.name||'Prescription')}</h3><p>${escapeHTML(r.customer?.full_name||'Customer')} · ${escapeHTML(r.customer?.email||'')}</p><small>Submitted ${fmtDate(r.created_at)}</small>${r.pharmacist_note?`<em>${escapeHTML(r.pharmacist_note)}</em>`:''}</div><div class="queue-actions"><button class="outline-btn small" data-rx-file="${r.id}"><i data-lucide="file-search"></i>View file</button><button class="primary-btn small" data-rx-review="${r.id}">Review</button></div></article>`).join(''):'<div class="empty-inline">No prescription submissions.</div>'}</div></section>`;$$('[data-rx-file]').forEach(b=>b.onclick=async()=>{try{const r=await API.prescriptionFile(b.dataset.rxFile);window.open(r.url,'_blank','noopener');}catch(err){toast(err.message,'error');}});$$('[data-rx-review]').forEach(b=>b.onclick=()=>reviewRxModal(b.dataset.rxReview));icons();}
function reviewRxModal(id){openModal(`<div class="modal-heading"><span class="section-kicker">VERIFY</span><h2>Prescription decision</h2><p>Choose the professional decision and leave a clear note for the customer when needed.</p></div><form id="rxReviewForm" class="form-stack"><label>Decision<select name="status"><option value="approved">Approve</option><option value="needs_information">Need More Information</option><option value="rejected">Reject</option></select></label><label>Pharmacist note<textarea name="pharmacist_note" rows="5"></textarea></label><button class="primary-btn">Save decision</button></form>`);$('#rxReviewForm').onsubmit=async e=>{e.preventDefault();try{await API.reviewPrescription(id,Object.fromEntries(new FormData(e.target)));toast('Prescription review saved.');closeModal();renderPrescriptions();}catch(err){toast(err.message,'error');}};}

async function renderSupport(){const rows=await API.pharmacistConsultations();$('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">CUSTOMER SUPPORT</span><h2>Pharmacist inquiry desk</h2><p>Handle medicine questions, prescription confusion, and appropriate OTC guidance. Do not use this as emergency triage.</p></div></div><div class="consult-list portal-consults">${rows.length?rows.map(c=>`<article class="consult-card"><div class="consult-head"><div><span class="status-tag">${escapeHTML(titleize(c.status))}</span><h3>${escapeHTML(c.subject)}</h3><p>${escapeHTML(c.customer?.full_name||'Customer')} · ${escapeHTML(c.customer?.email||'')}</p></div><small>${fmtDate(c.created_at)}</small></div><div class="message-thread">${c.messages.map(m=>`<div class="message ${m.sender_role==='customer'?'customer':'staff'}"><strong>${escapeHTML(titleize(m.sender_role))}</strong><p>${escapeHTML(m.message)}</p><small>${fmtDate(m.created_at)}</small></div>`).join('')}</div><form class="inline-reply" data-pharm-reply="${c.id}"><input name="message" placeholder="Reply to customer" required><select name="status"><option value="waiting_customer">Waiting Customer</option><option value="resolved">Resolved</option><option value="closed">Closed</option></select><button class="primary-btn small">Send</button></form></article>`).join(''):'<div class="empty-inline">No customer inquiries.</div>'}</div></section>`;$$('[data-pharm-reply]').forEach(f=>f.onsubmit=async e=>{e.preventDefault();try{await API.pharmacistReply(f.dataset.pharmReply,Object.fromEntries(new FormData(f)));toast('Reply sent.');renderSupport();}catch(err){toast(err.message,'error');}});icons();}

async function renderPharmacistMedicine(){await refreshBootstrap();const p=portalState.bootstrap.products;$('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">PHARMACIST EDIT ACCESS</span><h2>Medicine descriptions & classification</h2><p>Pharmacists can edit the customer-facing medicine use, full description, Rx/OTC classification, and image. Price, stock, and manufacturer remain controlled by Admin/Inventory roles.</p></div></div><div class="medicine-guidance-list">${p.length?p.map(x=>`<article><div class="tiny-product-img">${x.image_url?`<img src="${escapeHTML(x.image_url)}" alt="">`:'<i data-lucide="pill"></i>'}</div><div class="grow"><strong>${escapeHTML(x.name)}</strong><small>${escapeHTML(x.generic_name||'')}</small><textarea data-short-use="${x.id}" rows="2" placeholder="Short use / customer-facing summary">${escapeHTML(x.short_use||'')}</textarea><textarea data-description="${x.id}" rows="3" placeholder="Medicine description">${escapeHTML(x.description||'')}</textarea></div><label class="switch-line"><input type="checkbox" data-rx-toggle="${x.id}" ${x.requires_prescription?'checked':''}><span>${x.requires_prescription?'Prescription':'OTC'}</span></label><div class="stack-actions"><button class="primary-btn small" data-save-guidance="${x.id}">Save</button><button class="outline-btn small" data-product-image="${x.id}">Image</button></div></article>`).join(''):'<div class="empty-inline">No products yet.</div>'}</div></section>`;$$('[data-save-guidance]').forEach(b=>b.onclick=async()=>{const id=b.dataset.saveGuidance;try{await API.pharmacistProduct(id,{short_use:$(`[data-short-use="${id}"]`).value,description:$(`[data-description="${id}"]`).value,requires_prescription:$(`[data-rx-toggle="${id}"]`).checked});toast('Medicine description updated.');renderPharmacistMedicine();}catch(err){toast(err.message,'error');}});$$('[data-product-image]').forEach(b=>b.onclick=()=>imageUploadModal(b.dataset.productImage));icons();}

async function renderAttendance(){
  const rows=await API.attendance(); const role=staffRole();
  const fmtDuration=(a,b)=>{if(!a||!b)return 'Open shift';const ms=new Date(b)-new Date(a);return `${Math.max(0,ms/3600000).toFixed(2)} h`;};
  if(role==='admin'){
    $('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">ADMIN VERIFICATION</span><h2>Staff attendance</h2><p>Review Pharmacist and Merchandiser clock-in/out records before accepting attendance for payroll review.</p></div></div><div class="table-wrap"><table><thead><tr><th>Staff</th><th>Clock In</th><th>Clock Out</th><th>Hours</th><th>Status</th><th>Action</th></tr></thead><tbody>${rows.length?rows.map(r=>`<tr><td><strong>${escapeHTML(r.employee?.full_name||'Staff')}</strong><small>${escapeHTML(r.employee?.staff_id||'')}</small></td><td>${fmtDate(r.clock_in)}</td><td>${fmtDate(r.clock_out)}</td><td>${fmtDuration(r.clock_in,r.clock_out)}</td><td><span class="status-tag">${escapeHTML(titleize(r.status))}</span></td><td>${r.status==='pending'?`<div class="stack-actions"><button class="primary-btn small" data-attendance-action="${r.id}" data-attendance-status="verified">Verify</button><button class="danger-btn small" data-attendance-action="${r.id}" data-attendance-status="rejected">Reject</button></div>`:'—'}</td></tr>`).join(''):'<tr><td colspan="6">No attendance records.</td></tr>'}</tbody></table></div></section>`;
    $$('[data-attendance-action]').forEach(b=>b.onclick=async()=>{const note=prompt('Optional admin note:','')||'';try{await API.verifyAttendance(b.dataset.attendanceAction,{status:b.dataset.attendanceStatus,admin_note:note});toast(`Attendance ${b.dataset.attendanceStatus}.`);renderAttendance();}catch(err){toast(err.message,'error');}});
  }else{
    const open=rows.find(r=>!r.clock_out);
    $('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">MY ATTENDANCE</span><h2>Clock in / clock out</h2><p>Clock records remain Pending until the Admin verifies them.</p></div><div class="attendance-controls"><button class="primary-btn" id="clockInBtn" ${open?'disabled':''}><i data-lucide="log-in"></i>Clock In</button><button class="outline-btn" id="clockOutBtn" ${open?'':'disabled'}><i data-lucide="log-out"></i>Clock Out</button></div></div><div class="table-wrap"><table><thead><tr><th>Clock In</th><th>Clock Out</th><th>Hours</th><th>Status</th><th>Admin Note</th></tr></thead><tbody>${rows.length?rows.map(r=>`<tr><td>${fmtDate(r.clock_in)}</td><td>${fmtDate(r.clock_out)}</td><td>${fmtDuration(r.clock_in,r.clock_out)}</td><td><span class="status-tag">${escapeHTML(titleize(r.status))}</span></td><td>${escapeHTML(r.admin_note||'—')}</td></tr>`).join(''):'<tr><td colspan="5">No attendance records yet.</td></tr>'}</tbody></table></div></section>`;
    $('#clockInBtn').onclick=async()=>{try{await API.clockIn();toast('Clock-in recorded. Waiting for Admin verification.');renderAttendance();}catch(err){toast(err.message,'error');}};
    $('#clockOutBtn').onclick=async()=>{try{await API.clockOut();toast('Clock-out recorded. Waiting for Admin verification.');renderAttendance();}catch(err){toast(err.message,'error');}};
  }
  icons();
}


function merchandiserOptions(){
  const staff=(portalState.staff||[]).filter(x=>x.role==='merchandiser' && x.is_active!==false);
  return `<option value="">Assign later</option>${staff.map(x=>`<option value="${x.id}">${escapeHTML(x.full_name)}${x.staff_id?` (${escapeHTML(x.staff_id)})`:''}</option>`).join('')}`;
}
function supplierOptions(){ return `<option value="">No supplier selected</option>${optionRows(portalState.bootstrap?.suppliers||[])}`; }
function branchOptions(){ return `<option value="">Select branch</option>${optionRows(portalState.bootstrap?.branches||[])}`; }
function productOptions(selected=''){ return `<option value="">Select product</option>${(portalState.bootstrap?.products||[]).map(p=>`<option value="${p.id}" ${p.id===selected?'selected':''}>${escapeHTML(p.name)}</option>`).join('')}`; }
function manufacturerOptions(selected=''){ return `<option value="">Use product/default</option>${(portalState.bootstrap?.manufacturers||[]).map(m=>`<option value="${m.id}" ${m.id===selected?'selected':''}>${escapeHTML(m.name)}</option>`).join('')}`; }
function stockItemRow(index, item={}){
  return `<div class="delivery-item-row" data-delivery-item-row>
    <label>Product<select name="product_id" required>${productOptions(item.product_id||'')}</select></label>
    <label>Expected qty<input type="number" name="expected_quantity" min="1" value="${escapeHTML(item.expected_quantity||'')}" required></label>
    <label>Unit cost<input type="number" name="cost_per_unit" min="0" step="0.01" value="${escapeHTML(item.cost_per_unit||'')}" required></label>
    <label>Expiry<input type="date" name="expiration_date" value="${escapeHTML(item.expiration_date||'')}"></label>
    <button class="danger-btn small" type="button" data-remove-item-row><i data-lucide="trash-2"></i></button>
    <label>Manufacturer<select name="manufacturer_id">${manufacturerOptions(item.manufacturer_id||'')}</select></label>
    <label>Batch / Lot<input name="batch_number" value="${escapeHTML(item.batch_number||'')}"></label>
    <label style="grid-column:span 3">Note<input name="note" value="${escapeHTML(item.note||'')}"></label>
  </div>`;
}
function stockStatusTone(status=''){
  const value=String(status||'').toLowerCase();
  if(['completed','received'].includes(value)) return 'completed';
  if(['cancelled','failed','damaged'].includes(value)) return 'cancelled';
  if(['scheduled','arrived','receiving','short','queued'].includes(value)) return value;
  return '';
}
function deliveryCardHTML(delivery,{showReceive=false}={}){
  const items=delivery.items||[];
  const receivedTotal=items.reduce((sum,item)=>sum+Number(item.received_quantity||0),0);
  const expectedTotal=items.reduce((sum,item)=>sum+Number(item.expected_quantity||0),0);
  return `<article class="stock-delivery-card">
    <header>
      <div>
        <span class="section-kicker">${escapeHTML(delivery.delivery_reference||'DELIVERY PLAN')}</span>
        <h3>${escapeHTML(delivery.branch?.name||'Branch not set')}</h3>
        <small>${escapeHTML(delivery.supplier?.name||'Internal / not specified')} · Expected ${escapeHTML(delivery.expected_delivery_date||'—')}</small>
      </div>
      <span class="status-tag ${stockStatusTone(delivery.status)}">${escapeHTML(titleize(delivery.status||'scheduled'))}</span>
    </header>
    <div class="stock-delivery-meta">
      <div><span>Assigned merchandiser</span><strong>${escapeHTML(delivery.assignee?.full_name || 'Unassigned')}</strong></div>
      <div><span>Prepared by</span><strong>${escapeHTML(delivery.arranged_by_profile?.full_name || 'Admin')}</strong></div>
      <div><span>Items</span><strong>${items.length} line item(s)</strong></div>
      <div><span>Received vs expected</span><strong>${receivedTotal} / ${expectedTotal}</strong></div>
    </div>
    <div class="delivery-item-list">${items.map(item=>`<div class="delivery-item-chip"><div><strong>${escapeHTML(item.product?.name||'Product')}</strong><small>${escapeHTML(item.batch_number||'No batch yet')} · ${item.expiration_date?`EXP ${escapeHTML(item.expiration_date)}`:'No expiry set'}</small></div><div><strong>${Number(item.received_quantity||0)} / ${Number(item.expected_quantity||0)}</strong><small>${escapeHTML(titleize(item.status||'pending'))}</small></div></div>`).join('')}</div>
    ${delivery.notes?`<div class="subtle-card"><strong>Notes</strong><div>${escapeHTML(delivery.notes)}</div></div>`:''}
    ${showReceive?`<div class="compact-inline"><button class="primary-btn small" data-receive-delivery="${delivery.id}"><i data-lucide="package-check"></i>Receive & arrange</button></div>`:''}
  </article>`;
}

async function renderStockDeliveries(){
  await refreshBootstrap();
  if(!portalState.staff?.length) portalState.staff=await API.staff();
  const deliveries=await API.stockDeliveries();
  const content=$('#portalContent');
  content.innerHTML=`<div class="stock-delivery-form">
    <section class="panel">
      <div class="panel-head"><div><span class="section-kicker">ADMIN WORKFLOW</span><h2>Create inbound <span class="accent">stock delivery</span></h2><p>Admin schedules the incoming stock, then the merchandiser receives and arranges it before it becomes available in inventory.</p></div></div>
      <div class="notice-strip"><i data-lucide="circle-alert"></i><div><strong>Recommended workflow</strong><span>1) Admin prepares the delivery plan. 2) Merchandiser receives the actual stock. 3) Inventory is updated using the accepted quantity and batch details.</span></div></div>
      <form id="stockDeliveryForm" class="form-stack">
        <div class="form-grid two">
          <label>Branch<select name="branch_id" required>${branchOptions()}</select></label>
          <label>Supplier<select name="supplier_id">${supplierOptions()}</select></label>
        </div>
        <div class="form-grid two">
          <label>Assign merchandiser<select name="assigned_to">${merchandiserOptions()}</select></label>
          <label>Expected delivery date<input type="date" name="expected_delivery_date" value="${today()}" required></label>
        </div>
        <label>Delivery / DR reference<input name="delivery_reference" placeholder="DR-2026-0001"></label>
        <label>Notes<textarea name="notes" rows="3" placeholder="Supplier instructions, receiving notes, or handling reminders"></textarea></label>
        <div class="delivery-item-builder"><div class="compact-inline"><strong>Items</strong><button class="outline-btn small" type="button" id="addStockItemBtn"><i data-lucide="plus"></i>Add item</button></div><div id="stockDeliveryItems"></div></div>
        <button class="primary-btn" type="submit"><i data-lucide="truck"></i>Create stock delivery</button>
      </form>
    </section>
    <section class="panel">
      <div class="panel-head"><div><span class="section-kicker">CURRENT PLANS</span><h2>Inbound deliveries</h2><p>These deliveries are ready for merchandiser receiving and arrangement.</p></div></div>
      <div class="stock-delivery-grid">${deliveries.length?deliveries.map(delivery=>deliveryCardHTML(delivery)).join(''):'<div class="empty-inline">No inbound stock deliveries yet.</div>'}</div>
    </section>
  </div>`;
  const itemsBox=$('#stockDeliveryItems');
  const addRow=()=>{itemsBox.insertAdjacentHTML('beforeend',stockItemRow(itemsBox.children.length)); bindStockItemRowEvents(); icons();};
  function bindStockItemRowEvents(){ $$('[data-remove-item-row]', itemsBox).forEach(btn=>btn.onclick=()=>{btn.closest('[data-delivery-item-row]')?.remove();}); }
  $('#addStockItemBtn').onclick=addRow;
  addRow();
  // Manual extraction because FormData() does not work on a plain div.
  $('#stockDeliveryForm').onsubmit=async e=>{
    e.preventDefault();
    const base=Object.fromEntries(new FormData(e.target));
    const items=$$('[data-delivery-item-row]', itemsBox).map(row=>({
      product_id:$('[name="product_id"]',row).value,
      expected_quantity:$('[name="expected_quantity"]',row).value,
      cost_per_unit:$('[name="cost_per_unit"]',row).value,
      expiration_date:$('[name="expiration_date"]',row).value || null,
      manufacturer_id:$('[name="manufacturer_id"]',row).value || null,
      batch_number:$('[name="batch_number"]',row).value || null,
      note:$('[name="note"]',row).value || null,
    })).filter(item=>item.product_id && Number(item.expected_quantity)>0);
    if(!items.length){ toast('Add at least one delivery item.','error'); return; }
    try{
      await API.createStockDelivery({...base,supplier_id:base.supplier_id||null,assigned_to:base.assigned_to||null,items});
      toast('Inbound stock delivery created.');
      await renderStockDeliveries();
    }catch(err){toast(err.message,'error');}
  };
  icons();
}

async function renderIncomingStock(){
  await refreshBootstrap();
  const deliveries=(await API.stockDeliveries()).filter(delivery=>!['completed','cancelled'].includes(String(delivery.status||'').toLowerCase()));
  $('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">MERCHANDISER WORKFLOW</span><h2>Incoming stocks awaiting receiving</h2><p>Receive only the actual quantity delivered. Inventory will update from the accepted quantities and batch records.</p></div></div><div class="incoming-stock-grid">${deliveries.length?deliveries.map(delivery=>deliveryCardHTML(delivery,{showReceive:true})).join(''):'<div class="empty-inline">No inbound deliveries are waiting for receiving.</div>'}</div></section>`;
  $$('[data-receive-delivery]').forEach(btn=>btn.onclick=()=>openReceiveDeliveryModal(deliveries.find(x=>x.id===btn.dataset.receiveDelivery)));
  icons();
}

function openReceiveDeliveryModal(delivery){
  if(!delivery) return;
  openModal(`<div class="panel-head"><div><span class="section-kicker">RECEIVE STOCK</span><h2>${escapeHTML(delivery.delivery_reference||'Stock delivery')}</h2><p>${escapeHTML(delivery.branch?.name||'Branch')} · ${escapeHTML(delivery.supplier?.name||'No supplier')}</p></div></div>
  <form id="receiveDeliveryForm" class="receiving-table">
    ${delivery.items.map(item=>`<div class="receiving-row" data-receiving-row="${item.id}"><div><h4>${escapeHTML(item.product?.name||'Product')}</h4><p>Expected ${Number(item.expected_quantity||0)} unit(s). ${item.expiration_date?`Expiry ${escapeHTML(item.expiration_date)}.`:''}</p></div><div class="receiving-grid"><label>Received qty<input type="number" name="received_quantity" min="0" max="${Number(item.expected_quantity||0)}" value="${Number(item.expected_quantity||0)}"></label><label>Status<select name="status"><option value="received">Received in full</option><option value="short">Short delivered</option><option value="damaged">Damaged / rejected</option></select></label><label>Batch / Lot<input name="batch_number" value="${escapeHTML(item.batch_number||'')}"></label><label>Expiry<input type="date" name="expiration_date" value="${escapeHTML(item.expiration_date||'')}"></label><label>Manufacturer<select name="manufacturer_id">${manufacturerOptions(item.manufacturer_id||'')}</select></label><label>Unit cost<input type="number" name="cost_per_unit" min="0" step="0.01" value="${escapeHTML(item.cost_per_unit||'0')}"></label></div><label>Receiving note<textarea name="note" rows="2" placeholder="Short delivery, damaged packaging, or storage remarks"></textarea></label></div>`).join('')}
    <label>Delivery note<textarea name="notes" rows="3" placeholder="Optional notes for this received delivery"></textarea></label>
    <div class="compact-inline"><button class="primary-btn" type="submit"><i data-lucide="package-check"></i>Post received stock</button><button class="outline-btn" type="button" id="closeReceiveModal">Cancel</button></div>
  </form>`);
  $('#closeReceiveModal').onclick=closeModal;
  $('#receiveDeliveryForm').onsubmit=async e=>{
    e.preventDefault();
    const items=$$('[data-receiving-row]').map(row=>({
      item_id:row.dataset.receivingRow,
      received_quantity:$('[name="received_quantity"]',row).value,
      status:$('[name="status"]',row).value,
      batch_number:$('[name="batch_number"]',row).value || null,
      expiration_date:$('[name="expiration_date"]',row).value || null,
      manufacturer_id:$('[name="manufacturer_id"]',row).value || null,
      cost_per_unit:$('[name="cost_per_unit"]',row).value,
      note:$('[name="note"]',row).value || null,
    }));
    const notes=$('[name="notes"]',e.target).value || null;
    try{
      await API.receiveStockDelivery(delivery.id,{items,notes});
      toast('Stock received and inventory updated.');
      closeModal();
      await renderIncomingStock();
    }catch(err){toast(err.message,'error');}
  };
  icons();
}

async function renderReceiveStock(){await refreshBootstrap();const b=portalState.bootstrap;$('#portalContent').innerHTML=`<section class="panel receive-panel"><div class="panel-head"><div><span class="section-kicker">MERCHANDISER</span><h2>Record a stock delivery</h2><p>Every delivery becomes a dated batch so expiration and manufacturer records remain traceable.</p></div></div><form id="receiveForm" class="form-stack"><div class="form-grid two"><label>Branch<select name="branch_id" required><option value="">Select branch</option>${optionRows(b.branches)}</select></label><label>Supplier<select name="supplier_id"><option value="">No supplier selected</option>${optionRows(b.suppliers)}</select></label></div><div class="form-grid two"><label>Product<select name="product_id" required><option value="">Select product</option>${optionRows(b.products)}</select></label><label>Manufacturer<select name="manufacturer_id"><option value="">Use product/default</option>${optionRows(b.manufacturers)}</select></label></div><div class="form-grid three"><label>Delivery date<input type="date" name="delivery_date" value="${today()}" required></label><label>Batch / Lot No.<input name="batch_number"></label><label>Expiration date<input type="date" name="expiration_date"></label></div><div class="form-grid three"><label>Quantity delivered<input type="number" name="quantity" min="1" required></label><label>Cost per unit<input type="number" name="cost_per_unit" min="0" step="0.01" required></label><label>Reorder level<input type="number" name="reorder_level" min="0" value="10"></label></div><label>Delivery / DR reference<input name="delivery_reference"></label><label>Notes<textarea name="notes" rows="3"></textarea></label><button class="primary-btn">Receive into inventory</button></form></section>`;$('#receiveForm').onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));if(!d.supplier_id)delete d.supplier_id;if(!d.manufacturer_id)delete d.manufacturer_id;if(!d.expiration_date)delete d.expiration_date;try{await API.receiveStock(d);toast('Stock delivery recorded and inventory updated.');e.target.reset();}catch(err){toast(err.message,'error');}};icons();}

async function renderMerchProducts(){await refreshBootstrap();const p=portalState.bootstrap.products,b=portalState.bootstrap;$('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">PRODUCT ASSETS</span><h2>Manufacturer & product image</h2><p>Merchandiser access is limited to inventory-related manufacturer linkage and product imagery.</p></div></div><div class="merch-product-list">${p.length?p.map(x=>`<article><div class="tiny-product-img">${x.image_url?`<img src="${escapeHTML(x.image_url)}" alt="">`:'<i data-lucide="image"></i>'}</div><div class="grow"><strong>${escapeHTML(x.name)}</strong><select data-manufacturer="${x.id}"><option value="">No manufacturer</option>${b.manufacturers.map(m=>`<option value="${m.id}" ${m.id===x.manufacturer_id?'selected':''}>${escapeHTML(m.name)}</option>`).join('')}</select></div><button class="primary-btn small" data-save-maker="${x.id}">Save Manufacturer</button><button class="outline-btn small" data-product-image="${x.id}">Image</button></article>`).join(''):'<div class="empty-inline">No products yet.</div>'}</div></section>`;$$('[data-save-maker]').forEach(btn=>btn.onclick=async()=>{const id=btn.dataset.saveMaker;try{await API.merchProduct(id,{manufacturer_id:$(`[data-manufacturer="${id}"]`).value||null});toast('Manufacturer updated.');}catch(err){toast(err.message,'error');}});$$('[data-product-image]').forEach(b=>b.onclick=()=>imageUploadModal(b.dataset.productImage));icons();}

let activeRiderWatch=null;
let activeRiderDelivery=null;
let lastRiderUpdate=0;
function stopSharingRiderLocation(silent=false){
  if(activeRiderWatch!==null && navigator.geolocation){
    navigator.geolocation.clearWatch(activeRiderWatch);
  }
  activeRiderWatch=null;activeRiderDelivery=null;
  if(!silent)toast('Location sharing stopped.');
}
function startSharingRiderLocation(deliveryId){
  if(!navigator.geolocation){toast('GPS location is not supported on this device.','error');return;}
  if(activeRiderWatch!==null)stopSharingRiderLocation(true);
  activeRiderDelivery=deliveryId;
  const onPosition=async position=>{
    if(Date.now()-lastRiderUpdate<7000)return;
    lastRiderUpdate=Date.now();
    try{await API.riderLocation(deliveryId,{
      latitude:position.coords.latitude,
      longitude:position.coords.longitude,
      accuracy:position.coords.accuracy
    });}catch(err){stopSharingRiderLocation(true);toast(err.message,'error');}
  };
  activeRiderWatch=navigator.geolocation.watchPosition(onPosition,
    err=>{stopSharingRiderLocation(true);toast(`GPS unavailable: ${err.message}`,'error');},
    {enableHighAccuracy:true,timeout:15000,maximumAge:3000});
  toast('Sharing live GPS while this page remains active.');
}
window.addEventListener('pagehide',()=>stopSharingRiderLocation(true));

// A printable receipt image generated locally from the assigned order's data.
// Nothing is uploaded or written to server storage.
function receiptImage(order) {
  const canvas=document.createElement('canvas');
  canvas.width=760;
  const rows=Array.isArray(order.items)?order.items:[];
  canvas.height=425+rows.length*48;
  const ctx=canvas.getContext('2d');
  if(!ctx)throw new Error('Receipt preview is unavailable on this browser.');
  ctx.fillStyle='#ffffff';ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.fillStyle='#19382f'; ctx.fillRect(0,0,760,104);
  ctx.textAlign='center';ctx.fillStyle='#ffffff';ctx.font='bold 31px Arial';ctx.fillText('360 PHARMACY',380,52);
  ctx.font='19px Arial';ctx.fillText('ORDER RECEIPT',380,84);
  ctx.textAlign='left';ctx.fillStyle='#263a31';ctx.font='20px Arial';
  const line=(label,value,y)=>{ctx.fillText(label,38,y);ctx.textAlign='right';ctx.fillText(String(value??''),722,y);ctx.textAlign='left';};
  line('Order',String(order.order_number||''),155);
  const date=new Date(order.created_at);line('Date', Number.isNaN(date.valueOf())?'—':date.toLocaleDateString('en-PH'),187);
  line('Payment',String(order.payment_status||'unpaid').toUpperCase(),219);
  ctx.strokeStyle='#cfdad4';ctx.beginPath();ctx.moveTo(38,242);ctx.lineTo(722,242);ctx.stroke();
  let y=278;ctx.font='17px Arial';
  const price=n=>'PHP '+Number(n||0).toFixed(2);
  rows.forEach(item=>{
    let name=String(item.product_name_snapshot||'Medicine');
    if(name.length>45)name=name.slice(0,43)+'…';
    ctx.fillText(name,38,y);
    ctx.textAlign='right';ctx.fillText(`${Number(item.quantity||0)} x ${price(item.final_unit_price)}`,722,y);
    ctx.textAlign='left';y+=48;
  });
  ctx.strokeStyle='#cfdad4';ctx.beginPath();ctx.moveTo(38,y);ctx.lineTo(722,y);ctx.stroke();
  ctx.font='bold 26px Arial';line('TOTAL',price(order.total_amount),y+46);
  ctx.textAlign='center';ctx.font='17px Arial';ctx.fillStyle='#596e62';
  ctx.fillText(order.payment_status==='paid'?'PAID':'NOT A PROOF OF PAYMENT',380,canvas.height-46);
  return canvas.toDataURL('image/png');
}
async function previewDeliveryReceipt(deliveryId) {
  try {
    const data=await API.deliveryReceipt(deliveryId);
    const img=receiptImage(data);
    const name=String(data.order_number||'order').replace(/[^a-zA-Z0-9_-]/g,'_');
    openModal(`<div class="panel-head"><div><h2>Order receipt</h2><small>${escapeHTML(data.order_number)}</small></div></div><img class="receipt-preview" src="${img}" alt="Order receipt"><div class="stack-actions"><a class="primary-btn small" href="${img}" download="pharmacy360-receipt-${name}.png"><i data-lucide="download"></i>Download image</a></div>`);
  } catch(err){toast(err.message,'error');}
}

async function renderDeliveryPackages(){
  const rows=await API.deliveryPackages();
  if(activeRiderDelivery && !rows.some(d=>d.id===activeRiderDelivery && ['handed_to_courier','in_transit','out_for_delivery'].includes(d.order?.status))) stopSharingRiderLocation(true);
  $('#portalContent').innerHTML=`<section class="panel"><div class="panel-head"><div><span class="section-kicker">DELIVERY ACCOUNT</span><h2>Choose and deliver packages</h2></div></div><div class="task-grid">${rows.length?rows.map(d=>{const o=d.order||{};const mine=d.assigned_to===portalState.user.profile.id;let action='';if(!d.assigned_to)action=`<button class="primary-btn small" data-claim-package="${d.id}">Choose Package</button>`;else if(mine&&o.status==='handed_to_courier')action=`<button class="primary-btn small" data-delivery-status="${d.id}" data-status="in_transit">Transit</button>`;else if(mine&&o.status==='in_transit')action=`<button class="primary-btn small" data-delivery-status="${d.id}" data-status="out_for_delivery">Out for Delivery</button>`;else if(mine&&o.status==='out_for_delivery')action=`<button class="primary-btn small" data-delivery-status="${d.id}" data-status="delivered">Delivered</button>`;const gpsAction=mine&&['handed_to_courier','in_transit','out_for_delivery'].includes(o.status)?`<button class="outline-btn small" data-gps-id="${d.id}">${activeRiderDelivery===d.id?'Stop GPS sharing':'Share live GPS'}</button>`:'';
  const paymentAction=mine&&o.payment_method==='cash_on_delivery'&&['delivered','order_received'].includes(o.status)&&o.payment_status!=='paid'&&!d.payment_sent_at?`<button class="outline-btn small" data-payment-sent="${d.id}">Payment Sent</button>`:'';const paymentInfo=o.payment_status==='paid'?'<span class="status-tag completed">Paid</span>':(o.payment_method!=='cash_on_delivery'?'<span class="status-tag">No Rider Remittance</span>':(d.payment_sent_at?'<span class="status-tag completed">Payment Sent</span>':'<span class="status-tag pending">Payment Pending</span>'));return `<article class="task-card"><span class="status-tag ${o.status||d.status}">${escapeHTML(titleize(o.status||d.status))}</span><h3>${escapeHTML(o.order_number||'Package')}</h3><p>${mine?'Selected by you':'Available package'}</p><small>${fmtDate(o.created_at)}</small><div class="finance-breakdown"><div><span>Price per package</span><strong>${peso(o.total_amount)}</strong></div><div><span>Payment</span><strong>${paymentInfo}</strong></div></div><div class="stack-actions">${action}${gpsAction}${paymentAction}${mine?`<button class="outline-btn small" data-receipt="${d.id}"><i data-lucide="image"></i>Preview receipt</button>`:''}</div></article>`;}).join(''):'<div class="empty-inline">No packages are available or assigned to you.</div>'}</div></section>`;
  $$('[data-receipt]').forEach(b=>b.onclick=()=>previewDeliveryReceipt(b.dataset.receipt));
  $$('[data-gps-id]').forEach(btn=>btn.onclick=()=>{
    if(activeRiderDelivery===btn.dataset.gpsId)stopSharingRiderLocation();
    else startSharingRiderLocation(btn.dataset.gpsId);
    renderDeliveryPackages();
  });
  $$('[data-claim-package]').forEach(b=>b.onclick=async()=>{try{await API.claimPackage(b.dataset.claimPackage);toast('Package selected.');renderDeliveryPackages();}catch(err){toast(err.message,'error');}});
  $$('[data-delivery-status]').forEach(b=>b.onclick=async()=>{try{await API.deliveryStatus(b.dataset.deliveryStatus,{status:b.dataset.status});toast(`Delivery updated: ${titleize(b.dataset.status)}.`);renderDeliveryPackages();}catch(err){toast(err.message,'error');}});
  $$('[data-payment-sent]').forEach(b=>b.onclick=async()=>{if(!confirm('Confirm that you sent this package payment to the pharmacy?'))return;try{await API.deliveryPaymentSent(b.dataset.paymentSent);toast('Payment Sent recorded. Admin can now mark the order Paid.');renderDeliveryPackages();}catch(err){toast(err.message,'error');}});icons();
}

function setupPortalEvents(){
  $('#portalLogout').onclick = async () => {
    stopSharingRiderLocation(true);
    await API.logout();
    portalState.user = null;
    portalState.bootstrap = null;
    location.assign('/login');
  };
  $('#refreshPortal').onclick = async () => {
    try { await navigate(portalState.section); await refreshBadges(true); }
    catch (err) { toast(err.message,'error'); }
  };
  $('#portalModal').addEventListener('click',e => {if (e.target===$('#portalModal')) closeModal();});
  $('#portalModal .modal-close').onclick = closeModal;
}

window.addEventListener('DOMContentLoaded',async()=>{setupPortalEvents();await sessionStart();icons();});
