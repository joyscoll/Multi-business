const $ = s => document.querySelector(s);
let cart = [];
const HOLD_KEY = 'denmart-held-sales-v13';
const VIEW_TITLES = {sale:'New sale',catalogue:'Catalogue',held:'Held sales',summary:'Day summary',orders:'Online orders',drawer:'Cash drawer',shift:'Shift'};
const IDB_NAME = 'denmart-pos-local';
const IDB_VERSION = 1;

function esc(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function money(n){return `KES ${Number(n||0).toFixed(2)}`}
function status(){const on=navigator.onLine;$('#networkStatus').textContent=on?'ONLINE':'OFFLINE';$('#networkStatus').className='live-dot '+(on?'on':'off');$('#networkStatus').title=on?'Connected to Denmart server':'Offline — cached catalogue and queued cash/card sales remain available'}
window.addEventListener('online',()=>{status();syncOffline();});window.addEventListener('offline',status);status();

function openLocalDB(){return new Promise((resolve,reject)=>{
  if(!('indexedDB' in window)) return resolve(null);
  const req=indexedDB.open(IDB_NAME,IDB_VERSION);
  req.onupgradeneeded=()=>{const db=req.result;if(!db.objectStoreNames.contains('catalogue'))db.createObjectStore('catalogue',{keyPath:'id'});if(!db.objectStoreNames.contains('queue'))db.createObjectStore('queue',{keyPath:'client_ref'});if(!db.objectStoreNames.contains('scans'))db.createObjectStore('scans',{keyPath:'id',autoIncrement:true});};
  req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);
})}
async function idbPut(storeName,value){const db=await openLocalDB();if(!db)return;return new Promise((resolve,reject)=>{const tx=db.transaction(storeName,'readwrite');tx.objectStore(storeName).put(value);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);})}
async function idbGet(storeName,key){const db=await openLocalDB();if(!db)return null;return new Promise((resolve,reject)=>{const tx=db.transaction(storeName,'readonly');const r=tx.objectStore(storeName).get(key);r.onsuccess=()=>resolve(r.result||null);r.onerror=()=>reject(r.error);})}
async function idbAll(storeName){const db=await openLocalDB();if(!db)return [];return new Promise((resolve,reject)=>{const tx=db.transaction(storeName,'readonly');const r=tx.objectStore(storeName).getAll();r.onsuccess=()=>resolve(r.result||[]);r.onerror=()=>reject(r.error);})}
async function idbDelete(storeName,key){const db=await openLocalDB();if(!db)return;return new Promise((resolve,reject)=>{const tx=db.transaction(storeName,'readwrite');tx.objectStore(storeName).delete(key);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);})}
function beep(ok=true){try{const C=window.AudioContext||window.webkitAudioContext;if(!C)return;const c=new C(),o=c.createOscillator(),g=c.createGain();o.frequency.value=ok?880:220;g.gain.value=.035;o.connect(g);g.connect(c.destination);o.start();o.stop(c.currentTime+.08)}catch(e){}}

async function cacheProducts(items){for(const item of items||[])await idbPut('catalogue',item)}
async function warmCache(){if(!navigator.onLine)return;try{const r=await fetch('/api/pos/catalogue/cache?limit=300',{credentials:'same-origin'});if(r.ok){const d=await r.json();await cacheProducts(d.items||[]);}}catch(e){}}
async function localBarcode(barcode){const rows=await idbAll('catalogue');return rows.find(x=>String(x.barcode||'')===String(barcode))||null}

function productButton(x){
  const initials=String(x.name||'DM').split(/\s+/).slice(0,2).map(v=>v[0]).join('').toUpperCase();
  const media=x.image_url?`<img src="${esc(x.image_url)}" alt="" loading="lazy" onerror="this.outerHTML='<span class=\"pos-initials\">${esc(initials)}</span>'">`:`<span class="pos-initials">${esc(initials)}</span>`;
  return `<button class="pos-product" onclick='addPOS(${JSON.stringify(x.id)},${JSON.stringify(x.name)},${Number(x.price)},${Number(x.stock||0)})'>${media}<span><strong>${esc(x.name)}</strong><small>${esc(x.barcode||x.sku||'Catalogue')}</small></span><b>${money(x.price)}</b></button>`;
}

