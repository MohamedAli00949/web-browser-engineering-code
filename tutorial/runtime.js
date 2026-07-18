console = { log: function (x) { call_python("log", x); } }

function Node(handle) { this.handle = handle; }

Node.prototype.getAttribute = function (attr) {
  return call_python("getAttribute", this.handle, attr);
}

Object.defineProperty(Node.prototype, "innerHTML", {
  set: function (html) {
    call_python("innerHTML", this.handle, html.toString());
  }
});

Object.defineProperty(Node.prototype, 'style', {
  set: function (s) {
    call_python("style_set", this.handle, s.toString());
  }
});


LISTENERS = {}
Node.prototype.addEventListener = function (type, listener) {
  if (!LISTENERS[this.handle]) LISTENERS[this.handle] = {};
  var obj = LISTENERS[this.handle];
  if (!obj[type]) obj[type] = [];
  var list = obj[type];
  list.push(listener);
}

Node.prototype.dispatchEvent = function (evt) {
  var handle = this.handle;
  var type = evt.type;
  var list = (LISTENERS[handle] && LISTENERS[handle][type]) || [];
  for (var i = 0; i < list.length; i++) {
    list[i].call(this, evt);
  }

  return evt.do_default;
}

document = {
  querySelectorAll: function (s) {
    var handles = call_python("querySelectorAll", s);
    return handles.map(function (h) { return new Node(h); });
  }
}


function Event(type) {
  this.type = type
  this.do_default = true;
}

Event.prototype.preventDefault = function () {
  this.do_default = false;
}

function XMLHttpRequest() { }
XMLHttpRequest.prototype.open = function (method, url, is_async) {
  if (is_async) throw Error("Asynchronous XHR is not supported");
  this.method = method;
  this.url = url;
}

XMLHttpRequest.prototype.send = function (body) {
  this.responseText = call_python("XMLHttpRequest_send",
    this.method, this.url, body);
}

SET_TIMEOUT_REQUESTS = {}

function setTimeout(callback, time_delta) {
  var handle = Object.keys(SET_TIMEOUT_REQUESTS).length;
  SET_TIMEOUT_REQUESTS[handle] = callback;
  call_python("setTimeout", handle, time_delta);
}

function __runSetTimeout(handle) {
  var callback = SET_TIMEOUT_REQUESTS[handle]
  callback();
}

XML_REQUESTS = {}

function XMLHttpRequest() {
  this.handle = Object.keys(XML_REQUESTS).length;

  XML_REQUESTS[this.handle] = this;
}

XMLHttpRequest.prototype.open = function (method, url, is_async) {
  this.is_async = is_async;
  this.method = method;
  this.url = url;
}

XMLHttpRequest.prototype.send = function (body) {
  this.responseText = call_python("XMLHttpRequest_send",
    this.method, this.url, body, this.is_async, this.handle);
}

function __runXHROnload(body, handle) {
  var obj = XHR_REQUESTS[handle];
  var evt = new Event("load");
  obj.responseText = body;
  if (obj.onload)
    obj.onload(evt);
}

RAF_LISTENERS = []

function requestAnimationFrame(callback) {
  RAF_LISTENERS.push(callback);
  call_python("requestAnimationFrame");
}

function __runRAFHandlers() {
  var handlers_copy = RAF_LISTENERS;
  RAF_LISTENERS = [];
  for (var i = 0; i < handlers_copy.length; i++) {
    handlers_copy[i]();
  }
}
