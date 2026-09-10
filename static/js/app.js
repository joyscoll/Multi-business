document.addEventListener('DOMContentLoaded',()=>{const flashes=document.querySelectorAll('.flash');flashes.forEach((el,i)=>setTimeout(()=>el.remove(),4200+i*250));});
