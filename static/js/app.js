(function(){
  const splash=document.getElementById('splash');
  if(splash){ setTimeout(()=>splash.classList.add('hidden'),950); }
  const top=document.getElementById('topbar'); let last=window.scrollY;
  window.addEventListener('scroll',()=>{const y=window.scrollY; if(y>80&&y>last+8) top?.classList.add('hide'); else if(y<last-5) top?.classList.remove('hide'); last=y;},{passive:true});
  const menuBtn=document.getElementById('menuBtn'), mobile=document.getElementById('mobileMenu');
  menuBtn?.addEventListener('click',()=>mobile?.classList.toggle('open'));
  document.querySelectorAll('.mobile-menu a').forEach(a=>a.addEventListener('click',()=>mobile?.classList.remove('open')));
  setTimeout(()=>document.querySelectorAll('.toast').forEach(t=>t.remove()),4200);
})();
