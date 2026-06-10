console = { log: function (x) { call_python("log", x); } }

function Node(handle) { this.handle = handle; }

Node.prototype.getAttribute = function (attr) {
  return call_python("getAttribute", this.handle, attr);
}

Object.defineProperty(Node.prototype, "innerHTML", {
  set: function (html) {
    call_python("innerHTML", this.handle, html.toString());
  }
})

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
