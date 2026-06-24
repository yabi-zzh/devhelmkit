// UIViewer frontend logic
(function(){
"use strict";
var P=new URLSearchParams(window.location.search);
var JP=P.get("jpegPort")||0;
fetch("/api/runtime").then(function(r){return r.json()}).then(function(d){JP=JP||d.jpeg_port}).catch(function(){});
var S={serial:null,mode:"snapshot",h:null,sel:null,hov:null,disp:null,iw:0,ih:0,touch:false,ht:null,lastMove:0,collapsed:{},loading:false,locked:false,fetching:false};
var E={ds:G("deviceSelect"),ml:G("modeLive"),lk:G("lockBtn"),lkIcon:G("lockIcon"),lkLabel:G("lockLabel"),rb:G("refreshBtn"),ct:G("cleanupToggle"),cs:G("closeSessionBtn"),ph:G("placeholder"),sw:G("screenWrapper"),scr:document.querySelector(".phone-screen"),si:G("screenImg"),ov:G("overlay"),tp:G("treePanel"),ap:G("attrsPanel"),sb:G("statusBar"),sd:G("statusDot")};
function G(id){return document.getElementById(id)}
function ag(u){return fetch(u).then(function(r){if(!r.ok)throw new Error(r.status);return r.json()})}
function ap(u,d){return fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)}).then(function(r){if(!r.ok)throw new Error(r.status);return r.json()})}
function ss(m){E.sb.textContent=m;E.sd.className="dot";if(m.indexOf("失败")>=0)E.sd.classList.add("error");else if(m.indexOf("实时")>=0||m.indexOf("live")>=0)E.sd.classList.add("live");else if(m.indexOf("已连接")>=0||m.indexOf("获取完成")>=0||m.indexOf("就绪")>=0||m.indexOf("控件树已更新")>=0)E.sd.classList.add("snapshot")}
function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function setLoading(on){S.loading=on;E.rb.classList.toggle("loading",on);E.rb.disabled=on}
function loadDevices(){ag("/api/devices").then(function(d){var v=d.devices||[];E.ds.innerHTML='';v.forEach(function(s){var o=document.createElement("option");o.value=s;o.textContent=s;E.ds.appendChild(o)});ss(v.length?"检测到"+v.length+"台设备":"未检测到设备");if(v.length===1){E.ds.value=v[0];selectDevice(v[0])}}).catch(function(e){ss("设备列表失败:"+e.message)})}
E.ds.addEventListener("change",function(){var s=E.ds.value;if(!s)return;selectDevice(s)});
function selectDevice(s){S.serial=s;ap("/api/session/select",{serial:s}).then(function(r){S.mode=r.mode;S.disp=r.display_size;umb();ss("已连接:"+s)}).catch(function(e){ss("连接失败:"+e.message)})}
function umb(){E.ml.classList.toggle("active",S.mode==="live")}

// 是否处于检视模式（snapshot 始终检视；live 需锁定）
function canInspect(){return S.mode==="snapshot"||S.locked}
// 是否允许触控（仅 live 未锁定、未获取中，且首帧已就绪——避免 S.iw=0 时坐标除零产生 NaN）
function canTouch(){return S.mode==="live"&&!S.locked&&!S.fetching&&ensureSize()}

// 更新锁定按钮 UI
function updateLockUI(){
  var kg=document.getElementById("keyGroup");
  var fab=document.getElementById("liveRefreshBtn");
  if(S.mode!=="live"){E.lk.style.display="none";if(kg)kg.style.display="none";if(fab)fab.classList.remove("visible");return}
  E.lk.style.display="";
  if(kg)kg.style.display="";
  if(fab)fab.classList.toggle("visible",!S.locked);
  E.lk.classList.toggle("locked",S.locked);
  E.lkLabel.textContent=S.locked?"解锁":"锁定";
  // 锁定时用解锁图标，未锁定时用锁定图标
  if(S.locked){
    E.lkIcon.innerHTML='<rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 9.9-1"></path>';
  }else{
    E.lkIcon.innerHTML='<rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path>';
  }
}

