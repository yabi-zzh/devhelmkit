// UIViewer frontend logic
(function(){
"use strict";
var P=new URLSearchParams(window.location.search);
var JP=P.get("jpegPort")||0;
var Geometry=window.UiViewerGeometry;
fetch("/api/runtime").then(function(r){return r.json()}).then(function(d){JP=JP||d.jpeg_port}).catch(function(){});
var S={serial:null,sessionReady:false,sessionConnecting:false,mode:"snapshot",h:null,sel:null,hov:null,disp:null,iw:0,ih:0,viewport:null,imageLoadId:0,imageReady:false,touch:false,lastTouchPoint:null,touchStartPoint:null,touchStartAt:0,touchSnapshotId:null,collapsed:{},loading:false,overlayEnabled:false,interactionEnabled:false,manualHierarchyBusy:false,hierarchyRequestBusy:false,hierarchyRequestId:0,hierarchyPollTimer:null,recording:false,recordingBusy:false,recordingPollTimer:null,recordingPollBusy:false,recordingPollRequestId:0};
var E={ds:G("deviceSelect"),dr:G("refreshDevicesBtn"),ml:G("modeLive"),mlLabel:G("modeLiveLabel"),interaction:G("interactionBtn"),interactionLabel:G("interactionLabel"),overlayToggle:G("overlayBtn"),overlayLabel:G("overlayLabel"),recordLabel:G("recordLabel"),rb:G("refreshBtn"),ph:G("placeholder"),sw:G("screenWrapper"),scr:document.querySelector(".phone-screen"),si:G("screenImg"),ov:G("overlay"),side:G("sidePanel"),ic:G("inspectorColumns"),tc:G("treeColumn"),dc:G("detailColumn"),is:G("innerSplitter"),tp:G("treePanel"),ap:G("attrsPanel"),sb:G("statusBar"),sd:G("statusDot")};
function G(id){return document.getElementById(id)}
function ag(u){return fetch(u).then(function(r){if(!r.ok)throw new Error(r.status);return r.json()})}
function ap(u,d){return fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)}).then(function(r){if(!r.ok)throw new Error(r.status);return r.json()})}
function ss(m){E.sb.textContent=m;E.sd.className="dot";if(m.indexOf("失败")>=0||m.indexOf("异常")>=0)E.sd.classList.add("error");else if(m.indexOf("实时")>=0||m.indexOf("live")>=0)E.sd.classList.add("live");else if(m.indexOf("已连接")>=0||m.indexOf("获取完成")>=0||m.indexOf("就绪")>=0||m.indexOf("控件树已更新")>=0)E.sd.classList.add("snapshot")}
function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function setLoading(on){S.loading=on;E.rb.classList.toggle("loading",on);E.rb.disabled=on}
function loadDevices(){
  if(E.dr)E.dr.disabled=true;
  ag("/api/devices").then(function(d){
    var devices=d.devices||[];
    var current=S.serial;
    E.ds.innerHTML="";
    devices.forEach(function(serial){var option=document.createElement("option");option.value=serial;option.textContent=serial;E.ds.appendChild(option)});
    if(current && devices.indexOf(current) >= 0 && (S.sessionReady||S.sessionConnecting)){E.ds.value=current;ss("设备列表已刷新");return}
    if(devices.length){
      E.ds.value=devices[0];
      selectDevice(devices[0]);
    }else{
      E.ds.value="";
      ss("未检测到设备");
    }
  }).catch(function(e){ss("设备列表失败:"+e.message)}).then(function(){if(E.dr)E.dr.disabled=false})
}
if(E.dr)E.dr.addEventListener("click",loadDevices);
E.ds.addEventListener("change",function(){var s=E.ds.value;if(!s)return;selectDevice(s)});
function selectDevice(s){
  if(S.serial===s&&(S.sessionReady||S.sessionConnecting))return;
  var previousSerial=S.serial;
  endActiveGesture();
  flushPendingRecordedClick();
  S.hierarchyRequestId+=1;S.manualHierarchyBusy=false;S.hierarchyRequestBusy=false;setLoading(false);
  if(S.hierarchyPollTimer){clearInterval(S.hierarchyPollTimer);S.hierarchyPollTimer=null}
  stopMjpeg();
  if(S.recordingPollTimer){clearInterval(S.recordingPollTimer);S.recordingPollTimer=null}
  S.recordingPollRequestId+=1;
  if(previousSerial&&(S.recording||S.recordingBusy)){
    enqueueRecordingOperation(function(){
      return ap("/api/record/stop",{serial:previousSerial});
    }).catch(function(){});
  }
  resetImageGeometry();
  E.si.style.display="none";E.ph.classList.remove("hidden");
  S.serial=s;S.sessionReady=false;S.sessionConnecting=true;S.mode="snapshot";S.disp=null;S.h=null;S.sel=null;S.hov=null;S.overlayEnabled=false;S.interactionEnabled=false;S.recording=false;S.recordingBusy=false;S.recordingPollBusy=false;
  setRecordedScriptEvents([],false);
  E.tp.innerHTML="";E.ap.innerHTML="";renderOV();updateControlUI();ss("正在连接:"+s);
  ap("/api/session/select",{serial:s}).then(function(r){
    if(S.serial!==s)return;
    S.sessionReady=true;S.sessionConnecting=false;S.mode=r.mode;S.disp=r.display_size;S.recording=r.recording===true;S.interactionEnabled=S.mode==="live";updateControlUI();scheduleRecordingPoll();pollRecordingState();if(S.recording)ensureRecordingOverlayData();syncHierarchyPolling();ss("已连接:"+s)
  }).catch(function(e){
    if(S.serial===s){S.sessionReady=false;S.sessionConnecting=false;syncHierarchyPolling();updateControlUI();ss("连接失败:"+e.message)}
  })
}
function updateControlUI(){
  var hasSession=Boolean(S.serial)&&S.sessionReady;
  var isLive=hasSession&&S.mode==="live";
  var overlayActive=isLive&&(S.overlayEnabled||S.recording);
  var mr=document.getElementById("modeRecord");
  var keyGroup=document.getElementById("keyGroup");
  E.ml.disabled=!hasSession;
  E.ml.classList.toggle("active",isLive);
  E.ml.setAttribute("aria-pressed",String(isLive));
  E.ml.setAttribute("aria-disabled",String(!hasSession));
  E.ml.dataset.state=!hasSession?"unavailable":isLive?"on":"off";
  E.ml.title=!hasSession?"设备会话连接后可使用":isLive?"停止实时投屏":"开启实时投屏";
  if(E.mlLabel)E.mlLabel.textContent=isLive?"停止投屏":"实时投屏";
  E.rb.disabled=!hasSession||S.loading;

  if(E.interaction){
    var interactionDisabled=!isLive;
    E.interaction.disabled=interactionDisabled;
    E.interaction.classList.toggle("active",isLive&&S.interactionEnabled);
    E.interaction.setAttribute("aria-pressed",String(isLive&&S.interactionEnabled));
    E.interaction.setAttribute("aria-disabled",String(interactionDisabled));
    E.interaction.dataset.state=!isLive?"unavailable":S.interactionEnabled?"on":"off";
    E.interaction.title=!isLive?"实时投屏开启后可使用":S.interactionEnabled?"关闭触摸和设备导航":"开启触摸和设备导航";
    if(E.interactionLabel)E.interactionLabel.textContent=S.interactionEnabled&&isLive?"关闭交互":"开启交互";
  }
  if(E.overlayToggle){
    var overlayDisabled=!isLive||S.manualHierarchyBusy;
    E.overlayToggle.disabled=overlayDisabled;
    E.overlayToggle.classList.toggle("active",isLive&&S.overlayEnabled);
    E.overlayToggle.classList.toggle("effective",overlayActive&&!S.overlayEnabled);
    E.overlayToggle.classList.toggle("is-busy",S.manualHierarchyBusy);
    E.overlayToggle.setAttribute("aria-pressed",String(isLive&&S.overlayEnabled));
    E.overlayToggle.setAttribute("aria-disabled",String(overlayDisabled));
    E.overlayToggle.setAttribute("aria-busy",String(S.manualHierarchyBusy));
    E.overlayToggle.dataset.state=!isLive?"unavailable":S.overlayEnabled?"on":"off";
    E.overlayToggle.title=!isLive?"实时投屏开启后可使用":S.manualHierarchyBusy?"正在获取 UI 控件树":S.overlayEnabled?"隐藏 UI 控件边界":overlayActive?"录制正在临时显示；点击后停止录制仍保持显示":"显示 UI 控件边界";
    if(E.overlayLabel)E.overlayLabel.textContent=S.overlayEnabled&&isLive?"隐藏 UI 框":overlayActive?"保持 UI 框":"显示 UI 框";
  }
  if(mr){
    var recordingAvailable=isLive||S.recording;
    var recordingDisabled=!hasSession||!recordingAvailable||S.recordingBusy;
    mr.disabled=recordingDisabled;
    mr.classList.toggle("recording",S.recording);
    mr.classList.toggle("is-busy",S.recordingBusy);
    mr.setAttribute("aria-pressed",String(S.recording));
    mr.setAttribute("aria-disabled",String(recordingDisabled));
    mr.setAttribute("aria-busy",String(S.recordingBusy));
    mr.dataset.state=!hasSession||!recordingAvailable?"unavailable":S.recording?"on":"off";
    mr.title=!hasSession?"设备会话连接后可使用":!recordingAvailable?"实时投屏开启后可使用":S.recordingBusy?"正在更新录制状态":S.recording?"停止 Web 操作录制":"开始 Web 操作录制";
    if(E.recordLabel)E.recordLabel.textContent=S.recording?"停止录制":"脚本录制";
  }
  if(keyGroup){
    var navigationDisabled=!isLive||!S.interactionEnabled;
    keyGroup.classList.toggle("is-disabled",navigationDisabled);
    keyGroup.querySelectorAll("button").forEach(function(button){button.disabled=navigationDisabled;button.setAttribute("aria-disabled",String(navigationDisabled))});
  }
}