async function findBarcode(q){
  if(!navigator.onLine){const x=await localBarcode(q);if(x){beep(true);await idbPut('scans',{barcode:String(q),at:new Date().toISOString()});return [x]}beep(false);return []}
  const r=await fetch(`/api/pos/products/barcode/${encodeURIComponent(q)}`,{credentials:'same-origin'});
  if(r.ok){const d=await r.json();await cacheProducts([d]);await idbPut('scans',{barcode:String(q),at:new Date().toISOString()});beep(true);return [d]}
  beep(false);return [];
}

async function searchPOS(){
  const q=$('#posSearch').value.trim();if(!q){$('#posSearch').focus();return;}
  try{
    const rows=/^\d{6,14}$/.test(q)?await findBarcode(q):await searchText(q);
    $('#productResults').innerHTML=rows.map(productButton).join('')||`<div class="pos-empty">No matching item${navigator.onLine?'':' in the offline catalogue'}.</div>`;
  }catch(e){$('#productResults').innerHTML='<div class="pos-empty">Terminal could not complete that lookup.</div>';beep(false)}
}
function normalizeSearchText(value){return String(value||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim()}
function editDistance(a,b){a=normalizeSearchText(a);b=normalizeSearchText(b);const prev=Array.from({length:b.length+1},(_,i)=>i);for(let i=1;i<=a.length;i++){let cur=[i];for(let j=1;j<=b.length;j++)cur[j]=Math.min(cur[j-1]+1,prev[j]+1,prev[j-1]+(a[i-1]===b[j-1]?0:1));for(let j=0;j<=b.length;j++)prev[j]=cur[j]}return prev[b.length]}
function localFuzzySearch(rows,q,limit=50){const needle=normalizeSearchText(q);if(!needle)return rows.slice(0,limit);return rows.map(x=>{const hay=normalizeSearchText(`${x.name} ${x.barcode||''} ${x.sku||''}`);const name=normalizeSearchText(x.name);const exact=hay.includes(needle)?100:0;const ratio=1-(editDistance(needle,name)/Math.max(needle.length,name.length,1));return {x,score:Math.max(exact,ratio*100)}}).filter(v=>v.score>=58).sort((a,b)=>b.score-a.score||a.x.name.localeCompare(b.x.name)).slice(0,limit).map(v=>v.x)}
async function searchText(q){
  if(!navigator.onLine){return localFuzzySearch(await idbAll('catalogue'),q,50)}
  const r=await fetch('/api/pos/products/search?q='+encodeURIComponent(q),{credentials:'same-origin'});const d=await r.json();await cacheProducts(d.items||[]);return d.items||[];
}
window.addPOS=function(id,name,price,stock){const x=cart.find(i=>i.id===id);if(x)x.qty++;else cart.push({id,name,price:Number(price),qty:1,stock:Number(stock)});renderCart();$('#posSearch').select();beep(true)};
window.changeQty=function(i,d){cart[i].qty+=d;if(cart[i].qty<=0)cart.splice(i,1);renderCart()};
window.removeLine=function(i){cart.splice(i,1);renderCart()};
function renderCart(){const el=$('#saleLines');let total=0;el.innerHTML=cart.map((x,i)=>{const line=x.price*x.qty;total+=line;return `<div class="sale-line"><div class="sale-line-copy"><strong>${esc(x.name)}</strong><small>${money(x.price)} each</small></div><div class="sale-qty"><button onclick="changeQty(${i},-1)">−</button><b>${x.qty}</b><button onclick="changeQty(${i},1)">+</button></div><strong>${money(line)}</strong><button class="line-x" onclick="removeLine(${i})">×</button></div>`}).join('')||'<div class="cart-empty"><div>⌕</div><strong>Ready for the next customer</strong><span>Scan a barcode or search an item.</span></div>';$('#saleTotal').textContent=total.toFixed(2);$('#payButtons').classList.toggle('disabled',!cart.length)}

async function apiJSON(url,options){const r=await fetch(url,{credentials:'same-origin',...options});let d={};try{d=await r.json()}catch(e){}return {r,d}}

async function queueOfflineSale(method){
  const client_ref=`OFF-${Date.now()}-${crypto.randomUUID?crypto.randomUUID().slice(0,8):Math.random().toString(16).slice(2,10)}`;
  const payload={client_ref,payment_method:method,items:cart.map(x=>({store_product_id:x.id,quantity:x.qty}))};
  await idbPut('queue',{...payload,queued_at:new Date().toISOString()});
  toast(`${method==='CASH'?'Cash':'Card'} sale queued locally`);cart=[];renderCart();renderOfflineQueueBadge();
}
async function syncOffline(){if(!navigator.onLine)return;const queued=await idbAll('queue');if(!queued.length)return;try{const {r,d}=await apiJSON('/api/pos/sync/offline',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sales:queued})});if(!r.ok)return;for(const item of d.results||[]){if(item.ok)await idbDelete('queue',item.client_ref)}if((d.results||[]).some(x=>x.ok))toast('Offline sales synced to Denmart');renderOfflineQueueBadge()}catch(e){}}