// 切换锁定状态
function toggleLock(){
  if(S.mode!=="live")return;
  if(S.locked){
    // 解锁：清除选中/悬浮，隐藏画框，恢复触控，恢复实时投屏
    S.locked=false;
    S.sel=null;S.hov=null;
    E.tp.querySelectorAll(".tree-node").forEach(function(n){n.classList.remove("selected","hovered")});
    E.ap.innerHTML="";
    updateLockUI();
    renderOV();
    ss("已解锁 - 可触控操作");
  }else{
    // 锁定：触发一次新的 dump，让控件树与锁定瞬间画面对应
    if(S.loading)return;
    setLoading(true);
    S.fetching=true;
    ss("锁定中 - 获取控件树...");
    ag("/api/hierarchy?serial="+encodeURIComponent(S.serial)).then(function(h){
      S.h=h;renderTree(h);S.locked=true;updateLockUI();renderOV();ss("已锁定 - 可检视控件");
    }).catch(function(e){ss("锁定失败:"+e.message)}).then(function(){S.fetching=false;setLoading(false)});
  }
}
E.lk.addEventListener("click",toggleLock);
// 设备导航按键（仅 live 模式；锁定检视时不可用，避免误操作）
function sendKey(key){
  if(!S.serial||S.mode!=="live")return;
  if(S.locked){ss("请先解锁再操作设备按键");return}
  ap("/api/key",{serial:S.serial,key:key}).then(function(){ss("已发送按键: "+key)}).catch(function(e){ss("按键失败:"+e.message)});
}
(function(){
  var kb=document.getElementById("keyBack");if(kb)kb.addEventListener("click",function(){sendKey("back")});
  var kh=document.getElementById("keyHome");if(kh)kh.addEventListener("click",function(){sendKey("home")});
  var kr=document.getElementById("keyRecent");if(kr)kr.addEventListener("click",function(){sendKey("recent")});
  var lr=document.getElementById("liveRefreshBtn");if(lr)lr.addEventListener("click",refreshLiveFrame);
})();
// 强制刷新画面：live 模式静止时 uitest 不推帧，主动 uinput 轻触诱发一帧
function refreshLiveFrame(){
  if(!S.serial||S.mode!=="live"){ss("仅实时模式可刷新画面");return}
  var fab=document.getElementById("liveRefreshBtn");
  if(fab){if(fab.classList.contains("spinning"))return;fab.classList.add("spinning")}
  ss("正在刷新画面...");
  ap("/api/live/refresh",{serial:S.serial}).then(function(r){
    ss(r&&r.ok?"画面已刷新":"刷新未生效")
  }).catch(function(e){ss("刷新失败:"+e.message)}).then(function(){if(fab)fab.classList.remove("spinning")});
}
E.ml.addEventListener("click",function(){if(!S.serial)return;var next=S.mode==="live"?"snapshot":"live";switchMode(next)});
function switchMode(m){if(m==="live")ss("正在启动实时投屏...");ap("/api/session/mode",{serial:S.serial,mode:m}).then(function(s){S.mode=s.mode;umb();if(m==="live"){S.locked=false;startMjpeg();updateLockUI();ss("实时投屏已开启 - 点击锁定可检视控件")}else{stopMjpeg();S.locked=false;updateLockUI();E.si.style.display="none";E.si.src="";E.ph.classList.remove("hidden");ss("已切换到截图模式")}}).catch(function(e){ss("切换失败:"+e.message)})}
E.ct.addEventListener("change",function(){if(!S.serial)return;ap("/api/session/cleanup",{serial:S.serial,cleanup:E.ct.checked?"stop":"keep"}).catch(function(e){ss("设置失败:"+e.message)})});
E.cs.addEventListener("click",function(){if(!S.serial)return;stopMjpeg();ap("/api/session/close",{serial:S.serial}).then(function(){ss("已断开:"+S.serial);S.serial=null;S.mode="snapshot";S.locked=false;S.fetching=false;umb();updateLockUI();E.si.src="";E.si.style.display="none";E.ph.classList.remove("hidden");E.tp.innerHTML="";E.ap.innerHTML="";E.ds.value="";S.collapsed={};S.sel=null;S.hov=null;S.iw=0;S.ih=0;if(E.scr)E.scr.style.aspectRatio="";renderOV()}).catch(function(e){ss("断开失败:"+e.message)})});
E.rb.addEventListener("click",function(){if(!S.serial){ss("请先选择设备");return}if(S.loading)return;doRefresh()});
function doRefresh(){
  if(!S.serial||S.loading)return;
  setLoading(true);
  if(S.mode==="live"){
    // live 模式：仅获取控件树，获取期间禁止触控，成功后自动锁定
    S.fetching=true;
    ss("获取控件树中...");
    ag("/api/hierarchy?serial="+encodeURIComponent(S.serial)).then(function(h){
      S.h=h;renderTree(h);S.locked=true;updateLockUI();renderOV();ss("控件树已更新 - 已锁定")
    }).catch(function(e){ss("获取失败:"+e.message)}).then(function(){S.fetching=false;setLoading(false)});
  }else{
    ss("获取中...");
    ap("/api/refresh",{serial:S.serial}).then(function(d){
      var fid=d.frame&&d.frame.frame_id;
      showImg("http://127.0.0.1:"+JP+"/snapshot.jpg?serial="+encodeURIComponent(S.serial)+"&frame="+fid+"&nonce="+Date.now());
      S.h=d.hierarchy;renderTree(d.hierarchy);ss("获取完成")
    }).catch(function(e){ss("获取失败:"+e.message)}).then(function(){setLoading(false)});
  }
}
function startMjpeg(){if(!S.serial||!JP)return;showLiveLoading(true);showImg("http://127.0.0.1:"+JP+"/stream.mjpeg?serial="+encodeURIComponent(S.serial));ss("实时投屏已开启")}
function stopMjpeg(){E.si.src="";showLiveLoading(false)}
// 投屏加载态：进入 live 到首帧到达期间显示 spinner + 提示
function showLiveLoading(on){var el=document.getElementById("liveLoading");if(el)el.classList.toggle("hidden",!on)}
function showImg(u){E.ph.classList.add("hidden");E.si.style.display="block";E.si.onload=function(){S.iw=E.si.naturalWidth;S.ih=E.si.naturalHeight;applyAspect();showLiveLoading(false);renderOV()};E.si.src=u}
// 兜底：onload 时序不可靠时，只要 <img> 已有自然尺寸就同步回填，避免 renderOV 因 S.iw=0 永久短路
function ensureSize(){if((!S.iw||!S.ih)&&E.si&&E.si.naturalWidth){S.iw=E.si.naturalWidth;S.ih=E.si.naturalHeight;applyAspect()}return S.iw>0}
// 让内屏宽高比跟随实际截图比例，消除 contain 模式上下黑边
function applyAspect(){if(S.iw>0&&S.ih>0&&E.scr){E.scr.style.aspectRatio=S.iw+" / "+S.ih}}