function canInspect(){return S.mode==="snapshot"||(S.mode==="live"&&(S.overlayEnabled||S.recording))}
function canTouch(){return S.mode==="live"&&S.interactionEnabled&&ensureSize()}
function finishActiveGesture(point){
  if(!S.touch)return;
  S.touch=false;
  var end=point||S.lastTouchPoint||S.touchStartPoint;
  if(end)_queueTouchEvent({type:"up",x:end.x,y:end.y});
  if(S.touchStartPoint&&S.mode==="live"&&end){
    var duration=Date.now()-S.touchStartAt;
    var dx=end.x-S.touchStartPoint.x,dy=end.y-S.touchStartPoint.y;
    var distance=Math.sqrt(dx*dx+dy*dy);
    var action=distance>=18?"swipe":duration>=650?"long_click":"click";
    recordGestureAction(action,{x:S.touchStartPoint.x,y:S.touchStartPoint.y,ex:end.x,ey:end.y,duration:Math.max(duration/1000,0.1),snapshot_id:S.touchSnapshotId});
  }
  S.touchStartPoint=null;S.touchStartAt=0;S.touchSnapshotId=null;S.lastTouchPoint=null;
}
function endActiveGesture(){finishActiveGesture()}

function setInteractionEnabled(enabled){
  if(S.mode!=="live")return;
  if(!enabled)endActiveGesture();
  S.interactionEnabled=enabled;
  updateControlUI();
  ss(enabled?"交互已开启 - 可触摸和使用导航按键":"交互已关闭 - 投屏和 UI 框保持运行");
}
function toggleInteraction(){setInteractionEnabled(!S.interactionEnabled)}
if(E.interaction)E.interaction.addEventListener("click",toggleInteraction);

function requestLiveHierarchy(options){
  options=options||{};
  if(!S.serial||S.mode!=="live"||S.hierarchyRequestBusy)return false;
  var serial=S.serial;
  var requestId=S.hierarchyRequestId+1;
  S.hierarchyRequestId=requestId;
  S.hierarchyRequestBusy=true;
  if(options.loading){S.manualHierarchyBusy=true;setLoading(true);updateControlUI()}
  if(options.status)ss(options.status);
  ag("/api/hierarchy?serial="+encodeURIComponent(serial)).then(function(h){
    if(S.serial!==serial||S.hierarchyRequestId!==requestId)return;
    if(options.onSuccess)options.onSuccess(h);
  }).catch(function(e){
    if(S.serial!==serial||S.hierarchyRequestId!==requestId)return;
    if(options.onError)options.onError(e);
  }).then(function(){
    if(S.serial!==serial||S.hierarchyRequestId!==requestId)return;
    S.hierarchyRequestBusy=false;
    if(options.loading){S.manualHierarchyBusy=false;setLoading(false);updateControlUI()}
  });
  return true;
}
function hierarchyPollingEnabled(){
  return Boolean(S.serial&&S.sessionReady&&S.mode==="live"&&(S.overlayEnabled||S.recording));
}
function refreshLiveHierarchy(){
  if(!hierarchyPollingEnabled())return;
  requestLiveHierarchy({
    onSuccess:function(h){
      var selected=S.sel;
      S.h=h;
      if(selected&&(!h.nodes||!h.nodes[selected])){
        S.sel=null;S.hov=null;renderAttrs(null);
      }
      renderTree(h);
      renderOV();
    },
    onError:function(e){ss("UI 控件树刷新失败:"+e.message)}
  });
}
function startHierarchyPolling(){
  if(S.hierarchyPollTimer)return;
  S.hierarchyPollTimer=setInterval(function(){
    if(hierarchyPollingEnabled())refreshLiveHierarchy();
    else stopHierarchyPolling(true);
  },1000);
}
function stopHierarchyPolling(cancelRequest){
  if(S.hierarchyPollTimer){clearInterval(S.hierarchyPollTimer);S.hierarchyPollTimer=null}
  if(cancelRequest&&S.hierarchyRequestBusy){
    S.hierarchyRequestId+=1;
    S.hierarchyRequestBusy=false;
    if(S.manualHierarchyBusy){S.manualHierarchyBusy=false;setLoading(false);updateControlUI()}
  }
}
function syncHierarchyPolling(){
  if(hierarchyPollingEnabled())startHierarchyPolling();
  else stopHierarchyPolling(true);
}
function ensureRecordingOverlayData(){
  if(!S.recording||S.mode!=="live"||S.h||S.manualHierarchyBusy)return;
  requestLiveHierarchy({
    onSuccess:function(h){S.h=h;renderTree(h);renderOV()},
    onError:function(e){ss("录制 UI 框获取失败:"+e.message)}
  });
}
function setOverlayEnabled(enabled){
  if(S.mode!=="live")return;
  if(!enabled){
    S.overlayEnabled=false;S.hov=null;
    syncHierarchyPolling();
    updateControlUI();renderOV();ss(S.recording?"UI 框恢复为录制自动显示 - 交互状态不变":"UI 框已关闭 - 交互状态不变");
    return;
  }
  if(S.manualHierarchyBusy)return;
  S.overlayEnabled=true;
  updateControlUI();
  requestLiveHierarchy({
    loading:true,
    status:"正在获取 UI 控件树...",
    onSuccess:function(h){S.h=h;renderTree(h);renderOV();syncHierarchyPolling();ss("UI 框已开启 - 可继续触摸操作")},
    onError:function(e){S.overlayEnabled=false;renderOV();ss("UI 框开启失败:"+e.message)}
  });
}
function toggleOverlay(){setOverlayEnabled(!S.overlayEnabled)}
if(E.overlayToggle)E.overlayToggle.addEventListener("click",toggleOverlay);

