const API = '/api/search';
const grid = document.querySelector('#artGrid');
const statusEl = document.querySelector('#status');
const canvas = document.querySelector('#preview');
const ctx = canvas.getContext('2d');
const frame = document.querySelector('.preview-mat');
const art = { items: [], selected: null, image: null, page: 1, query: '', orientation: 'landscape', x: 50, y: 50, zoom: 100, saved: JSON.parse(localStorage.getItem('stillroom-saved-v2') || '[]'), crops: JSON.parse(localStorage.getItem('stillroom-crops-v1') || '{}'), checked: new Set(), searchId: 0, selectionId: 0, loading: false, hasMore: true, allHasMore: true, sourceHasMore: {} };
const tv = { paired: false, available: false, ip: null, busy: false };
const tvLibrary = { page: 0, hasMore: false, loading: false, items: [], selected: new Set() };
let collections=[];
let activeCollection=null;
const importedWorks=[];
const importedCrops={};
let importRequest=0;
const RESULTS_PER_BATCH = 24;
const imgSrc = (item, size='web') => {
  if(item?.source==='local')return item.localUrl;
  const source=item?.images?.[size]?.url;
  return source ? `/image?src=${encodeURIComponent(source)}` : '';
};
async function importImage(file){
  if(!file)return;
  const request=++importRequest;
  const status=document.querySelector('#importImageStatus');
  const report=(message,error=false)=>{status.textContent=message;status.classList.toggle('error',error)};
  let url;
  try{
    if(file.size>30*1024*1024)throw new Error('Choose an image smaller than 30 MB.');
    const header=new Uint8Array(await file.slice(0,8).arrayBuffer());
    const jpeg=header[0]===0xff&&header[1]===0xd8&&header[2]===0xff;
    const png=[137,80,78,71,13,10,26,10].every((byte,index)=>header[index]===byte);
    if(!jpeg&&!png)throw new Error('Choose a JPEG or PNG image. HEIC and other formats must be converted first.');
    if(request!==importRequest)return;
    report('Opening your image…');
    url=URL.createObjectURL(file);
    let image;
    try{image=await loadImage(url)}catch{throw new Error('This image could not be opened. Try another JPEG or PNG.');}
    if(request!==importRequest){URL.revokeObjectURL(url);return}
    if(!image.width||!image.height)throw new Error('This image has no usable dimensions.');
    const item={id:`local-${Date.now()}-${request}`,source:'local',localUrl:url,
      title:file.name.replace(/\.[^.]+$/,'')||'Your image',artistDisplayName:'Your image'};
    importedWorks.push(item);
    chooseCollection('imports',false);
    select(item,grid.lastElementChild);
    report(`${file.name} · ${image.width} × ${image.height}. Available until this page is refreshed.`);
    url=null; // Keep the URL alive for this session's imported collection.
  }catch(error){
    if(url)URL.revokeObjectURL(url);
    if(request===importRequest)report(error.message,true);
  }
}
function setStatus(text){statusEl.textContent=text}
function setTvStatus(message,error=false){const el=document.querySelector('#tvStatus');el.textContent=message;el.classList.toggle('error',error)}
function syncTvButton(){
  document.querySelector('#enlargePreviewBtn').disabled=!art.image;
  const ready=tv.paired&&tv.available&&!tv.busy&&!tvLibrary.loading&&document.querySelector('#tvIp').value.trim()===tv.ip;
  document.querySelector('#sendBtn').disabled=!art.image||!ready;
  document.querySelector('#sendCollectionBtn').disabled=!ready||!activeCollection||activeCollection.works.length<2;
}
function renderSavedCount(){document.querySelector('#savedCount').textContent=art.saved.length}
function visibleItems(){
  const source=document.querySelector('#sourceFilter').value;
  return source==='all' ? art.items : art.items.filter(item=>item.source===source);
}
function redrawGrid(){grid.innerHTML='';drawGrid(visibleItems())}

function thumbnailLoads(item){
  return new Promise(resolve=>{
    const image=new Image();
    const finish=ok=>{image.onload=null;image.onerror=null;resolve(ok)};
    image.onload=()=>finish(true);image.onerror=()=>finish(false);
    image.src=imgSrc(item);
  });
}

async function verifyCandidates(candidates,searchId,needed){
  const accepted=[];let index=0,checked=0;
  const enough=()=>{
    const source=document.querySelector('#sourceFilter').value;
    return accepted.filter(item=>source==='all'||item.source===source).length>=needed;
  };
  const worker=async()=>{
    while(index<candidates.length&&!enough()){
      const item=candidates[index++];
      if(searchId!==art.searchId)return;
      if(art.checked.has(item.id)||art.items.some(existing=>existing.id===item.id))continue;
      art.checked.add(item.id);
      if(await thumbnailLoads(item))accepted.push(item);
      checked++;
      setStatus(`Checking artwork previews… ${accepted.length}/${needed} loaded (${checked} checked)`);
    }
  };
  await Promise.all(Array.from({length:Math.min(6,candidates.length)},worker));
  return accepted;
}