// ===== 顶层节点处理：跳过 Unknown/root 类型根节点 =====
function getTopNodes(h){
  if(!h||!h.root)return [];
  var rootNode=h.nodes["root"];
  if(!rootNode)return [];
  var a=rootNode.attributes||{};
  var t=(a.type||"").toLowerCase();
  // 如果根节点类型为空、Unknown 或 root，且有子节点，则跳过根节点
  if((t===""||t==="unknown"||t==="root")&&rootNode.children_ids&&rootNode.children_ids.length>0){
    return rootNode.children_ids;
  }
  return ["root"];
}

// ===== 控件树渲染（支持折叠/展开） =====
function renderTree(h){
  if(!h||!h.root){E.tp.innerHTML='<div style="color:#888;padding:8px">无控件树</div>';return}
  E.tp.innerHTML="";
  var tops=getTopNodes(h);
  tops.forEach(function(nid){appendVisible(h,nid,0)});
  if(S.sel){var sn=E.tp.querySelector('[data-node-id="'+CSS.escape(S.sel)+'"]');if(sn)sn.classList.add("selected")}
}
function buildNode(h,nid,depth){
  var n=h.nodes[nid];if(!n)return null;
  var a=n.attributes||{};
  var t=a.type||"?";
  var kids=n.children_ids||[];
  var hasKids=kids.length>0;
  if(S.collapsed[nid]===undefined)S.collapsed[nid]=(depth>=1&&hasKids);
  var isCollapsed=S.collapsed[nid];
  var row=document.createElement("div");
  row.className="tree-node";
  row.setAttribute("data-node-id",nid);
  row.style.paddingLeft=(depth*16+4)+"px";
  var tog=document.createElement("span");
  tog.className="toggle"+(hasKids?"":" empty")+(isCollapsed?" collapsed":"");
  tog.textContent="\u25BC";
  row.appendChild(tog);
  var lab=document.createElement("span");
  lab.className="label";
  var typeSpan=document.createElement("span");
  typeSpan.className="type";
  typeSpan.textContent=t;
  lab.appendChild(typeSpan);
  if(a.text){var tx=document.createElement("span");tx.className="text";tx.textContent=' "'+a.text+'"';lab.appendChild(tx)}
  if(a.id){var idSpan=document.createElement("span");idSpan.className="id";idSpan.textContent=" #"+a.id;lab.appendChild(idSpan)}
  row.appendChild(lab);
  tog.addEventListener("click",function(e){
    e.stopPropagation();
    S.collapsed[nid]=!S.collapsed[nid];
    tog.classList.toggle("collapsed",S.collapsed[nid]);
    var p=row.parentElement;
    if(p){
      if(S.collapsed[nid]){
        var next=row.nextSibling;
        while(next&&next.getAttribute("data-depth")>depth){var nd=next;next=next.nextSibling;p.removeChild(nd)}
      }else{
        var insertAfter=row;
        kids.forEach(function(c){var child=buildNode(h,c,depth+1);if(child){child.setAttribute("data-depth",depth+1);insertAfter.parentNode.insertBefore(child,insertAfter.nextSibling);insertAfter=child}})
      }
    }
  });
  row.addEventListener("click",function(){selNode(nid)});
  row.addEventListener("mouseenter",function(){hovNode(nid)});
  row.addEventListener("mouseleave",function(){hovNode(null)});
  return row;
}
function appendVisible(h,nid,depth){
  var row=buildNode(h,nid,depth);
  if(!row)return;
  row.setAttribute("data-depth",depth);
  E.tp.appendChild(row);
  if(!S.collapsed[nid]){
    var n=h.nodes[nid];if(n){(n.children_ids||[]).forEach(function(c){appendVisible(h,c,depth+1)})}
  }
}

