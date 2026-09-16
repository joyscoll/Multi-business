if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/pwa/service-worker.js').catch(console.error);
function getCart(){try{return JSON.parse(localStorage.getItem('rm_cart')||'[]')}catch{return[]}}
function saveCart(c){localStorage.setItem('rm_cart',JSON.stringify(c))}
function addToCart(id,name,price){const c=getCart();const i=c.find(x=>x.id===id);if(i)i.quantity++;else c.push({id,name,price:Number(price),quantity:1});saveCart(c);alert(name+' added to cart.');}