async function search(reset=true){
  if(art.loading&&!reset)return;
  if(reset){activeCollection=null;document.querySelector('#collectionActions').hidden=true;document.querySelectorAll('.collection-card').forEach(card=>card.classList.remove('active'));art.searchId++;art.page=1;art.items=[];art.checked.clear();art.hasMore=true;art.allHasMore=true;art.sourceHasMore={};grid.innerHTML='';syncTvButton()}
  const searchId=art.searchId;
  art.loading=true;
  const loadMoreButton=document.querySelector('#loadMore');loadMoreButton.disabled=true;loadMoreButton.hidden=true;
  const startCount=visibleItems().length;
  const targetCount=startCount+RESULTS_PER_BATCH;
  document.querySelector('#collectionTitle').textContent=art.query ? `Works for “${art.query}”` : 'Open a window';
  try{
    while(searchId===art.searchId&&art.hasMore&&visibleItems().length<targetCount){
      setStatus(`Finding artworks with working previews… ${visibleItems().length}/${targetCount}`);
      const params = new URLSearchParams({q:art.query,page:art.page,source:'all'});
      const response=await fetch(`${API}?${params}`);
      if(!response.ok) throw new Error('The collection could not be reached.');
      const data=await response.json();
      // A previous query can finish after the user starts a new one. Do not
      // let its late response advance the new query's page cursor or hasMore.
      if(searchId!==art.searchId)return;
      art.page++;
      art.allHasMore=Boolean(data.info?.hasMore);
      art.sourceHasMore=Object.fromEntries(Object.entries(data.sourceInfo||{}).map(([name,info])=>[name,Boolean(info.hasMore)]));
      const selectedSource=document.querySelector('#sourceFilter').value;
      art.hasMore=selectedSource==='all'?art.allHasMore:Boolean(art.sourceHasMore[selectedSource]);
      const candidates=data.data.filter(x=>x.images?.web?.url && x.images?.print?.url);
      const verified=await verifyCandidates(candidates,searchId,Math.max(1,targetCount-visibleItems().length));
      if(searchId!==art.searchId)return;
      art.items.push(...verified);
      redrawGrid();
    }
    const shown=visibleItems();
    if(shown.length) setStatus('Open-access flat artworks with working previews');
    else {
      const query=art.query.trim();
      const isKandinsky=/kandinsky/i.test(query);
      setStatus(isKandinsky
        ? 'No Kandinsky works with working previews were found. Try another search.'
        : `No open-access flat artworks with working previews found${query ? ` for “${query}”` : ''}. Try another search.`);
    }
    loadMoreButton.hidden=!art.hasMore;loadMoreButton.disabled=false;
  }catch(error){
    if(searchId===art.searchId){setStatus('The collection could not load. Check your connection and try again.');loadMoreButton.hidden=!art.hasMore;loadMoreButton.disabled=false}
  }finally{
    if(searchId===art.searchId)art.loading=false;
  }
}

function drawGrid(items){
  for(const item of items){
    const button=document.createElement('button');button.className='art-card';button.type='button';button.dataset.id=item.id;
    const wrap=document.createElement('div');wrap.className='art-image-wrap';
    const image=document.createElement('img');image.loading='lazy';image.alt=item.title;image.src=imgSrc(item);
    let triedOriginal=false;
    image.onerror=()=>{
      if(item.source!=='commons'&&!triedOriginal&&item.images?.print?.url!==item.images?.web?.url){triedOriginal=true;image.src=imgSrc(item,'print');return}
      image.remove();wrap.classList.add('image-unavailable');wrap.textContent='Image unavailable'
    };
    wrap.append(image);
    const title=document.createElement('b');title.textContent=item.title || 'Untitled';
    const by=document.createElement('small');by.textContent=item.artistDisplayName||'Artist unknown';
    button.append(wrap,title,by);button.addEventListener('click',()=>select(item,button));grid.append(button);
  }
}

