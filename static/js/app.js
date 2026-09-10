function shareUrl(url){ if(navigator.share){ navigator.share({title:document.title,url}).catch(()=>{}); } else if(navigator.clipboard){ navigator.clipboard.writeText(url).then(()=>alert('Link copied.')); } else { prompt('Copy this link',url); } }
document.addEventListener('DOMContentLoaded',()=>{ const top=document.querySelector('.top'); let last=window.scrollY; window.addEventListener('scroll',()=>{ if(!top) return; const now=window.scrollY; top.classList.toggle('minimize', now>last && now>120); last=now; },{passive:true}); });function filterQuickChoices(term){
  const q=(term||'').toLowerCase().trim();
  document.querySelectorAll('#quickFilters a').forEach(a=>{a.style.display=!q||a.dataset.filterLabel.includes(q)?'inline-flex':'none'});
}
