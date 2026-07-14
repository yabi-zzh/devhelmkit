// UIViewer live-frame geometry
(function(root){
"use strict";

var DEFAULT_LIVE_SCALE=0.5;
var DEFAULT_SIZE_TOLERANCE=2;

function positiveNumber(value){
  var number=Number(value);
  return Number.isFinite(number)&&number>0?number:0;
}

function sourceRect(width,height){
  return {left:0,top:0,width:width,height:height};
}

function deriveEffectiveViewport(input){
  input=input||{};
  var rawWidth=positiveNumber(input.rawWidth);
  var rawHeight=positiveNumber(input.rawHeight);
  if(!rawWidth||!rawHeight)return null;

  var displayWidth=positiveNumber(input.displayWidth)||rawWidth;
  var displayHeight=positiveNumber(input.displayHeight)||rawHeight;
  var scale=positiveNumber(input.scale)||DEFAULT_LIVE_SCALE;
  var tolerance=positiveNumber(input.tolerance)||DEFAULT_SIZE_TOLERANCE;
  var expectedWidth=Math.round(displayWidth*scale);
  var expectedHeight=Math.round(displayHeight*scale);
  var isLive=input.mode==="live";
  var heightMatches=Math.abs(rawHeight-expectedHeight)<=tolerance;
  var isVerified=isLive&&heightMatches&&rawWidth>=expectedWidth;
  var content=isVerified
    ?sourceRect(Math.min(rawWidth,expectedWidth),Math.min(rawHeight,expectedHeight))
    :sourceRect(rawWidth,rawHeight);

  return {
    rawWidth:rawWidth,
    rawHeight:rawHeight,
    displayWidth:displayWidth,
    displayHeight:displayHeight,
    expectedWidth:expectedWidth,
    expectedHeight:expectedHeight,
    contentRect:content,
    verified:isVerified,
    sourcePixelsPerDevice:{
      x:content.width/displayWidth,
      y:content.height/displayHeight
    },
    devicePixelsPerSource:{
      x:displayWidth/content.width,
      y:displayHeight/content.height
    }
  };
}

function createViewportTransform(viewport,domWidth,domHeight){
  if(!viewport||!viewport.contentRect)return null;
  var width=positiveNumber(domWidth);
  var height=positiveNumber(domHeight);
  var source=viewport.contentRect;
  if(!width||!height||!source.width||!source.height)return null;

  var sourceToDomX=width/source.width;
  var sourceToDomY=height/source.height;
  var sourcePerDevice=viewport.sourcePixelsPerDevice;
  var deviceToDomX=sourcePerDevice.x*sourceToDomX;
  var deviceToDomY=sourcePerDevice.y*sourceToDomY;

  return {
    width:width,
    height:height,
    deviceToDomX:deviceToDomX,
    deviceToDomY:deviceToDomY,
    deviceToSource:function(x,y){
      return {
        x:source.left+x*sourcePerDevice.x,
        y:source.top+y*sourcePerDevice.y
      };
    },
    sourceToDevice:function(x,y){
      return {
        x:(x-source.left)*viewport.devicePixelsPerSource.x,
        y:(y-source.top)*viewport.devicePixelsPerSource.y
      };
    },
    sourceToDom:function(x,y){
      return {
        x:(x-source.left)*sourceToDomX,
        y:(y-source.top)*sourceToDomY
      };
    },
    domToSource:function(x,y){
      return {
        x:source.left+x/sourceToDomX,
        y:source.top+y/sourceToDomY
      };
    },
    deviceToDom:function(x,y){
      var sourcePoint=this.deviceToSource(x,y);
      return this.sourceToDom(sourcePoint.x,sourcePoint.y);
    },
    domToDevice:function(x,y){
      var sourcePoint=this.domToSource(x,y);
      return this.sourceToDevice(sourcePoint.x,sourcePoint.y);
    }
  };
}

var api=Object.freeze({
  DEFAULT_LIVE_SCALE:DEFAULT_LIVE_SCALE,
  DEFAULT_SIZE_TOLERANCE:DEFAULT_SIZE_TOLERANCE,
  deriveEffectiveViewport:deriveEffectiveViewport,
  createViewportTransform:createViewportTransform
});

if(root)root.UiViewerGeometry=api;
if(typeof module!=="undefined"&&module.exports)module.exports=api;
})(typeof globalThis!=="undefined"?globalThis:this);