// ===== 选中 / 悬浮 =====
function selNode(nid){
  S.sel=nid;
  E.tp.querySelectorAll(".tree-node").forEach(function(n){n.classList.toggle("selected",n.getAttribute("data-node-id")===nid)});
  renderOV();
  renderAttrs(nid);
  // 联动：展开控件树到对应节点 + 滚动可见，不强制切换 Tab
  expandToNode(nid);
  scrollTreeToNode(nid);
}
function hovNode(nid){
  S.hov=nid;
  E.tp.querySelectorAll(".tree-node").forEach(function(n){n.classList.toggle("hovered",n.getAttribute("data-node-id")===nid)});
  renderOV();
}

// 展开控件树直到目标节点可见（沿父链展开所有折叠的祖先）
function expandToNode(nid){
  if(!S.h||!S.h.nodes||!nid)return;
  // 构建 parent 映射
  var parentMap={};
  Object.keys(S.h.nodes).forEach(function(pid){
    var n=S.h.nodes[pid];
    (n.children_ids||[]).forEach(function(c){parentMap[c]=pid});
  });
  // 从目标节点向上遍历，展开所有折叠的祖先
  var chain=[];
  var cur=parentMap[nid];
  while(cur){chain.push(cur);cur=parentMap[cur]}
  // 需要重新渲染树来反映展开状态
  var needRebuild=false;
  chain.forEach(function(pid){
    // 显式设为 false，覆盖 undefined（未渲染）和 true（已折叠）两种状态
    // 否则 buildNode 会将 undefined 的节点重新初始化为折叠
    if(S.collapsed[pid]!==false){S.collapsed[pid]=false;needRebuild=true}
  });
  if(needRebuild)renderTree(S.h);
}