// 设备按键始终发送真实操作，录制结果由 Viewer 自己的操作事件提供。
function sendKey(key){
  if(!S.serial||S.mode!=="live")return;
  if(!S.interactionEnabled){ss("请先开启交互再使用导航按键");return}
  ap("/api/key",{serial:S.serial,key:key}).then(function(){
    if(S.recording)recordWebAction("key",{key:key});
    ss("已发送按键: "+key)
  }).catch(function(e){ss("按键失败:"+e.message)});
}
(function(){
  var kb=document.getElementById("keyBack");if(kb)kb.addEventListener("click",function(){sendKey("back")});
  var kh=document.getElementById("keyHome");if(kh)kh.addEventListener("click",function(){sendKey("home")});
  var kr=document.getElementById("keyRecent");if(kr)kr.addEventListener("click",function(){sendKey("recent")});
  var llw=document.getElementById("llWakeupBtn");if(llw)llw.addEventListener("click",refreshLiveFrame);
})();
// 强制刷新画面：live 模式静止时 uitest 不推帧，主动 uinput 轻触诱发一帧
function refreshLiveFrame(){
  if(!S.serial||S.mode!=="live"){ss("仅实时模式可刷新画面");return}
  ss("正在刷新画面...");
  ap("/api/live/refresh",{serial:S.serial}).then(function(r){
    ss(r&&r.ok?"画面已刷新":"刷新未生效")
  }).catch(function(e){ss("刷新失败:"+e.message)});
}
E.ml.addEventListener("click",function(){if(!S.serial){ss("请先选择设备");return}var next=S.mode==="live"?"snapshot":"live";switchMode(next)});
function switchMode(mode){
  if(!S.serial)return Promise.reject(new Error("请先选择设备"));
  var serial=S.serial;
  if(mode==="live")ss("正在启动实时投屏...");
  return ap("/api/session/mode",{serial:serial,mode:mode}).then(function(state){
    if(S.serial!==serial)return state;
    S.mode=state.mode;
    if(S.mode==="live"){
      S.interactionEnabled=true;S.overlayEnabled=false;S.h=null;S.sel=null;S.hov=null;E.tp.innerHTML="";E.ap.innerHTML="";startMjpeg();syncHierarchyPolling();updateControlUI();
      if(S.recording){ensureRecordingOverlayData();pollRecordingState()}
      ss(S.recording?"实时投屏已开启 - 交互默认开启，录制继续运行":"实时投屏已开启 - 交互默认开启");
    }else{
      endActiveGesture();
      S.hierarchyRequestId+=1;S.manualHierarchyBusy=false;S.hierarchyRequestBusy=false;setLoading(false);
      stopHierarchyPolling();
      stopMjpeg();resetImageGeometry();S.interactionEnabled=false;S.overlayEnabled=false;S.h=null;updateControlUI();E.si.style.display="none";E.ph.classList.remove("hidden");S.sel=null;S.hov=null;E.tp.innerHTML="";E.ap.innerHTML="";renderOV();renderAttrs(null);ss(S.recording?"已切换到截图模式 - 脚本录制继续运行":"已切换到截图模式");
    }
    return state;
  }).catch(function(e){ss("切换失败:"+e.message);throw e})
}
E.rb.addEventListener("click",function(){if(!S.serial){ss("请先选择设备");return}if(S.loading||S.manualHierarchyBusy)return;doRefresh()});
function doRefresh(){
  if(!S.serial||S.loading||S.manualHierarchyBusy)return;
  var serial=S.serial;
  if(S.mode==="live"){
    // live 模式只刷新控件树，不改变投屏、交互或 UI 框的用户开关。
    requestLiveHierarchy({
      loading:true,
      status:"获取控件树中...",
      onSuccess:function(h){S.h=h;renderTree(h);renderOV();ss("控件树已更新 - 可继续触控操作")},
      onError:function(e){ss("获取失败:"+e.message)}
    });
  }else{
    setLoading(true);ss("获取中...");
    ap("/api/refresh",{serial:serial}).then(function(d){
      if(S.serial!==serial)return;
      var fid=d.frame&&d.frame.frame_id;
      showImg("http://127.0.0.1:"+JP+"/snapshot.jpg?serial="+encodeURIComponent(serial)+"&frame="+fid+"&nonce="+Date.now());
      S.h=d.hierarchy;renderTree(d.hierarchy);ss("获取完成")
    }).catch(function(e){if(S.serial===serial)ss("获取失败:"+e.message)}).then(function(){if(S.serial===serial)setLoading(false)});
  }
}
var _liveTimeoutTimer=null;
function startMjpeg(){
  if(!S.serial||!JP)return;
  resetImageGeometry();
  showLiveLoading(true);
  if(_liveTimeoutTimer)clearTimeout(_liveTimeoutTimer);
  _liveTimeoutTimer=setTimeout(function(){
    var el=document.getElementById("liveLoading");
    if(el&&!el.classList.contains("hidden")){
      ss("首帧加载超时，自动刷新画面中...");
      refreshLiveFrame();
    }
  },1000);
  showImg("http://127.0.0.1:"+JP+"/stream.mjpeg?serial="+encodeURIComponent(S.serial));
  ss("实时投屏已开启")
}
function stopMjpeg(){
  if(_liveTimeoutTimer){clearTimeout(_liveTimeoutTimer);_liveTimeoutTimer=null}
  S.imageLoadId+=1;
  E.si.onload=null;
  E.si.onerror=null;
  E.si.src="";
  showLiveLoading(false)
}
// 投屏加载态：进入 live 到首帧到达期间显示 spinner + 提示
function showLiveLoading(on){var el=document.getElementById("liveLoading");if(el)el.classList.toggle("hidden",!on)}
function showImg(u){
  resetImageGeometry();
  var loadId=S.imageLoadId+1;
  S.imageLoadId=loadId;
  E.ph.classList.add("hidden");
  E.si.style.display="block";
  E.si.style.visibility="hidden";
  E.si.onload=function(){
    if(loadId!==S.imageLoadId)return;
    if(_liveTimeoutTimer){clearTimeout(_liveTimeoutTimer);_liveTimeoutTimer=null}
    S.iw=E.si.naturalWidth;
    S.ih=E.si.naturalHeight;
    S.imageReady=true;
    updateViewport();
    applyAspect();
    E.si.style.visibility="visible";
    showLiveLoading(false);
    renderOV()
  };
  E.si.onerror=function(){
    if(loadId!==S.imageLoadId)return;
    resetImageGeometry();
    E.si.style.display="none";
    E.si.style.visibility="";
    E.ph.classList.remove("hidden");
    showLiveLoading(false);
    renderOV();
    ss("画面加载失败")
  };
  E.si.src=u
}
// 实时帧的裁剪边界由纯几何模块派生：已验证时仅保留左上有效区域；
// 任何尺寸异常均保留整张 JPEG，避免根据方向或旧帧数据猜测内容边界。
var LIVE_CAPTURE_SCALE=Geometry.DEFAULT_LIVE_SCALE;
var VIEWPORT_SIZE_TOLERANCE=Geometry.DEFAULT_SIZE_TOLERANCE;
function updateViewport(){
  S.viewport=Geometry.deriveEffectiveViewport({
    mode:S.mode,
    rawWidth:S.iw,
    rawHeight:S.ih,
    displayWidth:S.disp&&S.disp[0],
    displayHeight:S.disp&&S.disp[1],
    scale:LIVE_CAPTURE_SCALE,
    tolerance:VIEWPORT_SIZE_TOLERANCE
  });
  return S.viewport;
}
function viewport(){return S.viewport||updateViewport()}
function viewportTransform(){
  var vp=viewport();
  if(!vp||!E.scr)return null;
  var rect=E.scr.getBoundingClientRect();
  return Geometry.createViewportTransform(vp,rect.width,rect.height);
}
function resetImageGeometry(){
  S.iw=0;S.ih=0;S.viewport=null;S.imageReady=false;
  if(E.scr){
    E.scr.style.aspectRatio="";
    E.scr.style.removeProperty("--phone-screen-width");
    E.scr.style.removeProperty("--phone-screen-height");
  }
  if(E.sw){
    E.sw.style.removeProperty("--phone-frame-width");
    E.sw.style.removeProperty("--phone-frame-height");
  }
  E.si.style.width="";E.si.style.height="";
}
// 兜底：onload 时序不可靠时，只在当前源已完成加载的前提下同步回填，
// 避免把切换前残留的 naturalWidth 误认为新帧的几何尺寸。
function ensureSize(){
  if(!S.imageReady&&E.si&&E.si.complete&&E.si.naturalWidth){
    S.iw=E.si.naturalWidth;S.ih=E.si.naturalHeight;S.imageReady=true;
    updateViewport();applyAspect();
  }
  return S.imageReady&&S.iw>0&&S.ih>0
}
// 手机壳、截图内屏和 overlay 都以有效视口定尺寸；原图若有右侧冗余，
// 仅扩大 img 自身宽度并由 phone-screen 的 overflow 裁掉，不改 JPEG 字节。
function applyAspect(){
  var vp=viewport();
  if(vp&&E.scr){
    E.scr.style.aspectRatio=vp.contentRect.width+" / "+vp.contentRect.height;
    resizePhoneFrame();
  }
}
function resizePhoneFrame(){
  var vp=viewport();
  if(!E.sw||!E.scr||!vp)return;
  var area=document.querySelector(".screen-area");
  if(!area)return;
  var ar=area.getBoundingClientRect();
  var areaStyle=window.getComputedStyle(area);
  var frameStyle=window.getComputedStyle(E.sw);
  function cssPx(v){return parseFloat(v)||0}
  var padX=cssPx(areaStyle.paddingLeft)+cssPx(areaStyle.paddingRight);
  var padY=cssPx(areaStyle.paddingTop)+cssPx(areaStyle.paddingBottom);
  var frameExtraX=cssPx(frameStyle.paddingLeft)+cssPx(frameStyle.paddingRight)+cssPx(frameStyle.borderLeftWidth)+cssPx(frameStyle.borderRightWidth);
  var frameExtraY=cssPx(frameStyle.paddingTop)+cssPx(frameStyle.paddingBottom)+cssPx(frameStyle.borderTopWidth)+cssPx(frameStyle.borderBottomWidth);
  var usableW=ar.width-padX-frameExtraX;
  var usableH=ar.height-padY-frameExtraY;
  if(usableW<=0||usableH<=0)return;
  var content=vp.contentRect;
  var scale=Math.min(usableW/content.width,usableH/content.height);
  var screenW=Math.max(1,Math.floor(content.width*scale));
  var screenH=Math.max(1,Math.floor(content.height*scale));
  E.scr.style.setProperty("--phone-screen-width",screenW+"px");
  E.scr.style.setProperty("--phone-screen-height",screenH+"px");
  E.sw.style.setProperty("--phone-frame-width",(screenW+frameExtraX)+"px");
  E.sw.style.setProperty("--phone-frame-height",(screenH+frameExtraY)+"px");
  E.si.style.width=Math.ceil(vp.rawWidth*scale)+"px";
  E.si.style.height=Math.ceil(vp.rawHeight*scale)+"px";
}
function relayoutScreen(){
  resizePhoneFrame();
  renderOV();
}
function scheduleScreenRelayout(){
  relayoutScreen();
  if(window.requestAnimationFrame){window.requestAnimationFrame(relayoutScreen)}
  else setTimeout(relayoutScreen,0);
}

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
  row.style.paddingLeft=(depth*12+4)+"px";
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
  // 选中节点时把目标放到阅读友好的区域：纵向居中，横向保留一段父级路径上下文。
  setTimeout(function(){
    var node=E.tp.querySelector('[data-node-id="'+CSS.escape(nid)+'"]');
    if(!node)return;
    var label=node.querySelector(".label")||node;
    var maxTop=Math.max(0,E.tp.scrollHeight-E.tp.clientHeight);
    var maxLeft=Math.max(0,E.tp.scrollWidth-E.tp.clientWidth);
    var targetTop=clamp(node.offsetTop-Math.floor((E.tp.clientHeight-node.offsetHeight)/2),0,maxTop);
    var labelLeft=label.offsetLeft;
    var targetLeft=clamp(labelLeft-Math.floor(E.tp.clientWidth*0.35),0,maxLeft);
    if(E.tp.scrollTo){
      E.tp.scrollTo({top:targetTop,left:targetLeft,behavior:"smooth"});
    }else{
      E.tp.scrollTop=targetTop;
      E.tp.scrollLeft=targetLeft;
    }
  },50);
}

