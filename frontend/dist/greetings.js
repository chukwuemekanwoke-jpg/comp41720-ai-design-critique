// Adapted from the supplied Stitch design; motion pauses for keyboard focus.
(() => {
  const region=document.querySelector('#greeting-region');
  const word=document.querySelector('#greeting');
  const language=document.querySelector('#greeting-language');
  const greetings=[['Dia duit','Gaeilge · Irish','ga'],['Bonjour','Français · French','fr'],['Hello','English','en'],['नमस्ते','हिन्दी · Hindi','hi'],['你好','中文 · Chinese','zh']];
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){word.textContent='Dia duit · Hello';word.lang='ga';language.textContent='Gaeilge · English';return;}
  let index=0,paused=false,pending;
  function show(next){clearTimeout(pending);word.classList.add('fading');pending=setTimeout(()=>{[word.textContent,language.textContent,word.lang]=greetings[next];word.classList.remove('fading');},450);}
  const pause=()=>{paused=true;index=2;show(index);};
  region.addEventListener('mouseenter',pause);region.addEventListener('focus',pause);
  region.addEventListener('mouseleave',()=>{paused=region.matches(':focus');});
  region.addEventListener('blur',()=>{paused=region.matches(':hover');});
  setInterval(()=>{if(!paused&&!document.hidden){index=(index+1)%greetings.length;show(index);}},2800);
})();