// 滚动控件树使目标节点可见
function scrollTreeToNode(nid){
  // 延迟执行，确保 renderTree 重建 DOM 后布局已完成
  setTimeout(function(){
    var node=E.tp.querySelector('[data-node-id="'+CSS.escape(nid)+'"]');
    if(node){
      node.scrollIntoView({block:"center",behavior:"smooth"});
    }
  },50);
}

// 切换右侧面板 Tab
function switchTab(name){
  document.querySelectorAll(".panel-tab").forEach(function(x){x.classList.remove("active")});
  var tab=document.querySelector('.panel-tab[data-panel="'+name+'"]');
  if(tab)tab.classList.add("active");
  E.tp.style.display=(name==="tree")?"":"none";
  E.ap.style.display=(name==="attrs")?"":"none";
}

// ===== 属性面板（按优先级排序） =====
var ATTR_ORDER=["type","id","key","text","description","enabled","visible","clickable","longClickable","focusable","focused","selected","checkable","checked","scrollable","opacity","backgroundColor","backgroundImage","blur","clip","zIndex","fontSize","fontFamily","fontWeight","foregroundColor","borderColor","borderWidth","content","accessibilityId","hint","hitTestBehavior","displayId","hostWindowId","hashcode","hierarchy","origBounds","originalText","childCount","x","y"];
function renderAttrs(nid){
  if(!S.h||!S.h.nodes[nid]){E.ap.innerHTML="";return}
  var n=S.h.nodes[nid];
  var a=n.attributes||{};
  var h='<div class="attrs">';
  h+='<div class="attr-row"><div class="attr-key">node_id</div><div class="attr-val">'+esc(nid)+'</div>'+copyBtn(nid)+'</div>';
  if(n.bounds){var bstr='['+n.bounds.left+","+n.bounds.top+"]["+n.bounds.right+","+n.bounds.bottom+"]";h+='<div class="attr-row"><div class="attr-key">bounds</div><div class="attr-val">'+bstr+'</div>'+copyBtn(bstr)+'</div>'}
  // 按优先级排序属性
  var keys=Object.keys(a).filter(function(k){return k!=="bounds"});
  keys.sort(function(x,y){
    var ix=ATTR_ORDER.indexOf(x),iy=ATTR_ORDER.indexOf(y);
    if(ix<0)ix=999;if(iy<0)iy=999;
    if(ix!==iy)return ix-iy;
    return x<y?-1:1;
  });
  keys.forEach(function(k){
    h+='<div class="attr-row"><div class="attr-key">'+esc(k)+'</div><div class="attr-val">'+esc(String(a[k]))+'</div>'+copyBtn(String(a[k]))+'</div>';
  });
  h+="</div>";
  E.ap.innerHTML=h;
  // 绑定复制按钮
  E.ap.querySelectorAll(".attr-copy").forEach(function(btn){
    btn.addEventListener("click",function(){
      var val=btn.getAttribute("data-val");
      copyText(val,btn);
    });
  });
}

// 复制图标按钮 HTML，data-val 存原始值供点击时读取
function copyBtn(val){
  var v=esc(String(val));
  return '<button class="attr-copy" data-val="'+v+'" title="复制"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button>';
}