function isWideInspector(){return window.matchMedia&&window.matchMedia("(min-width: 1440px)").matches}
function storageNumber(key,fallback){
  try{
    var value=Number(localStorage.getItem(key));
    return Number.isFinite(value)?value:fallback;
  }catch(e){return fallback}
}
function storeNumber(key,value){try{localStorage.setItem(key,String(value))}catch(e){}}
function clamp(v,min,max){return Math.max(min,Math.min(max,v))}
var INSPECTOR_TREE_MIN_PCT=28;
var INSPECTOR_TREE_MAX_PCT=78;
var INSPECTOR_TREE_MIN_WIDTH=320;
var INSPECTOR_DETAIL_MIN_WIDTH=320;
var INSPECTOR_SPLITTER_WIDTH=6;
function detailAwareTreeMaxPct(colsW){
  if(!colsW||colsW<=0)return INSPECTOR_TREE_MAX_PCT;
  var maxByDetail=(colsW-INSPECTOR_SPLITTER_WIDTH-INSPECTOR_DETAIL_MIN_WIDTH)/colsW*100;
  return clamp(maxByDetail,INSPECTOR_TREE_MIN_PCT,INSPECTOR_TREE_MAX_PCT);
}
function applyInspectorTreeWidth(pct){
  if(!E.side)return;
  var p=clamp(Number(pct)||42,INSPECTOR_TREE_MIN_PCT,INSPECTOR_TREE_MAX_PCT);
  var maxWidth="calc(100% - "+(INSPECTOR_DETAIL_MIN_WIDTH+INSPECTOR_SPLITTER_WIDTH)+"px)";
  E.side.style.setProperty("--tree-column-width","clamp("+INSPECTOR_TREE_MIN_WIDTH+"px, "+p+"%, "+maxWidth+")");
}
function syncLayoutState(){
  if(isWideInspector())applyInspectorTreeWidth(storageNumber("uiviewer.treeWidthPct",42));
}
function activePanel(){
  var tab=document.querySelector(".panel-tab.active");
  return tab?tab.getAttribute("data-panel"):"attrs";
}