async function select(item,button){
  document.querySelectorAll('.art-card').forEach(n=>n.classList.toggle('selected',n===button));
  const selectionId=++art.selectionId;
  const savedCrop=(item.source==='local'?importedCrops[item.id]:art.crops[item.id])||{};
  art.selected=item;art.image=null;art.x=savedCrop.x??50;art.y=savedCrop.y??50;art.zoom=savedCrop.zoom??(activeCollection&&item.source!=='local'?104:100);
  document.querySelector('#posX').value=art.x;document.querySelector('#posY').value=art.y;
  document.querySelector('#zoom').value=art.zoom;document.querySelector('#zoomValue').textContent=`${art.zoom}%`;document.querySelector('#emptyPreview').hidden=true;
  document.querySelector('#selectedTitle').textContent=item.title || 'Untitled';
  const attribution=document.querySelector('#selectedArtist');
  attribution.textContent=[item.artistDisplayName,item.objectDate].filter(Boolean).join(' · ');
  if(item.objectURL){attribution.append(' · ');const source=document.createElement('a');source.href=item.objectURL;source.target='_blank';source.rel='noreferrer';source.textContent=item.museum;source.style.color='inherit';attribution.append(source)}
  document.querySelector('#downloadBtn').disabled=true;document.querySelector('#saveButton').disabled=false;syncSaveButton();syncTvButton();
  setStatus('');
  const image=new Image();image.crossOrigin='anonymous';
  image.onload=()=>{if(selectionId!==art.selectionId)return;art.image=image;drawPreview();document.querySelector('#downloadBtn').disabled=false;syncTvButton()};
  const imageSizes=item.source==='commons'?['web']:['print','web'];
  const tryImageSize=index=>{
    if(selectionId!==art.selectionId)return;
    if(index>=imageSizes.length){
      document.querySelector('#emptyPreview').hidden=false;
      document.querySelector('#emptyPreview').innerHTML='<b>Image could not load</b><small>Check your connection or try another work.</small>';
      return;
    }
    image.onerror=()=>tryImageSize(index+1);
    image.src=imgSrc(item,imageSizes[index]);
  };
  tryImageSize(0);
}

function cropRect(image,W,H,x,y,zoom){
  const scale=Math.max(W/image.width,H/image.height)*(zoom/100),sw=W/scale,sh=H/scale;
  return {sx:(image.width-sw)*(x/100),sy:(image.height-sh)*(y/100),sw,sh};
}

function drawPreview(){
  if(!art.image)return;
  const portrait=art.orientation==='portrait';const large=document.querySelector('#previewDialog').open;
  const W=(portrait?540:960)*(large?2:1),H=(portrait?960:540)*(large?2:1);
  canvas.width=W;canvas.height=H;frame.style.aspectRatio=portrait?'9/16':'16/9';
  if(large)fitEnlargedPreview();
  const crop=cropRect(art.image,W,H,art.x,art.y,art.zoom);
  const xControl=document.querySelector('#posX'),yControl=document.querySelector('#posY');
  const canMoveX=art.image.width-crop.sw>0.5,canMoveY=art.image.height-crop.sh>0.5;
  xControl.disabled=!canMoveX;yControl.disabled=!canMoveY;
  xControl.title=canMoveX?'Move the crop left or right':'This image has no horizontal crop to adjust';
  yControl.title=canMoveY?'Move the crop up or down':'This image has no vertical crop to adjust';
  xControl.parentElement.classList.toggle('inactive-crop',!canMoveX);
  yControl.parentElement.classList.toggle('inactive-crop',!canMoveY);
  ctx.clearRect(0,0,W,H);
  ctx.fillStyle='#fff';ctx.fillRect(0,0,W,H);
  ctx.drawImage(art.image,crop.sx,crop.sy,crop.sw,crop.sh,0,0,W,H);
}

function loadImage(src){return new Promise((resolve,reject)=>{
  const image=new Image();
  const timer=setTimeout(()=>{image.onload=null;image.onerror=null;image.src='';reject(new Error('Image took too long to load'))},35000);
  image.onload=()=>{clearTimeout(timer);resolve(image)};
  image.onerror=()=>{clearTimeout(timer);reject(new Error('Image could not load'))};
  image.src=src;
})}

async function exportBlob(){
  if(!art.image||!art.selected)throw new Error('Select an artwork first.');
  const selected=art.selected,orientation=art.orientation,x=art.x,y=art.y,zoom=art.zoom;
  let exportImage=art.image;
  if(selected.source==='commons'){
    setTvStatus('Preparing the full-resolution image…');
    try{exportImage=await loadImage(imgSrc(selected,'print'))}
    catch{setTvStatus('Original unavailable; using the preview image.')}
  }
  const out=document.createElement('canvas');out.width=orientation==='portrait'?2160:3840;out.height=orientation==='portrait'?3840:2160;
  const outCtx=out.getContext('2d'),crop=cropRect(exportImage,out.width,out.height,x,y,zoom);
  outCtx.fillStyle='#fff';outCtx.fillRect(0,0,out.width,out.height);
  outCtx.drawImage(exportImage,crop.sx,crop.sy,crop.sw,crop.sh,0,0,out.width,out.height);
  const blob=await new Promise(resolve=>out.toBlob(resolve,'image/jpeg',.94));
  if(!blob)throw new Error('This image could not be exported. Try another work.');
  return {blob,title:selected.title};
}