// 复制文本到剪贴板，并给按钮临时标记已复制状态
function copyText(text,btn){
  if(!text)return;
  var ok=true;
  try{
    navigator.clipboard.writeText(text);
  }catch(e){
    // 降级方案：使用 execCommand
    var ta=document.createElement("textarea");
    ta.value=text;ta.style.position="fixed";ta.style.opacity="0";
    document.body.appendChild(ta);ta.select();
    try{document.execCommand("copy")}catch(e2){ok=false}
    document.body.removeChild(ta);
  }
  // 按钮图标临时切换为对勾，1.2s 后还原
  btn.classList.add("copied");
  var orig=btn.innerHTML;
  btn.innerHTML='<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
  setTimeout(function(){btn.classList.remove("copied");btn.innerHTML=orig},1200);
  // 全局 toast 提示
  showToast(ok?"已复制到剪贴板":"复制失败");
}

// 轻量 toast 提示（居中底部短暂浮现）
var _toastTimer=null;
function showToast(msg){
  var el=document.getElementById("toast");
  if(!el){
    el=document.createElement("div");
    el.id="toast";el.className="toast";
    document.body.appendChild(el);
  }
  el.textContent=msg;
  el.classList.add("show");
  if(_toastTimer)clearTimeout(_toastTimer);
  _toastTimer=setTimeout(function(){el.classList.remove("show")},1400);
}

// ===== Overlay：仅渲染 hover 框 + selected 框 =====
// 计算 object-fit:contain 下图片实际显示区：缩放系数 + 居中黑边偏移
function imgRect(){
  var ew=E.si.clientWidth,eh=E.si.clientHeight;
  var scale=Math.min(ew/S.iw,eh/S.ih);
  var dispW=S.iw*scale,dispH=S.ih*scale;
  return {scale:scale,offX:(ew-dispW)/2,offY:(eh-dispH)/2};
}
function renderOV(){
  if(!S.h||!ensureSize()||!canInspect()){E.ov.innerHTML="";return}
  var dw=S.disp?S.disp[0]:S.iw,dh=S.disp?S.disp[1]:S.ih;
  // 设备坐标 -> 图片像素 -> 显示像素
  var ix=S.iw/dw,iy=S.ih/dh;
  var R=imgRect();
  var svg="";
  // selected 框
  if(S.sel){var r=makeRect(S.h,S.sel,ix,iy,R,"selected");if(r)svg+=r}
  // hover 框（与 selected 不同时才显示）
  if(S.hov&&S.hov!==S.sel){var r2=makeRect(S.h,S.hov,ix,iy,R,"hover");if(r2)svg+=r2}
  E.ov.innerHTML=svg;
}
function makeRect(h,nid,ix,iy,R,cls){
  var n=h.nodes[nid];if(!n||!n.bounds)return null;
  var b=n.bounds;
  var x=R.offX+b.left*ix*R.scale,y=R.offY+b.top*iy*R.scale;
  var w=(b.right-b.left)*ix*R.scale,hh=(b.bottom-b.top)*iy*R.scale;
  return '<rect data-node-id="'+nid+'" class="'+cls+'" x="'+x+'" y="'+y+'" width="'+w+'" height="'+hh+'"></rect>';
}

// ===== 鼠标在截图上移动时，找到最深层匹配节点（仅检视模式） =====
E.si.addEventListener("mousemove",function(e){
  if(!canInspect()||!S.h||!ensureSize())return;
  var r=E.si.getBoundingClientRect();
  var R=imgRect();
  // 鼠标在元素内坐标 -> 扣除黑边偏移 -> 图片像素 -> 设备坐标
  var px=e.clientX-r.left-R.offX,py=e.clientY-r.top-R.offY;
  if(px<0||py<0||px>S.iw*R.scale||py>S.ih*R.scale){if(S.hov)hovNode(null);return}
  var dw=S.disp?S.disp[0]:S.iw,dh=S.disp?S.disp[1]:S.ih;
  var dx=Math.round(px/R.scale*dw/S.iw),dy=Math.round(py/R.scale*dh/S.ih);
  var found=findNodeAt(S.h,dx,dy);
  if(found!==S.hov)hovNode(found);
});
E.si.addEventListener("mouseleave",function(){if(canInspect())hovNode(null)});

