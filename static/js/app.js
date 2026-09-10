(function(){
  const splash=document.getElementById('splash'); if(splash) setTimeout(()=>splash.classList.add('hidden'),1000);
  const top=document.getElementById('topbar'); let last=window.scrollY;
  window.addEventListener('scroll',()=>{const y=window.scrollY;if(y>85&&y>last+8)top?.classList.add('hide');else if(y<last-5)top?.classList.remove('hide');last=y},{passive:true});
  const menu=document.getElementById('mobileMenu'), btn=document.getElementById('menuBtn'); btn?.addEventListener('click',()=>menu?.classList.toggle('open')); document.querySelectorAll('.mobile-menu a').forEach(a=>a.addEventListener('click',()=>menu?.classList.remove('open')));
  document.querySelectorAll('.toast').forEach(t=>setTimeout(()=>t.remove(),4500));
  // QR camera entry. Uses BarcodeDetector when the browser exposes it; physical QR links still work without this page.
  const video=document.getElementById('scanner');
  if(video && 'BarcodeDetector' in window && navigator.mediaDevices?.getUserMedia){
    const detector=new BarcodeDetector({formats:['qr_code']});
    navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}}}).then(stream=>{
      video.srcObject=stream;
      const tick=async()=>{try{const codes=await detector.detect(video);if(codes.length&&codes[0].rawValue){location.href=codes[0].rawValue;return}}catch(e){}requestAnimationFrame(tick)};tick();
    }).catch(()=>{});
  }
})();