async function download(){
  try{
    const {blob,title}=await exportBlob();
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;
    link.download=`stillroom-${(title||'artwork').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,48)}.jpg`;
    link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){setTvStatus(error.message,true)}
}

async function tvRequest(path,options){
  const response=await fetch(path,options);
  let result={};try{result=await response.json()}catch{}
  if(!response.ok)throw new Error(result.error||'The TV request failed.');
  return result;
}

function tvLibraryReady(){return tv.paired&&tv.available&&document.querySelector('#tvIp').value.trim()===tv.ip}
function syncTvLibraryControls(){
  document.querySelector('#refreshTvPhotos').disabled=!tvLibraryReady()||tvLibrary.loading||tv.busy;
  document.querySelector('#loadMoreTvPhotos').disabled=!tvLibraryReady()||tvLibrary.loading||tv.busy;
  document.querySelector('#deleteTvPhotos').disabled=!tvLibraryReady()||tvLibrary.loading||tv.busy||!tvLibrary.selected.size;
}
function setTvPhotoStatus(message,error=false){const el=document.querySelector('#tvPhotoStatus');el.textContent=message;el.classList.toggle('error',error)}
function updateTvPhotoSelection(){
  const count=tvLibrary.selected.size;
  document.querySelector('#tvPhotoSelectedCount').textContent=`${count} selected`;
  document.querySelector('#tvPhotoToolbar').hidden=!tvLibrary.items.length;
  syncTvLibraryControls();
}
function appendTvPhotos(items){
  const grid=document.querySelector('#tvPhotoGrid');
  for(const item of items){
    if(tvLibrary.items.some(existing=>existing.id===item.id))continue;
    tvLibrary.items.push(item);
    const card=document.createElement('div');card.className='tv-photo-card';
    const label=document.createElement('label');
    const thumb=document.createElement('div');thumb.className='tv-photo-thumb';
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.value=item.id;checkbox.setAttribute('aria-label',`Select TV photo ${item.id} for deletion`);
    checkbox.addEventListener('change',()=>{if(checkbox.checked)tvLibrary.selected.add(item.id);else tvLibrary.selected.delete(item.id);updateTvPhotoSelection()});
    thumb.append(checkbox);
    if(item.thumbnail){const image=document.createElement('img');image.src=item.thumbnail;image.alt=`TV photo ${item.id}`;thumb.append(image)}
    else{const missing=document.createElement('span');missing.className='unavailable';missing.textContent='Preview unavailable';thumb.append(missing)}
    if(item.current){const badge=document.createElement('span');badge.className='current-tag';badge.textContent='On display';thumb.append(badge)}
    const copy=document.createElement('div');copy.className='tv-photo-copy';
    const name=document.createElement('b');name.textContent=item.current?'Currently displayed':'Uploaded photo';
    const detail=document.createElement('small');detail.textContent=[item.width&&item.height?`${item.width} × ${item.height}`:null,item.id].filter(Boolean).join(' · ');
    copy.append(name,detail);label.append(thumb,copy);card.append(label);grid.append(card);
  }
  updateTvPhotoSelection();
}
async function refreshTvPhotos(reset=true){
  if(!tvLibraryReady()){setTvPhotoStatus('Pair your Frame TV to see its photos.');syncTvLibraryControls();return}
  if(tvLibrary.loading)return;
  tvLibrary.loading=true;syncTvLibraryControls();syncTvButton();
  const page=reset?1:tvLibrary.page+1;
  const pairedIp=tv.ip;
  if(reset){tvLibrary.items=[];tvLibrary.selected.clear();document.querySelector('#tvPhotoGrid').innerHTML='';updateTvPhotoSelection()}
  setTvPhotoStatus('Reading My Photos from your Frame TV…');
  try{
    const result=await tvRequest(`/api/tv/photos?page=${page}`);
    if(tv.ip!==pairedIp||document.querySelector('#tvIp').value.trim()!==pairedIp)return;
    tvLibrary.page=page;tvLibrary.hasMore=result.hasMore;
    appendTvPhotos(result.items||[]);
    document.querySelector('#loadMoreTvPhotos').hidden=!result.hasMore;
    setTvPhotoStatus(result.total?`${result.total} ${result.total===1?'photo':'photos'} in My Photos on your Frame TV.`:'No photos in My Photos on this TV yet.');
  }catch(error){setTvPhotoStatus(error.message,true)}
  finally{tvLibrary.loading=false;syncTvLibraryControls();syncTvButton()}
}
function openDeleteTvDialog(){
  if(!tvLibrary.selected.size||!tvLibraryReady())return;
  const count=tvLibrary.selected.size;
  const current=tvLibrary.items.some(item=>item.current&&tvLibrary.selected.has(item.id));
  document.querySelector('#deleteTvDialogCopy').textContent=`${count} ${count===1?'photo':'photos'} will be removed from this TV’s My Photos. This does not remove your saved works in Stillroom.${current?' The image currently on display is selected, so the TV may change what it shows.':''}`;
  document.querySelector('#confirmDeleteTv').textContent=`Delete ${count} from TV`;
  document.querySelector('#deleteTvDialog').showModal();
}
async function confirmDeleteTvPhotos(){
  const ids=[...tvLibrary.selected];if(!ids.length)return;
  const button=document.querySelector('#confirmDeleteTv');button.disabled=true;
  try{
    const result=await tvRequest('/api/tv/photos/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contentIds:ids})});
    document.querySelector('#deleteTvDialog').close();
    await refreshTvPhotos();
    const deleted=result.deletedIds?.length||0,remaining=result.notDeletedIds?.length||0;
    setTvPhotoStatus(`${deleted} ${deleted===1?'photo':'photos'} deleted from the TV.${remaining?` ${remaining} could not be confirmed; refresh and try again.`:''}${result.slideshowStopped?' The slideshow stopped because it included a deleted photo.':''}`,remaining>0);
    if(result.slideshowStopped)await loadSlideshowStatus();
  }catch(error){document.querySelector('#deleteTvDialog').close();setTvPhotoStatus(error.message,true)}
  finally{button.disabled=false}
}

async function loadTvStatus(){
  try{
    const result=await tvRequest('/api/tv/status');
    tv.paired=result.paired;tv.available=result.available;tv.ip=result.ip;
    if(result.ip)document.querySelector('#tvIp').value=result.ip;
    setTvStatus(!result.available?'Install the optional TV package to enable direct transfer.':result.paired?`Paired with ${result.ip}. Ready to send artwork.`:'Enter your TV address to pair.');
    if(!result.available)setTvPhotoStatus('Install the optional TV package to read My Photos.');
    else if(!result.paired)setTvPhotoStatus('Pair your Frame TV to see its photos.');
    if(result.paired&&result.available)await refreshTvPhotos();
  }catch{setTvStatus('Could not check the TV connection. Refresh the page.',true)}
  syncTvButton();syncTvLibraryControls();
}

async function pairTv(){
  const ip=document.querySelector('#tvIp').value.trim();
  if(!ip){setTvStatus('Enter the TV’s IP address first.',true);return}
  const button=document.querySelector('#pairBtn');button.disabled=true;tv.busy=true;syncTvButton();
  setTvStatus('Connecting… accept the Stillroom prompt on your TV.');
  try{
    const result=await tvRequest('/api/tv/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip})});
    tv.paired=result.paired;tv.available=result.available;tv.ip=result.ip;setTvStatus(`Paired with ${result.ip}. Ready to send artwork.`);await refreshTvPhotos();
  }catch(error){setTvStatus(error.message,true)}
  finally{button.disabled=false;tv.busy=false;syncTvButton();syncTvLibraryControls()}
}

async function sendToTv(){
  if(!tv.paired||!art.image||tv.busy)return;
  tv.busy=true;syncTvButton();setTvStatus('Preparing artwork…');
  try{
    const {blob}=await exportBlob();
    setTvStatus('Sending artwork to your Frame TV…');
    const result=await tvRequest('/api/tv/upload',{method:'POST',headers:{'Content-Type':'image/jpeg'},body:blob});
    setTvStatus(result.message||'Artwork uploaded to your TV.');
    await refreshTvPhotos();
  }catch(error){setTvStatus(error.message,true)}
  finally{tv.busy=false;syncTvButton()}
}

function isSaved(id){return art.saved.some(x=>x.id===id)}
function syncSaveButton(){const b=document.querySelector('#saveButton');b.textContent=isSaved(art.selected?.id)?'♥':'♡';b.classList.toggle('saved',isSaved(art.selected?.id));b.disabled=!art.selected||art.selected.source==='local';b.title=art.selected?.source==='local'?'Imported images are available in this tab until the page is refreshed.':'Save artwork'}
function saveSelected(){if(!art.selected||art.selected.source==='local')return;if(isSaved(art.selected.id))art.saved=art.saved.filter(x=>x.id!==art.selected.id);else art.saved.unshift(art.selected);localStorage.setItem('stillroom-saved-v2',JSON.stringify(art.saved));renderSavedCount();syncSaveButton();renderCollections();if(activeCollection?.id==='saved')chooseCollection('saved')}
function saveCrop(){if(!art.selected)return;const crop={x:art.x,y:art.y,zoom:art.zoom};if(art.selected.source==='local'){importedCrops[art.selected.id]=crop;return}art.crops[art.selected.id]=crop;localStorage.setItem('stillroom-crops-v1',JSON.stringify(art.crops))}

function allCollections(){return [...collections,...(importedWorks.length?[{id:'imports',title:'Your uploaded images',description:'Images opened in this browser tab. Refreshing the page clears this collection. Download or send them to your TV to keep a copy.',works:importedWorks}]:[]),{id:'saved',title:'Your saved works',description:'A personal set made from your saved artworks.',works:art.saved}]}
function renderCollections(){
  const container=document.querySelector('#collectionCards');container.innerHTML='';
  for(const collection of allCollections()){
    const card=document.createElement('button');card.type='button';card.className='collection-card';card.classList.toggle('active',activeCollection?.id===collection.id);
    const cover=collection.works[0];
    if(cover){const img=document.createElement('img');img.src=imgSrc(cover);img.alt='';img.loading='lazy';card.append(img)}
    else{const coverEl=document.createElement('span');coverEl.className='saved-art-cover';coverEl.textContent='♡';card.append(coverEl)}
    const copy=document.createElement('span');copy.className='collection-card-copy';
    const title=document.createElement('b');title.textContent=collection.title;
    const count=document.createElement('small');count.textContent=`${collection.works.length} ${collection.works.length===1?'work':'works'}`;
    copy.append(title,count);card.append(copy);card.addEventListener('click',()=>chooseCollection(collection.id));container.append(card);
  }
}
async function loadCollections(){
  try{
    const response=await fetch('/api/collections');if(!response.ok)throw new Error();
    const data=await response.json();collections=data.collections||[];renderCollections();
  }catch{document.querySelector('#collectionCards').textContent='Curated collections could not load. Refresh the page.'}
}
function chooseCollection(id,scroll=true){
  const collection=allCollections().find(entry=>entry.id===id);if(!collection)return;
  activeCollection=collection;art.searchId++;art.loading=false;art.hasMore=false;art.items=collection.works.slice();
  art.orientation='landscape';document.querySelectorAll('.orientation').forEach(button=>button.classList.toggle('active',button.dataset.orientation==='landscape'));
  document.querySelector('#sourceFilter').value='all';grid.innerHTML='';drawGrid(art.items);
  if(art.items.length)select(art.items[0],grid.querySelector('.art-card'));
  else{art.selectionId++;art.selected=null;art.image=null;const empty=document.querySelector('#emptyPreview');empty.innerHTML='<span>✳</span><b>Your next favorite<br />starts here.</b><small>Save a work to build your collection</small>';empty.hidden=false;document.querySelector('#selectedTitle').textContent='Choose a painting';document.querySelector('#selectedArtist').textContent='Your preview will appear here.';document.querySelector('#saveButton').disabled=true;document.querySelector('#downloadBtn').disabled=true}
  document.querySelector('#collectionTitle').textContent=collection.title;
  document.querySelector('#collectionDescription').textContent=collection.description;
  document.querySelector('#collectionActions').hidden=false;
  document.querySelector('#loadMore').hidden=true;
  document.querySelector('#collectionStatus').textContent=collection.works.length<2?(id==='imports'?'Upload at least two images to start a slideshow.':'Save at least two artworks to start a slideshow.'):'';
  document.querySelector('.collection-note').textContent=id==='imports'?'Each image uses its landscape crop. Stillroom rotates this set while the server is running.':'Each work is cropped to 16:9 with a small edge trim. Stillroom rotates this exact set while the server is running.';
  setStatus(`${collection.works.length} ${id==='imports'?'uploaded':'curated'} ${collection.works.length===1?'work':'works'}`);
  renderCollections();syncTvButton();
  if(scroll)document.querySelector('.gallery-panel').scrollIntoView({behavior:'smooth',block:'start'});
}
function setCollectionStatus(message,error=false){const el=document.querySelector('#collectionStatus');el.textContent=message;el.classList.toggle('error',error)}
async function exportCollectionItem(item){
  let image;
  try{image=await loadImage(imgSrc(item,'print'))}
  catch{image=await loadImage(imgSrc(item,'web'))}
  const out=document.createElement('canvas');out.width=3840;out.height=2160;
  const crop=(item.source==='local'?importedCrops[item.id]:art.crops[item.id])||{x:50,y:50,zoom:item.source==='local'?100:104};
  const rect=cropRect(image,3840,2160,crop.x,crop.y,crop.zoom);
  out.getContext('2d').fillStyle='#fff';out.getContext('2d').fillRect(0,0,out.width,out.height);
  out.getContext('2d').drawImage(image,rect.sx,rect.sy,rect.sw,rect.sh,0,0,3840,2160);
  const blob=await new Promise(resolve=>out.toBlob(resolve,'image/jpeg',.94));
  if(!blob)throw new Error('The artwork could not be exported.');
  return blob;
}
async function sendCollection(){
  if(!activeCollection||!tv.paired||tv.busy||document.querySelector('#tvIp').value.trim()!==tv.ip)return;
  const collection=activeCollection;
  tv.busy=true;syncTvButton();
  const contentIds=[];const failed=[];
  try{
    await tvRequest('/api/tv/slideshow/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    await loadSlideshowStatus();
    for(let index=0;index<collection.works.length;index++){
      const item=collection.works[index];
      setCollectionStatus(`Preparing ${index+1} of ${collection.works.length}: ${item.title}…`);
      try{
        const blob=await exportCollectionItem(item);
        setCollectionStatus(`Sending ${index+1} of ${collection.works.length}: ${item.title}…`);
        const result=await tvRequest('/api/tv/upload?select=0',{method:'POST',headers:{'Content-Type':'image/jpeg'},body:blob});
        if(!result.contentId)throw new Error('The TV did not return an artwork ID.');
        contentIds.push(result.contentId);
      }catch(error){failed.push(`${item.title}: ${error.message}`)}
    }
    if(contentIds.length<2)throw new Error(`Only ${contentIds.length} work${contentIds.length===1?'':'s'} sent. A slideshow needs at least two. ${failed[0]||''}`);
    setCollectionStatus(`Starting slideshow with ${contentIds.length} works…`);
    const intervalMinutes=Number(document.querySelector('#slideInterval').value);
    await tvRequest('/api/tv/slideshow/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contentIds,intervalMinutes})});
    setCollectionStatus(`${contentIds.length} works sent. Slideshow started.${failed.length?` ${failed.length} could not be sent.`:''}`,failed.length>0);
    await loadSlideshowStatus();
  }catch(error){setCollectionStatus(error.message,true)}
  finally{tv.busy=false;syncTvButton();if(contentIds.length)await refreshTvPhotos()}
}
async function loadSlideshowStatus(){
  try{
    const state=await tvRequest('/api/tv/slideshow/status');
    const banner=document.querySelector('#slideshowBanner');banner.hidden=!state.active;
    if(state.active)document.querySelector('#slideshowBannerText').textContent=`Slideshow running · ${state.count} works · every ${state.intervalMinutes} min${state.lastError?' · TV connection needs attention':''}`;
  }catch{}
}
async function stopCollectionSlideshow(){
  const button=document.querySelector('#stopSlideshowBtn');button.disabled=true;
  try{
    await tvRequest('/api/tv/slideshow/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    setCollectionStatus('Slideshow stopped. The current artwork remains on the TV.');
    await loadSlideshowStatus();
  }catch(error){setCollectionStatus(error.message,true)}
  finally{button.disabled=false}
}

// Move the existing preview and controls so both views share one composition.
const previewDialog=document.querySelector('#previewDialog');
const previewStage=document.querySelector('#previewDialogStage');
const previewControls=document.querySelector('#previewDialogControls');
const previewParts=['.preview-wrap','.bezel-choice','.controls'].map(selector=>{
  const node=document.querySelector(selector),placeholder=document.createComment('preview home');
  node.before(placeholder);
  return {node,placeholder};
});
function fitEnlargedPreview(){
  if(!previewDialog.open)return;
  const bezel=document.querySelector('#tvBezel');
  const style=getComputedStyle(bezel);
  const horizontal=parseFloat(style.paddingLeft)+parseFloat(style.paddingRight);
  const vertical=parseFloat(style.paddingTop)+parseFloat(style.paddingBottom);
  const stageStyle=getComputedStyle(previewParts[0].node);
  const width=previewStage.clientWidth-parseFloat(stageStyle.paddingLeft)-parseFloat(stageStyle.paddingRight);
  const height=previewStage.clientHeight-parseFloat(stageStyle.paddingTop)-parseFloat(stageStyle.paddingBottom);
  const ratio=art.orientation==='portrait'?9/16:16/9;
  bezel.style.width=`${Math.max(0,Math.min(width,(height-vertical)*ratio+horizontal))}px`;
}
function enlargePreview(){
  if(!art.image||previewDialog.open)return;
  document.querySelector('#previewDialogArtwork').textContent=art.selected?.title||'Your artwork';
  previewStage.append(previewParts[0].node);
  previewControls.append(previewParts[1].node,previewParts[2].node);
  previewDialog.showModal();
  document.documentElement.classList.add('preview-dialog-open');
  drawPreview();
}
function restorePreview(){
  for(const {node,placeholder} of previewParts)placeholder.after(node);
  document.querySelector('#tvBezel').style.removeProperty('width');
  document.documentElement.classList.remove('preview-dialog-open');
  drawPreview();
  document.querySelector('#enlargePreviewBtn').focus({preventScroll:true});
}
document.querySelector('#enlargePreviewBtn').addEventListener('click',enlargePreview);
document.querySelector('#closePreviewBtn').addEventListener('click',()=>previewDialog.close());
previewDialog.addEventListener('close',restorePreview);
new ResizeObserver(fitEnlargedPreview).observe(previewStage);

document.querySelector('#importImageFile').addEventListener('change',event=>{const file=event.target.files[0];event.target.value='';importImage(file)});
document.querySelector('#searchForm').addEventListener('submit',e=>{e.preventDefault();art.query=document.querySelector('#searchInput').value.trim();document.querySelectorAll('.chip').forEach(c=>c.classList.remove('active'));search()});
document.querySelector('#sourceFilter').addEventListener('change',()=>{
  redrawGrid();
  const count=visibleItems().length;
  setStatus(`${count} loaded ${count===1?'work':'works'} from this source filter`);
  const selectedSource=document.querySelector('#sourceFilter').value;
  art.hasMore=selectedSource==='all'?art.allHasMore:Boolean(art.sourceHasMore[selectedSource]);
  if(count<RESULTS_PER_BATCH&&art.hasMore&&!art.loading)search(false);
});
document.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>{document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('active',x===c));art.query=c.dataset.query;document.querySelector('#searchInput').value='';search()}));
document.querySelector('#surpriseBtn').addEventListener('click',()=>{const ideas=['impressionist painting','Japanese woodblock print','Dutch still life','seascape painting','wildflower painting','mountain landscape','abstract painting','French art'];art.query=ideas[Math.floor(Math.random()*ideas.length)];document.querySelector('#searchInput').value='';document.querySelectorAll('.chip').forEach(c=>c.classList.remove('active'));search()});
document.querySelector('#loadMore').addEventListener('click',()=>search(false));
document.querySelectorAll('.orientation').forEach(b=>b.addEventListener('click',()=>{art.orientation=b.dataset.orientation;document.querySelectorAll('.orientation').forEach(x=>x.classList.toggle('active',x===b));drawPreview()}));
for(const [id,key] of [['#posX','x'],['#posY','y']])document.querySelector(id).addEventListener('input',e=>{art[key]=Number(e.target.value);saveCrop();drawPreview()});
document.querySelector('#zoom').addEventListener('input',e=>{art.zoom=Number(e.target.value);document.querySelector('#zoomValue').textContent=`${art.zoom}%`;saveCrop();drawPreview()});
document.querySelector('#downloadBtn').addEventListener('click',download);document.querySelector('#saveButton').addEventListener('click',saveSelected);
document.querySelector('#pairBtn').addEventListener('click',pairTv);document.querySelector('#sendBtn').addEventListener('click',sendToTv);
document.querySelector('#tvLibraryJump').addEventListener('click',()=>document.querySelector('#tvLibrary').scrollIntoView({behavior:'smooth'}));
document.querySelector('#refreshTvPhotos').addEventListener('click',()=>refreshTvPhotos());
document.querySelector('#loadMoreTvPhotos').addEventListener('click',()=>refreshTvPhotos(false));
document.querySelector('#deleteTvPhotos').addEventListener('click',openDeleteTvDialog);
document.querySelector('#cancelDeleteTv').addEventListener('click',()=>document.querySelector('#deleteTvDialog').close());
document.querySelector('#confirmDeleteTv').addEventListener('click',confirmDeleteTvPhotos);
document.querySelector('#sendCollectionBtn').addEventListener('click',sendCollection);
document.querySelector('#stopSlideshowBtn').addEventListener('click',stopCollectionSlideshow);
const savedBezel=localStorage.getItem('stillroom-bezel-v1');
if(['black','white','teak','brown','sand-gold'].includes(savedBezel))document.querySelector('#bezelSelect').value=savedBezel;
function updateBezel(){const value=document.querySelector('#bezelSelect').value;document.querySelector('#tvBezel').className=`tv-bezel bezel-${value}`;localStorage.setItem('stillroom-bezel-v1',value);fitEnlargedPreview()}
document.querySelector('#bezelSelect').addEventListener('change',updateBezel);updateBezel();
document.querySelector('#tvIp').addEventListener('input',()=>{
  const matches=document.querySelector('#tvIp').value.trim()===tv.ip;
  if(tv.paired)setTvStatus(matches?`Paired with ${tv.ip}. Ready to send artwork.`:'Pair this TV address before sending artwork.');
  if(!matches){tvLibrary.items=[];tvLibrary.selected.clear();document.querySelector('#tvPhotoGrid').innerHTML='';document.querySelector('#tvPhotoToolbar').hidden=true;setTvPhotoStatus('Pair this TV address to see its photos.')}
  else if(!tvLibrary.items.length)refreshTvPhotos();
  syncTvButton();syncTvLibraryControls();
});
document.querySelector('#transferHelp').addEventListener('click',()=>document.querySelector('#helpDialog').showModal());document.querySelector('#closeDialog').addEventListener('click',()=>document.querySelector('#helpDialog').close());document.querySelector('#savedToggle').addEventListener('click',()=>chooseCollection('saved'));
renderSavedCount();loadCollections();loadTvStatus();loadSlideshowStatus();setInterval(loadSlideshowStatus,30000);search();