// 点击截图区域：选中当前 hover 的节点（仅检视模式）
E.si.addEventListener("click",function(e){
  if(!canInspect()||!S.h||!ensureSize())return;
  if(S.hov)selNode(S.hov);
});

// 画面区域内禁用右键菜单，避免右击触发浏览器上下文菜单干扰交互
if(E.scr)E.scr.addEventListener("contextmenu",function(e){e.preventDefault()});

// 遍历树找到包含坐标且面积最小的节点（最深层匹配）
function findNodeAt(h,dx,dy){
  if(!h||!h.nodes)return null;
  var best=null,bestArea=Infinity;
  var screenArea=(S.disp?S.disp[0]*S.disp[1]:S.iw*S.ih)||1;
  var tops=getTopNodes(h);
  function walk(nid){
    var n=h.nodes[nid];if(!n||!n.bounds)return;
    var b=n.bounds;
    if(dx>=b.left&&dx<=b.right&&dy>=b.top&&dy<=b.bottom){
      var area=(b.right-b.left)*(b.bottom-b.top);
      // 过滤面积超过屏幕 70% 的大容器
      if(area/screenArea<0.7){
        if(area<bestArea){bestArea=area;best=nid}
      }
    }
    var a=n.attributes||{};
    var t=(a.type||"").toLowerCase();
    // 不在 Unknown/root 类型节点内继续向下找
    if(t!=="unknown"&&t!=="root"&&t!==""){
      (n.children_ids||[]).forEach(function(c){walk(c)});
    }else{
      (n.children_ids||[]).forEach(function(c){walk(c)});
    }
  }
  tops.forEach(function(nid){walk(nid)});
  return best;
}

// ===== 触控（仅 live 模式） =====
function i2d(cx,cy){
  if(!ensureSize())return{x:0,y:0};  // 首帧未就绪时兜底，避免除零 NaN
  var r=E.si.getBoundingClientRect();
  var R=imgRect();
  // 扣除黑边偏移后映射到图片像素，再裁剪到图片显示范围内
  var px=Math.max(0,Math.min(cx-r.left-R.offX,S.iw*R.scale));
  var py=Math.max(0,Math.min(cy-r.top-R.offY,S.ih*R.scale));
  var dw=S.disp?S.disp[0]:S.iw,dh=S.disp?S.disp[1]:S.ih;
  return{x:Math.max(0,Math.min(Math.round(px/R.scale*dw/S.iw),dw-1)),y:Math.max(0,Math.min(Math.round(py/R.scale*dh/S.ih),dh-1))};
}
// 触控 move 节流：mousemove 触发极密（60-120Hz），按 ~16ms 固定窗口取最新点发送，
// 即发即忘、不等返回。中间点丢弃，只用最新位置追随手指，降低设备 RPC 压力且保持跟手。
var _pendingMove=null;
var _flushTimer=null;
function _flushMove(){
  _flushTimer=null;
  if(!S.serial||_pendingMove===null)return;
  var c=_pendingMove;_pendingMove=null;
  ap("/api/touch",{serial:S.serial,events:[{type:"move",x:c.x,y:c.y}]}).catch(function(){});
}
function _scheduleFlush(){
  if(_flushTimer!==null)return;
  _flushTimer=setTimeout(_flushMove,16);  // ~60fps 上限
}
E.si.addEventListener("mousedown",function(e){if(!S.serial||!canTouch())return;e.preventDefault();S.touch=true;_pendingMove=null;var c=i2d(e.clientX,e.clientY);ap("/api/touch",{serial:S.serial,events:[{type:"down",x:c.x,y:c.y}]}).catch(function(){})});
E.si.addEventListener("mousemove",function(e){if(!S.touch)return;e.preventDefault();var c=i2d(e.clientX,e.clientY);_pendingMove=c;_scheduleFlush()});
E.si.addEventListener("mouseup",function(e){if(!S.touch)return;e.preventDefault();S.touch=false;if(_flushTimer!==null){clearTimeout(_flushTimer);_flushTimer=null}var c=i2d(e.clientX,e.clientY);var events=[];if(_pendingMove!==null){events.push({type:"move",x:_pendingMove.x,y:_pendingMove.y});_pendingMove=null}events.push({type:"up",x:c.x,y:c.y});ap("/api/touch",{serial:S.serial,events:events}).catch(function(){})});
E.si.addEventListener("mouseleave",function(e){if(!S.touch)return;S.touch=false;if(_flushTimer!==null){clearTimeout(_flushTimer);_flushTimer=null}var c=i2d(e.clientX,e.clientY);var events=[];if(_pendingMove!==null){events.push({type:"move",x:_pendingMove.x,y:_pendingMove.y});_pendingMove=null}events.push({type:"up",x:c.x,y:c.y});ap("/api/touch",{serial:S.serial,events:events}).catch(function(){})});