let lastMpesaTransaction='';
async function refreshMpesaFeed(){
  const headline=$('#posMpesaLast'), today=$('#posMpesaToday'); if(!headline||!navigator.onLine)return;
  try{
    const {r,d}=await apiJSON('/api/pos/mpesa-feed'); if(!r.ok)return;
    if(today)today.textContent=`KES ${Number(d.received_total||0).toFixed(2)} today · ${Number(d.matched_total||0).toFixed(2)} matched`;
    const e=(d.events||[])[0];
    if(!e){headline.textContent='Waiting';return;}
    const ref=e.order_number?`Order ${e.order_number}`:(e.receipt_number?`Receipt ${e.receipt_number}`:(e.transaction||'M-PESA'));
    const progress=e.received_amount!=null ? ` · ${money(e.received_amount)}/${money(e.required_amount)}` : '';
    const state=e.status==='MATCHED' ? (e.outstanding_amount>0?'PART':'PAID') : 'WAIT';
    headline.textContent=`${e.status==='MATCHED'?'✓':'•'} ${money(e.amount)} · ${state} · ${ref}`;
    headline.title=`${e.customer||'M-PESA customer'} · ${e.payment_label||'Received'}${progress}${e.outstanding_amount!=null&&Number(e.outstanding_amount)>0?` · Remaining ${money(e.outstanding_amount)}`:''}`;
    if(e.transaction && e.transaction!==lastMpesaTransaction){ lastMpesaTransaction=e.transaction; if(e.status==='MATCHED') beep(true); }
  }catch(e){}
}

async function makeSale(method){
  if(!cart.length)return toast('Add an item first');
  if(method==='MPESA'&&!navigator.onLine)return toast('M-PESA needs an internet connection');
  if(!navigator.onLine && method!=='MPESA')return queueOfflineSale(method);
  const phone=method==='MPESA'?prompt('Customer M-PESA number (07xx xxx xxx)',''):null;
  if(method==='MPESA'&&!phone)return toast('Payment not started');
  const reference=method==='CARD'?prompt('Card / external payment reference',''):null;
  if(method==='CARD'&&!reference)return toast('Payment not recorded');
  const {r,d}=await apiJSON('/api/pos/sales',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payment_method:method,items:cart.map(x=>({store_product_id:x.id,quantity:x.qty})),payment_reference:reference})});
  if(!r.ok)return toast(d.error||'Sale failed');
  if(method==='MPESA'){
    const p=await apiJSON('/api/payments/mpesa/initiate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sale_id:d.sale_id,amount:d.total,phone_number:phone})});
    if(p.r.ok){
      toast('M-PESA prompt sent');
      waitForPayment(p.d.payment_id,d.receipt_number);
    }else if(p.r.status===503 && (p.d.error==='mpesa_not_configured'||p.d.error==='payment_provider_unavailable')){
      const g=await apiJSON('/api/payments/gateway/await',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sale_id:d.sale_id,phone_number:phone})});
      if(!g.r.ok)return toast(g.d.message||g.d.error||'M-PESA gateway could not start');
      toast('Ask customer to pay to the M-PESA line · waiting for confirmation');
      waitForPayment(g.d.payment_id,d.receipt_number);
    }else{
      return toast(p.d.message||p.d.error||'M-PESA request failed');
    }
  }else{
    toast('Sale complete · '+d.receipt_number);window.open('/merchant/receipt/'+encodeURIComponent(d.receipt_number),'_blank','noopener');cart=[];renderCart();
  }
}
function paintMpesaPaymentCard(d, receiptNumber){
  const el=document.getElementById('mpesaPaymentCard'); if(!el) return;
  const total=Number(d.required_amount||d.amount||0);
  const received=Number(d.received_amount||0);
  const outstanding=Math.max(0,Number(d.outstanding_amount ?? (total-received)));
  el.hidden=false;
  if(d.status==='PAID'){
    el.innerHTML=`<div class="mpesa-card-state ok">✓ M-PESA PAYMENT COMPLETE</div><strong>${money(received)}</strong><small>${esc(receiptNumber)} · Fully paid</small>`;
  } else if(received>0){
    el.innerHTML=`<div class="mpesa-card-state partial">◔ PART PAYMENT RECEIVED</div><strong>${money(received)} / ${money(total)}</strong><small>${esc(receiptNumber)} · Remaining ${money(outstanding)} · Ask customer to pay the balance</small>`;
  } else {
    el.innerHTML=`<div class="mpesa-card-state">M-PESA LISTENING</div><strong>${money(total)}</strong><small>${esc(receiptNumber)} · Waiting for customer payment</small>`;
  }
}