// 切换右侧面板 Tab：宽屏时控件树常驻中列，右列只在属性和录制间切换。
function switchTab(name){
  syncLayoutState();
  var wide=isWideInspector();
  var requested=name||activePanel()||"attrs";
  var detail=(wide&&requested==="tree")?"attrs":requested;
  document.querySelectorAll(".panel-tab").forEach(function(x){x.classList.toggle("active",x.getAttribute("data-panel")===detail)});
  if(E.side){
    E.side.classList.toggle("wide-inspector",wide);
    E.side.classList.toggle("tree-tab-mode",!wide&&requested==="tree");
  }
  if(E.tc)E.tc.style.display=(wide||requested==="tree")?"flex":"none";
  if(E.dc)E.dc.style.display="flex";
  E.tp.style.display=(wide||requested==="tree")?"":"none";
  E.ap.style.display=(detail==="attrs")?"":"none";
  var rp=document.getElementById("recorderPanel");
  if(rp)rp.style.display=(detail==="recorder")?"flex":"none";
  var ta=document.getElementById("treeActions");
  if(ta)ta.style.display=(wide||requested==="tree")?"flex":"none";
  resizeXPathInput(document.getElementById("xpathValue"));
}

// ===== 属性面板（按优先级排序） =====
var ATTR_ORDER=["type","id","key","text","description","enabled","visible","clickable","longClickable","focusable","focused","selected","checkable","checked","scrollable","opacity","backgroundColor","backgroundImage","blur","clip","zIndex","fontSize","fontFamily","fontWeight","foregroundColor","borderColor","borderWidth","content","accessibilityId","hint","hitTestBehavior","displayId","hostWindowId","hashcode","hierarchy","origBounds","originalText","childCount","x","y"];
var XPATH_BY_OPTIONS=[
  ["class","class"],["key","key"],["id","id"],["text","text"],
  ["description","description"],["bounds","bounds"],["path","path"]
];
function xpathPanelHtml(){
  var opts=XPATH_BY_OPTIONS.map(function(o){return '<option value="'+esc(o[0])+'">'+esc(o[1])+'</option>'}).join("");
  return '<div class="xpath-box">'
    +'<div class="xpath-toolbar"><span class="xpath-title">XPath</span><span class="xpath-by-label">by</span><select id="xpathBySelect">'+opts+'</select>'
    +'<button id="xpathCopyBtn" class="attr-copy xpath-copy" title="复制 XPath">'
    +'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>'
    +'</button></div>'
    +'<div class="xpath-line"><textarea id="xpathValue" class="xpath-input" readonly rows="1">生成中...</textarea></div>'
    +'<div id="xpathMeta" class="xpath-meta"></div></div>';
}
function resizeXPathInput(input){
  if(!input)return;
  var line=input.closest(".xpath-line");
  var lineWidth=line?line.clientWidth:0;
  var maxWidth=lineWidth?Math.max(96,lineWidth):Infinity;
  var minWidth=112;
  var measure=document.getElementById("xpathMeasure");
  if(!measure){
    measure=document.createElement("span");
    measure.id="xpathMeasure";
    measure.className="xpath-measure";
    document.body.appendChild(measure);
  }
  var text=input.value||input.placeholder||"";
  measure.textContent=text||" ";
  var contentWidth=Math.ceil(measure.getBoundingClientRect().width)+24;
  var width=Math.min(maxWidth,Math.max(minWidth,contentWidth));
  input.style.width=width+"px";
  input.style.height="auto";
  input.style.height=input.scrollHeight+"px";
}
function renderXPathMeta(meta, requested, actual, matches){
  if(!meta)return;
  var actualBy=actual||requested||"";
  var actualLabel=actualBy||"当前选择";
  var countNumber=Number(matches);
  var hasCount=matches!==undefined&&matches!==null&&matches!==""&&Number.isFinite(countNumber);
  var stateClass="neutral";
  var stateText="匹配数未知";
  if(hasCount){
    if(countNumber===1){stateClass="unique";stateText="唯一匹配"}
    else if(countNumber>1){stateClass="warn";stateText=countNumber+" 个匹配，非唯一"}
    else{stateClass="empty";stateText="未命中"}
  }
  var sourceClass=actualBy!==requested?"fallback":"source";
  var sourceText=actualBy!==requested?("已回退到 "+actualLabel):("依据 "+actualLabel);
  var chips=actualBy!==requested?('<span class="xpath-meta-chip '+sourceClass+'">'+esc(sourceText)+'</span>'):"";
  chips+='<span class="xpath-meta-chip '+stateClass+'">'+esc(stateText)+'</span>';
  meta.className="xpath-meta xpath-meta-"+stateClass;
  meta.title=sourceText+" · "+stateText;
  meta.innerHTML=chips;
}
function bindXPathPanel(nid){
  var sel=document.getElementById("xpathBySelect");
  var copy=document.getElementById("xpathCopyBtn");
  var input=document.getElementById("xpathValue");
  resizeXPathInput(input);
  if(!sel)return;
  sel.addEventListener("change",function(){loadXPath(nid,sel.value)});
  if(copy){
    copy.addEventListener("click",function(){
      var input=document.getElementById("xpathValue");
      if(input&&input.value&&input.value!=="生成中...")copyText(input.value,copy);
      else showToast("暂无可复制的 XPath");
    });
  }
  loadXPath(nid,sel.value);
}
function loadXPath(nid,by){
  var input=document.getElementById("xpathValue");
  var meta=document.getElementById("xpathMeta");
  if(!input)return;
  input.value="生成中...";
  resizeXPathInput(input);
  if(meta){meta.className="xpath-meta";meta.textContent="";meta.title=""}
  if(!S.serial){
    input.value="";
    resizeXPathInput(input);
    if(meta){meta.className="xpath-meta xpath-meta-empty";meta.textContent="请先选择设备";meta.title=""}
    return;
  }
  ag("/api/xpath?serial="+encodeURIComponent(S.serial)+"&node_id="+encodeURIComponent(nid)+"&by="+encodeURIComponent(by)).then(function(d){
    if(S.sel!==nid)return;
    input.value=d.xpath||"";
    resizeXPathInput(input);
    var selected=d.selected||{};
    var actual=d.by||selected.by||by;
    renderXPathMeta(meta,by,actual,selected.matches);
  }).catch(function(e){
    if(S.sel!==nid)return;
    input.value="";
    resizeXPathInput(input);
    if(meta){meta.className="xpath-meta xpath-meta-empty";meta.textContent="XPath 生成失败: "+e.message;meta.title=""}
  });
}
function renderAttrs(nid){
  if(!S.h||!S.h.nodes[nid]){E.ap.innerHTML="";return}
  var n=S.h.nodes[nid];
  var a=n.attributes||{};
  var h='<div class="attrs">';
  h+='<div class="attr-row"><div class="attr-key" title="node_id">node_id</div><div class="attr-val">'+esc(nid)+'</div>'+copyBtn(nid)+'</div>';
  h+=xpathPanelHtml();
  if(n.bounds){var bstr='['+n.bounds.left+","+n.bounds.top+"]["+n.bounds.right+","+n.bounds.bottom+"]";h+='<div class="attr-row"><div class="attr-key" title="bounds">bounds</div><div class="attr-val">'+bstr+'</div>'+copyBtn(bstr)+'</div>'}
  // 按优先级排序属性
  var keys=Object.keys(a).filter(function(k){return k!=="bounds"});
  keys.sort(function(x,y){
    var ix=ATTR_ORDER.indexOf(x),iy=ATTR_ORDER.indexOf(y);
    if(ix<0)ix=999;if(iy<0)iy=999;
    if(ix!==iy)return ix-iy;
    return x<y?-1:1;
  });
  keys.forEach(function(k){
    h+='<div class="attr-row"><div class="attr-key" title="'+esc(k)+'">'+esc(k)+'</div><div class="attr-val">'+esc(String(a[k]))+'</div>'+copyBtn(String(a[k]))+'</div>';
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
  bindXPathPanel(nid);
}

// 复制图标按钮 HTML，data-val 存原始值供点击时读取
function copyBtn(val){
  var v=esc(String(val));
  return '<button class="attr-copy" data-val="'+v+'" title="复制"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button>';
}

// 复制文本到剪贴板，并给按钮临时标记已复制状态
function fallbackCopyText(text){
  var ta=document.createElement("textarea");
  ta.value=text;
  ta.style.position="fixed";
  ta.style.opacity="0";
  document.body.appendChild(ta);
  ta.select();
  try{return document.execCommand("copy")}catch(e){return false}
  finally{document.body.removeChild(ta)}
}
function markCopyResult(btn,ok){
  if(btn){
    btn.classList.add("copied");
    var orig=btn.innerHTML;
    btn.innerHTML='<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
    setTimeout(function(){btn.classList.remove("copied");btn.innerHTML=orig},1200);
  }
  showToast(ok?"已复制到剪贴板":"复制失败");
}
function copyText(text,btn){
  if(!text)return;
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(function(){markCopyResult(btn,true)}).catch(function(){markCopyResult(btn,fallbackCopyText(text))});
    return;
  }
  markCopyResult(btn,fallbackCopyText(text));
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
// 所有交互都经由同一个设备坐标 ↔ 有效源视口 ↔ DOM 像素变换，
// 因而即使原始 JPEG 在右侧带冗余，控件、命中与触控仍落在同一设备坐标系。
function imgRect(){return viewportTransform()}
function renderOV(){
  if(!S.h||!ensureSize()||!canInspect()){E.ov.innerHTML="";return}
  var transform=imgRect();
  if(!transform){E.ov.innerHTML="";return}
  var svg="";
  if(S.sel){var r=makeRect(S.h,S.sel,transform,"selected");if(r)svg+=r}
  if(S.hov&&S.hov!==S.sel){var r2=makeRect(S.h,S.hov,transform,"hover");if(r2)svg+=r2}
  E.ov.innerHTML=svg;
}
function makeRect(h,nid,transform,cls){
  var n=h.nodes[nid];if(!n||!n.bounds)return null;
  var b=n.bounds;
  var start=transform.deviceToDom(b.left,b.top);
  var end=transform.deviceToDom(b.right,b.bottom);
  return '<rect data-node-id="'+nid+'" class="'+cls+'" x="'+start.x+'" y="'+start.y+'" width="'+(end.x-start.x)+'" height="'+(end.y-start.y)+'"></rect>';
}

// ===== 鼠标在截图上移动时，找到最深层匹配节点（仅检视模式） =====
E.si.addEventListener("mousemove",function(e){
  if(!canInspect()||!S.h||!ensureSize())return;
  var r=E.scr.getBoundingClientRect();
  var transform=imgRect();
  if(!transform)return;
  var px=e.clientX-r.left,py=e.clientY-r.top;
  if(px<0||py<0||px>transform.width||py>transform.height){if(S.hov)hovNode(null);return}
  var devicePoint=transform.domToDevice(px,py);
  var found=findNodeAt(S.h,Math.round(devicePoint.x),Math.round(devicePoint.y));
  if(found!==S.hov)hovNode(found);
});
E.si.addEventListener("mouseleave",function(){if(canInspect())hovNode(null)});

// 点击截图区域：选中当前 hover 的节点（仅检视模式）
E.si.addEventListener("click",function(){
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
    // 所有子节点使用同一命中规则；Unknown/root 只影响树展示入口，不截断检视命中。
    (n.children_ids||[]).forEach(function(c){walk(c)});
  }
  tops.forEach(function(nid){walk(nid)});
  return best;
}

// ===== 触控（仅 live 模式） =====
function i2d(cx,cy){
  if(!ensureSize())return{x:0,y:0};
  var r=E.scr.getBoundingClientRect();
  var transform=imgRect();
  var vp=viewport();
  if(!transform||!vp)return{x:0,y:0};
  var px=Math.max(0,Math.min(cx-r.left,transform.width));
  var py=Math.max(0,Math.min(cy-r.top,transform.height));
  var devicePoint=transform.domToDevice(px,py);
  return{
    x:Math.max(0,Math.min(Math.round(devicePoint.x),vp.displayWidth-1)),
    y:Math.max(0,Math.min(Math.round(devicePoint.y),vp.displayHeight-1))
  };
}
// 触控发送泵：任意时刻只允许一个请求执行；连续 move 只保留最新坐标。
// 普通 move 最快约 60Hz，结束手势时将最后一个 move 与 up 同批发送，兼顾跟手与顺序。
var TOUCH_MOVE_INTERVAL_MS=16;
function createTouchPump(sendBatch){
  var queue=[];
  var requestActive=false;
  var flushTimer=null;
  var lastMoveSentAt=0;

  function sendNextBatch(){
    if(requestActive||!queue.length)return;
    var first=queue.shift();
    var events=[first.event];
    var next=queue.length?queue[0]:null;
    if(first.event.type==="move"&&next&&next.serial===first.serial&&next.event.type==="up"){
      events.push(queue.shift().event);
    }
    if(events.some(function(event){return event.type==="move"}))lastMoveSentAt=performance.now();
    requestActive=true;
    Promise.resolve(sendBatch(first.serial,events))
      .catch(function(){})
      .then(function(){requestActive=false;pump()});
  }

  function pump(){
    if(requestActive||flushTimer!==null||!queue.length)return;
    var first=queue[0];
    var next=queue.length>1?queue[1]:null;
    var endingMove=first.event.type==="move"&&next&&
      next.serial===first.serial&&next.event.type==="up";
    var wait=first.event.type==="move"&&!endingMove?
      Math.max(0,TOUCH_MOVE_INTERVAL_MS-(performance.now()-lastMoveSentAt)):0;
    if(wait>0){
      flushTimer=setTimeout(function(){flushTimer=null;sendNextBatch()},wait);
      return;
    }
    sendNextBatch();
  }

  return function(serial,event){
    var item={serial:serial,event:event};
    var last=queue.length?queue[queue.length-1]:null;
    if(event.type==="move"&&last&&last.serial===serial&&last.event.type==="move"){
      queue[queue.length-1]=item;
    }else{
      queue.push(item);
    }
    if(event.type==="up"&&flushTimer!==null){
      clearTimeout(flushTimer);
      flushTimer=null;
    }
    pump();
  };
}
var _enqueueTouch=createTouchPump(function(serial,events){
  return ap("/api/touch",{serial:serial,events:events});
});
function _queueTouchEvent(event){
  if(S.serial)_enqueueTouch(S.serial,event);
}
var recordedScriptEvents=[];
var _recordingActionQueue=Promise.resolve();
// 录制新增、删除、清空、状态读取和停止共用一条队列，避免旧响应覆盖较新的脚本状态。
function enqueueRecordingOperation(operation){
  var result=_recordingActionQueue.then(operation);
  // 单次失败仍返回给调用方处理，但不能让后续队列永久保持 rejected。
  _recordingActionQueue=result.catch(function(){});
  return result;
}
function scriptCode(event){return String(event&&(event.code||event.script)||"").replace(/\r\n/g,"\n")}
function getScriptText(){return recordedScriptEvents.map(scriptCode).filter(Boolean).join("\n")}
function syncScriptBuffer(){
  var ta=document.getElementById("scriptTextarea");
  if(ta)ta.value=getScriptText();
}
function renderScriptLines(scrollToBottom){
  var list=document.getElementById("scriptList");
  var empty=document.getElementById("scriptEmpty");
  var count=document.getElementById("scriptCount");
  syncScriptBuffer();
  if(count)count.textContent=recordedScriptEvents.length+" 条";
  if(!list)return;
  list.querySelectorAll(".script-line").forEach(function(node){node.parentNode.removeChild(node)});
  if(empty)empty.style.display=recordedScriptEvents.length?"none":"flex";
  var frag=document.createDocumentFragment();
  recordedScriptEvents.forEach(function(event,idx){
    var line=scriptCode(event);
    if(!line)return;
    var row=document.createElement("div");
    row.className="script-line";
    if(idx===0)row.classList.add("first");
    if(idx===recordedScriptEvents.length-1)row.classList.add("last");
    row.setAttribute("role","listitem");

    var no=document.createElement("span");
    no.className="script-line-no";
    no.textContent=String(idx+1);
    row.appendChild(no);

    var codeEl=document.createElement("code");
    codeEl.className="script-code";
    codeEl.textContent=line;
    codeEl.title=line;
    row.appendChild(codeEl);

    var actions=document.createElement("div");
    actions.className="script-line-actions";
    var copy=document.createElement("button");
    copy.type="button";
    copy.className="script-line-button script-line-copy";
    copy.title="复制第 "+(idx+1)+" 条脚本";
    copy.textContent="复制";
    copy.addEventListener("click",function(){copyText(line,copy)});
    actions.appendChild(copy);

    var remove=document.createElement("button");
    remove.type="button";
    remove.className="script-line-button script-line-delete";
    remove.title="删除第 "+(idx+1)+" 条脚本";
    remove.textContent="删除";
    remove.addEventListener("click",function(){deleteRecordingEvent(event,remove)});
    actions.appendChild(remove);
    row.appendChild(actions);

    frag.appendChild(row);
  });
  list.appendChild(frag);
  if(scrollToBottom)list.scrollTop=list.scrollHeight;
}
function setRecordedScriptEvents(events,scrollToBottom){
  recordedScriptEvents=Array.isArray(events)?events.filter(function(event){return scriptCode(event)!==""}):[];
  renderScriptLines(scrollToBottom===true);
}
function appendRecordingEvent(event){
  if(!event||scriptCode(event)==="")return;
  var exists=recordedScriptEvents.some(function(item){return item.event_id===event.event_id});
  if(exists)return;
  recordedScriptEvents.push(event);
  renderScriptLines(true);
}
function deleteRecordingEvent(event,button){
  if(!S.serial||!event||event.event_id===undefined)return Promise.resolve();
  var serial=S.serial;
  var itemIndex=recordedScriptEvents.indexOf(event);
  button.disabled=true;
  return enqueueRecordingOperation(function(){
    return ap("/api/record/delete",{serial:serial,event_id:event.event_id});
  }).then(function(result){
    if(S.serial!==serial)return;
    setRecordedScriptEvents(result.events||[],false);
    showToast("已删除第 "+(itemIndex+1)+" 条脚本");
  }).catch(function(e){
    if(S.serial===serial)button.disabled=false;
    showToast("删除脚本失败: "+e.message);
  });
}
function clearScriptCode(){
  setRecordedScriptEvents([],false);
}
E.si.addEventListener("mousedown",function(e){
  if(!S.serial)return;
  if(canTouch()){
    e.preventDefault();S.touch=true;
    var c=i2d(e.clientX,e.clientY);
    S.touchStartPoint=c;S.lastTouchPoint=c;S.touchStartAt=Date.now();S.touchSnapshotId=S.h&&S.h.snapshot_id;
    _queueTouchEvent({type:"down",x:c.x,y:c.y});
  }
});
E.si.addEventListener("mousemove",function(e){
  if(!S.touch)return;
  e.preventDefault();
  if(S.mode==="live"&&S.interactionEnabled){
    var c=i2d(e.clientX,e.clientY);
    S.lastTouchPoint=c;
    _queueTouchEvent({type:"move",x:c.x,y:c.y});
  }
});
E.si.addEventListener("mouseup",function(e){
  if(!S.touch)return;
  e.preventDefault();
  var c=i2d(e.clientX,e.clientY);
  finishActiveGesture(c);
});
E.si.addEventListener("mouseleave",endActiveGesture);
window.addEventListener("mouseup",endActiveGesture);
window.addEventListener("blur",endActiveGesture);

var RECORD_DOUBLE_CLICK_INTERVAL_MS=300;
var RECORD_DOUBLE_CLICK_DISTANCE=24;
var _pendingRecordedClick=null;
var _pendingRecordedClickTimer=null;
function clearPendingRecordedClick(){
  if(_pendingRecordedClickTimer!==null){clearTimeout(_pendingRecordedClickTimer);_pendingRecordedClickTimer=null}
  _pendingRecordedClick=null;
}
function flushPendingRecordedClick(){
  if(!_pendingRecordedClick)return Promise.resolve();
  var pending=_pendingRecordedClick;
  clearPendingRecordedClick();
  return recordWebAction("click",pending.params);
}
function recordGestureAction(action,params){
  if(!S.recording)return Promise.resolve();
  if(action!=="click"){
    flushPendingRecordedClick();
    return recordWebAction(action,params);
  }
  var now=Date.now();
  var pending=_pendingRecordedClick;
  if(pending){
    var dx=params.x-pending.params.x,dy=params.y-pending.params.y;
    if(now-pending.finishedAt<=RECORD_DOUBLE_CLICK_INTERVAL_MS&&Math.sqrt(dx*dx+dy*dy)<=RECORD_DOUBLE_CLICK_DISTANCE){
      clearPendingRecordedClick();
      return recordWebAction("double_click",pending.params);
    }
    flushPendingRecordedClick();
  }
  _pendingRecordedClick={params:params,finishedAt:now};
  _pendingRecordedClickTimer=setTimeout(flushPendingRecordedClick,RECORD_DOUBLE_CLICK_INTERVAL_MS);
  return Promise.resolve();
}
function recordWebAction(action,params){
  if(!S.recording||!S.serial)return Promise.resolve();
  var serial=S.serial;
  return enqueueRecordingOperation(function(){
    return ap("/api/record/action",{serial:serial,action:action,params:params}).then(function(result){
      if(S.serial===serial&&result&&result.recorded&&result.event)appendRecordingEvent(result.event);
    });
  }).catch(function(e){
    if(S.serial===serial)ss("录制操作失败: "+e.message);
  });
}
function applyRecordingState(state){
  if(!state)return;
  var wasRecording=S.recording;
  S.recording=state.recording===true;
  setRecordedScriptEvents(state.events||[],false);
  if(S.recording)ensureRecordingOverlayData();
  if(wasRecording&&!S.recording&&!S.overlayEnabled){S.hov=null;renderOV()}
  updateControlUI();
  syncHierarchyPolling();
  if(state.error)ss("录制异常: "+state.error);
}
function pollRecordingState(){
  if(!S.serial||S.recordingPollBusy)return;
  var serial=S.serial;
  var requestId=S.recordingPollRequestId+1;
  S.recordingPollRequestId=requestId;
  S.recordingPollBusy=true;
  enqueueRecordingOperation(function(){
    return ag("/api/record/state?serial="+encodeURIComponent(serial));
  }).then(function(state){
    if(S.serial===serial&&S.recordingPollRequestId===requestId)applyRecordingState(state);
  }).catch(function(e){
    if(S.serial===serial&&S.recordingPollRequestId===requestId&&S.recording)ss("录制状态获取失败: "+e.message);
  }).then(function(){
    if(S.recordingPollRequestId===requestId)S.recordingPollBusy=false;
  });
}
function scheduleRecordingPoll(){
  if(S.recordingPollTimer)clearInterval(S.recordingPollTimer);
  S.recordingPollTimer=setInterval(function(){
    if(S.recording)pollRecordingState();
  },1000);
}
function startRecording(){
  if(!S.serial||S.mode!=="live")return Promise.reject(new Error("脚本录制需要实时投屏"));
  clearPendingRecordedClick();
  var serial=S.serial;
  S.recordingPollRequestId+=1;S.recordingPollBusy=false;
  return ap("/api/record/start",{serial:serial}).then(function(state){
    if(S.serial!==serial){
      if(state&&state.recording){
        enqueueRecordingOperation(function(){return ap("/api/record/stop",{serial:serial})}).catch(function(){});
      }
      return;
    }
    clearScriptCode();
    applyRecordingState(state);
    switchTab("recorder");
    ss(S.overlayEnabled?"脚本录制已开始 - 投屏、交互和 UI 框开关保持不变":"脚本录制已开始 - UI 框由录制临时显示，交互状态不变");
    pollRecordingState();
  });
}
function stopRecording(){
  if(!S.serial)return Promise.resolve();
  var serial=S.serial;
  flushPendingRecordedClick();
  S.recordingPollRequestId+=1;S.recordingPollBusy=false;
  return enqueueRecordingOperation(function(){
    return ap("/api/record/stop",{serial:serial});
  }).then(function(state){
    if(S.serial!==serial)return;
    applyRecordingState(state);
    ss(state.error?"录制已停止，但脚本生成存在异常":"脚本录制已停止");
  });
}
function setRecordingEnabled(enabled){
  if(enabled){
    return startRecording().catch(function(e){
      S.recording=false;if(!S.overlayEnabled){S.hov=null;renderOV()}updateControlUI();ss("启动录制失败: "+e.message);throw e;
    });
  }
  return stopRecording().catch(function(e){ss("停止录制失败: "+e.message);throw e});
}

// ===== Tab =====
document.querySelectorAll(".panel-tab").forEach(function(t){t.addEventListener("click",function(){
  switchTab(t.getAttribute("data-panel"));
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
  var initialScreenPct=storageNumber("uiviewer.screenWidthPct",isWideInspector()?34:30);
  sa.style.width=clamp(initialScreenPct,22,52)+"%";
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
    var newPct=clamp(startPct+dx/mainW*100,22,52);
    sa.style.width=newPct+"%";
    storeNumber("uiviewer.screenWidthPct",Math.round(newPct*10)/10);
    scheduleScreenRelayout();
    resizeXPathInput(document.getElementById("xpathValue"));
  });

  sp.addEventListener("pointerup",function(e){
    if(!dragging)return;
    dragging=false;
    sp.classList.remove("dragging");
    document.body.style.cursor="";
    document.body.style.userSelect="";
    try{sp.releasePointerCapture(e.pointerId)}catch(err){}
  });

  sp.addEventListener("pointercancel",function(){
    if(!dragging)return;
    dragging=false;
    sp.classList.remove("dragging");
    document.body.style.cursor="";
    document.body.style.userSelect="";
  });
})();

// ===== Inspector 内部分割线：仅宽屏三列模式调整控件树/详情宽度 =====
(function(){
  var sp=document.getElementById("innerSplitter");
  var cols=document.getElementById("inspectorColumns");
  if(!sp||!cols||!E.side)return;
  var dragging=false,startX=0,startPct=0;

  sp.addEventListener("pointerdown",function(e){
    if(!isWideInspector())return;
    dragging=true;
    startX=e.clientX;
    startPct=E.tc?E.tc.offsetWidth/cols.offsetWidth*100:storageNumber("uiviewer.treeWidthPct",42);
    sp.classList.add("dragging");
    document.body.style.cursor="col-resize";
    document.body.style.userSelect="none";
    try{sp.setPointerCapture(e.pointerId)}catch(err){}
    e.preventDefault();
    e.stopPropagation();
  });

  sp.addEventListener("pointermove",function(e){
    if(!dragging)return;
    var colsW=cols.offsetWidth;
    if(colsW<=0)return;
    var newPct=clamp(startPct+(e.clientX-startX)/colsW*100,INSPECTOR_TREE_MIN_PCT,detailAwareTreeMaxPct(colsW));
    applyInspectorTreeWidth(newPct);
    storeNumber("uiviewer.treeWidthPct",Math.round(newPct*10)/10);
    scheduleScreenRelayout();
    resizeXPathInput(document.getElementById("xpathValue"));
  });

  function stopDrag(e){
    if(!dragging)return;
    dragging=false;
    sp.classList.remove("dragging");
    document.body.style.cursor="";
    document.body.style.userSelect="";
    if(e&&e.pointerId!==undefined){try{sp.releasePointerCapture(e.pointerId)}catch(err){}}
  }

  sp.addEventListener("pointerup",stopDrag);
  sp.addEventListener("pointercancel",stopDrag);
})();

[E.tp,E.ap].forEach(function(panel){
  if(!panel)return;
  panel.addEventListener("contextmenu",function(event){event.preventDefault()});
});

window.addEventListener("resize",function(){
  switchTab(activePanel());
  scheduleScreenRelayout();
  resizeXPathInput(document.getElementById("xpathValue"));
});
(function(){
  var mr=document.getElementById("modeRecord");
  if(mr){
    mr.addEventListener("click",function(){
      if(!S.serial){ss("请先选择设备");return}
      var enabled=!S.recording;
      S.recordingBusy=true;updateControlUI();
      setRecordingEnabled(enabled).catch(function(){}).finally(function(){S.recordingBusy=false;updateControlUI()});
    });
  }
  var cp=document.getElementById("copyScriptBtn");
  if(cp){
    cp.addEventListener("click",function(){
      var text=getScriptText();
      if(text)copyText(text,cp);
      else showToast("暂无可复制的脚本");
    });
  }
  var cl=document.getElementById("clearScriptBtn");
  if(cl){
    cl.addEventListener("click",function(){
      if(!recordedScriptEvents.length){showToast("暂无可清空的脚本");return}
      if(!S.serial){showToast("请先选择设备");return}
      var serial=S.serial;
      cl.disabled=true;
      enqueueRecordingOperation(function(){
        return ap("/api/record/clear",{serial:serial});
      }).then(function(result){
        if(S.serial!==serial)return;
        setRecordedScriptEvents(result.events||[],false);
        showToast("录制脚本已清空");
      }).catch(function(e){
        showToast("清空脚本失败: "+e.message);
      }).then(function(){cl.disabled=false});
    });
  }
  renderScriptLines(false);
})();
syncLayoutState();
switchTab(activePanel());
loadDevices();updateControlUI();
})();