// ===== Tab =====
document.querySelectorAll(".panel-tab").forEach(function(t){t.addEventListener("click",function(){
  document.querySelectorAll(".panel-tab").forEach(function(x){x.classList.remove("active")});
  t.classList.add("active");
  var p=t.getAttribute("data-panel");
  E.tp.style.display=(p==="tree")?"":"none";
  E.ap.style.display=(p==="attrs")?"":"none";
  var ta=document.getElementById("treeActions");
  if(ta)ta.style.display=(p==="tree")?"flex":"none";
})});

// ===== =====
document.getElementById("expandAllBtn").addEventListener("click",function(){
  if(!S.h)return;
  Object.keys(S.h.nodes).forEach(function(nid){
    var n=S.h.nodes[nid];
    if(n.children_ids&&n.children_ids.length>0)S.collapsed[nid]=false;
  });
  renderTree(S.h);
});
document.getElementById("collapseAllBtn").addEventListener("click",function(){
  if(!S.h)return;
  Object.keys(S.h.nodes).forEach(function(nid){
    var n=S.h.nodes[nid];
    if(n.children_ids&&n.children_ids.length>0)S.collapsed[nid]=true;
  });
  renderTree(S.h);
});

// ===== 拖拽分割线（Pointer Events + setPointerCapture） =====
(function(){
  var sp=document.getElementById("splitter");
  var sa=document.querySelector(".screen-area");
  var main=document.querySelector(".main");
  if(!sp||!sa||!main)return;
  var dragging=false,startX=0,startPct=0;

  sp.addEventListener("pointerdown",function(e){
    dragging=true;
    startX=e.clientX;
    startPct=sa.offsetWidth/main.offsetWidth*100;
    sp.classList.add("dragging");
    document.body.style.cursor="col-resize";
    document.body.style.userSelect="none";
    try{sp.setPointerCapture(e.pointerId)}catch(err){}
    e.preventDefault();
    e.stopPropagation();
  });

  sp.addEventListener("pointermove",function(e){
    if(!dragging)return;
    var dx=e.clientX-startX;
    var mainW=main.offsetWidth;
    if(mainW<=0)return;
    var newPct=startPct+dx/mainW*100;
    newPct=Math.max(15,Math.min(60,newPct));
    sa.style.width=newPct+"%";
    renderOV();
  });

  sp.addEventListener("pointerup",function(e){
    if(!dragging)return;
    dragging=false;
    sp.classList.remove("dragging");
    document.body.style.cursor="";
    document.body.style.userSelect="";
    try{sp.releasePointerCapture(e.pointerId)}catch(err){}
  });

  sp.addEventListener("pointercancel",function(e){
    if(!dragging)return;
    dragging=false;
    sp.classList.remove("dragging");
    document.body.style.cursor="";
    document.body.style.userSelect="";
  });
})();

window.addEventListener("resize",renderOV);
loadDevices();umb();updateLockUI();
})();