async function waitForPayment(paymentId,receiptNumber){
  let checks=0;
  const poll=async()=>{
    checks++;
    try{
      const {d}=await apiJSON('/api/payments/'+encodeURIComponent(paymentId)+'/status');
      paintMpesaPaymentCard(d,receiptNumber);
      if(d.status==='PAID'){
        toast('M-PESA confirmed · '+receiptNumber); cart=[]; renderCart();
        setTimeout(()=>window.open('/merchant/receipt/'+encodeURIComponent(receiptNumber),'_blank','noopener'),250);
        return;
      }
      if(d.status==='FAILED'){ toast(d.message||'M-PESA payment failed'); return; }
      if(d.status==='PARTIALLY_PAID' && Number(d.outstanding_amount)>0){
        if(checks % 8 === 1) toast('Part payment received · remaining '+money(d.outstanding_amount));
      }
    }catch(e){}
    if(checks<240) setTimeout(poll,2500);
    else toast('Payment is still pending — it will remain open until fully paid');
  };
  poll();
}

async function openShift(){const cash=prompt('Opening cash (KES)','0');if(cash===null)return;const {r,d}=await apiJSON('/api/pos/shifts/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({opening_cash:cash})});toast(r.ok?'Shift opened.':(d.error||'Could not open shift'));if(r.ok)location.reload()}
async function closeShift(){const cash=prompt('Counted closing cash (KES)','0');if(cash===null)return;const {r,d}=await apiJSON('/api/pos/shifts/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({closing_cash:cash})});toast(r.ok?`Shift closed · difference ${money(d.difference)}`:(d.error||'Could not close shift'));if(r.ok)setTimeout(()=>location.reload(),900)}
window.loadDaySummary=async function(){const {r,d}=await apiJSON('/api/pos/day-summary');if(!r.ok)return toast(d.error||'Summary unavailable');const el=$('#summaryCards');if(el)el.innerHTML=`<div class="mini-stat"><small>Paid sales</small><strong>${d.sales_count}</strong></div><div class="mini-stat"><small>Sales total</small><strong>${money(d.sales_total)}</strong></div><div class="mini-stat"><small>Cash</small><strong>${money(d.cash_sales)}</strong></div>`};
window.cashDrawer=async function(kind){const amount=prompt('Amount (KES)','0');if(!amount)return;const notes=prompt('Note','')||'';const {r,d}=await apiJSON('/api/pos/cash-drawer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:kind,amount,notes})});toast(r.ok?'Drawer entry recorded.':(d.error||'Drawer entry failed'))};
window.loadOrders=async function(){const el=$('#orderList');if(!el)return;el.innerHTML='<div class="muted">Loading…</div>';const {r,d}=await apiJSON('/api/pos/orders');if(!r.ok){el.innerHTML='<div class="muted">'+esc(d.error||'Unavailable')+'</div>';return}el.innerHTML=(d.items||[]).map(x=>{const next=x.fulfillment_status==='PENDING'?'PACKING':x.fulfillment_status==='PACKING'?'READY_FOR_DISPATCH':x.fulfillment_status==='READY_FOR_DISPATCH'?'OUT_FOR_DELIVERY':'DELIVERED';const received=Number(x.received_amount||0),remaining=Number(x.outstanding_amount||0);const pay=received>0&&remaining>0?`<small>Received ${money(received)} · Remaining ${money(remaining)}</small>`:`<small>${esc(x.payment_status)}</small>`;return `<div class="activity-row"><div><strong>${esc(x.order_number)}</strong><small>${esc(x.customer||'Online customer')}</small>${pay}</div><div class="order-mini-actions"><b>${money(x.total)}</b><small>${esc(x.fulfillment_status)}</small>${x.payment_status==='PAID'&&x.fulfillment_status!=='DELIVERED'&&x.fulfillment_status!=='CANCELLED'?`<button class="admin-action" onclick="advanceOrder('${encodeURIComponent(x.order_number)}','${next}')">${next.replaceAll('_',' ')}</button>`:''}</div></div>`}).join('')||'<div class="muted">No online orders yet.</div>'};
window.advanceOrder=async function(orderNumber,state){const {r,d}=await apiJSON('/api/pos/orders/'+orderNumber+'/fulfillment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fulfillment_status:state})});toast(r.ok?'Order updated.':(d.error||'Could not update order'));if(r.ok)loadOrders()};
window.holdSale=async function(){if(!cart.length)return toast('Basket is empty');const h=JSON.parse(localStorage.getItem(HOLD_KEY)||'[]');h.push({at:new Date().toISOString(),items:cart});localStorage.setItem(HOLD_KEY,JSON.stringify(h));cart=[];renderCart();renderHeld();toast('Sale held on this till')};
window.resumeHeld=function(i){const h=JSON.parse(localStorage.getItem(HOLD_KEY)||'[]');const x=h.splice(i,1)[0];if(!x)return;cart=x.items||[];localStorage.setItem(HOLD_KEY,JSON.stringify(h));renderCart();renderHeld();document.querySelector('[data-view="sale"]').click();toast('Held sale recalled')};
window.renderHeld=function(){const el=$('#heldList');if(!el)return;const h=JSON.parse(localStorage.getItem(HOLD_KEY)||'[]');el.innerHTML=h.map((x,i)=>`<div class="activity-row"><div><strong>Held sale ${i+1}</strong><small>${new Date(x.at).toLocaleString()} · ${(x.items||[]).length} lines</small></div><button class="admin-action" onclick="resumeHeld(${i})">Recall</button></div>`).join('')||'<div class="muted">No held sales on this till.</div>'};
window.searchCatalogue=async function(){const q=$('#catalogueSearch')?.value.trim()||'';const rows=await searchText(q);const el=$('#catalogueResults');if(el)el.innerHTML=(rows||[]).map(productButton).join('')||'<div class="pos-empty">No matching product.</div>'};
function renderOfflineQueueBadge(){idbAll('queue').then(rows=>{const el=$('#offlineQueueCount');if(el)el.textContent=rows.length?`${rows.length} queued`:''})};
function renderHeld(){window.renderHeld()}
function setupViews(){document.querySelectorAll('.agent-nav-link').forEach(btn=>btn.addEventListener('click',()=>{const view=btn.dataset.view;document.querySelectorAll('.agent-nav-link').forEach(b=>b.classList.toggle('active',b===btn));document.querySelectorAll('.agent-view').forEach(p=>p.classList.toggle('active',p.dataset.panel===view));const title=$('#agentTitle');if(title)title.textContent=VIEW_TITLES[view]||'Merchant Point';if(view==='held')renderHeld();if(view==='summary')loadDaySummary();if(view==='orders')loadOrders();if(view==='catalogue')searchCatalogue();}));}
let scanBuffer='',scanTimer=null;
function handleKeyboardScanner(e){
  const active=document.activeElement;const typing=['INPUT','TEXTAREA'].includes(active?.tagName);
  if(typing)return;
  if(/^\d$/.test(e.key)){scanBuffer+=e.key;clearTimeout(scanTimer);scanTimer=setTimeout(()=>{scanBuffer=''},180);return}
  if(e.key==='Enter'&&scanBuffer.length>=6){const code=scanBuffer;scanBuffer='';e.preventDefault();$('#posSearch').value=code;searchPOS();return}
  if(e.key==='Enter'&&scanBuffer){scanBuffer='';}
}
window.addEventListener('keydown',handleKeyboardScanner);
$('#posSearch')?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();searchPOS()}});
function refreshSessionChrome(){const el=$('#posSessionClock');if(el){const d=new Date();el.textContent=d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}const status=$('#networkStatus');if(status){status.textContent=navigator.onLine?'ONLINE':'OFFLINE';status.style.opacity=navigator.onLine?'1':'.65'}}
window.addEventListener('online',refreshSessionChrome);window.addEventListener('offline',refreshSessionChrome);setInterval(refreshSessionChrome,30000);refreshSessionChrome();setupViews();renderCart();renderHeld();warmCache();if(navigator.onLine){syncOffline();refreshMpesaFeed();}setInterval(refreshMpesaFeed,3000);renderOfflineQueueBadge();
