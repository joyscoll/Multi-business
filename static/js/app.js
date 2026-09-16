if ('serviceWorker' in navigator) {
  const path = window.location.pathname;
  if (path === '/supermarket' || path.startsWith('/supermarket/')) {
    navigator.serviceWorker.register('/supermarket/sw.js', {scope:'/supermarket'}).catch(()=>{});
  }
}
function getCart(){try{return JSON.parse(localStorage.getItem('rm_cart')||'[]')}catch{return[]}}
function saveCart(c){localStorage.setItem('rm_cart',JSON.stringify(c))}
function addToCart(id,name,price){const c=getCart();const i=c.find(x=>x.id===id);if(i)i.quantity++;else c.push({id,name,price:Number(price),quantity:1});saveCart(c);toast(name+' added to your basket.');updateCartCount();}
function updateCartCount(){const n=getCart().reduce((a,x)=>a+x.quantity,0);document.querySelectorAll('[data-cart-count]').forEach(e=>e.textContent=n)}
function toast(message){const t=document.createElement('div');t.className='toast';t.textContent=message;document.body.appendChild(t);setTimeout(()=>t.remove(),2400)}
document.addEventListener('DOMContentLoaded',updateCartCount);
