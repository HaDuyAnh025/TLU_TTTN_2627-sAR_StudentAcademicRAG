/*
 * dc-lite.js — tiny runtime that makes the exported design screens run offline.
 * It renders the <x-dc> template of a page using the page's `class Component extends DCLogic`.
 *
 * Template syntax (for readers / AI tools):
 *   {{ path }}                      dotted lookup into the object returned by renderVals()
 *   <sc-for list="{{ xs }}" as="x"> repeat children for each item (x, $index in scope)
 *   <sc-if value="{{ cond }}">      render children only when cond is truthy
 *   onClick="{{ fn }}"              click handler; onChange="{{ fn }}" = input/change handler
 *   <helmet>                        styles/links that belong in <head>
 *
 * URL options:  ?state={json}  seeds the initial state,  ?simulateError=true / ?errorDemo=Lỗi%20xóa  set props.
 * This file is a prototype helper only — it is NOT meant to be shipped in the real app.
 */
(function () {
  var HOLE = /\{\{\s*([\w$.]+)\s*\}\}/g;
  var WHOLE = /^\{\{\s*([\w$.]+)\s*\}\}$/;

  function lookup(scopes, p) {
    if (p === 'true') return true;
    if (p === 'false') return false;
    if (/^-?\d+(\.\d+)?$/.test(p)) return Number(p);
    var parts = p.split('.');
    for (var i = scopes.length - 1; i >= 0; i--) {
      var s = scopes[i];
      if (s && Object.prototype.hasOwnProperty.call(s, parts[0])) {
        var v = s[parts[0]];
        for (var j = 1; j < parts.length; j++) v = v == null ? undefined : v[parts[j]];
        return v;
      }
    }
    return undefined;
  }
  function str(v) { return v == null || v === false || typeof v === 'function' ? '' : String(v); }
  function holeName(attr) { var m = (attr || '').match(WHOLE); return m ? m[1] : null; }

  function eventFor(el, name) {
    if (name === 'onclick') return 'click';
    if (name === 'onchange') {
      var t = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
      if (t === 'select' || type === 'checkbox' || type === 'radio' || type === 'file' || type === 'date') return 'change';
      return 'input';
    }
    return name.slice(2);
  }

  function expand(node, scopes, out) {
    if (node.nodeType === 3) { out.push(document.createTextNode(node.nodeValue.replace(HOLE, function (_, p) { return str(lookup(scopes, p)); }))); return; }
    if (node.nodeType !== 1) return;
    var tag = node.tagName.toLowerCase();
    if (tag === 'sc-for') {
      var list = lookup(scopes, holeName(node.getAttribute('list'))) || [];
      var as = node.getAttribute('as');
      list.forEach(function (item, i) {
        var sc = {}; sc[as] = item; sc.$index = i;
        node.childNodes.forEach(function (ch) { expand(ch, scopes.concat([sc]), out); });
      });
      return;
    }
    if (tag === 'sc-if') {
      if (lookup(scopes, holeName(node.getAttribute('value')))) node.childNodes.forEach(function (ch) { expand(ch, scopes, out); });
      return;
    }
    var el = node.namespaceURI === 'http://www.w3.org/1999/xhtml' ? document.createElement(tag) : document.createElementNS(node.namespaceURI, node.localName);
    var late = {};
    Array.prototype.forEach.call(node.attributes, function (a) {
      var name = a.name;
      if (name.indexOf('hint-') === 0) return;
      var hn = holeName(a.value);
      if (/^on[a-z]+$/i.test(name)) {
        var fn = hn ? lookup(scopes, hn) : null;
        if (typeof fn === 'function') el.addEventListener(eventFor(node, name.toLowerCase()), fn);
        return;
      }
      if (hn) {
        var v = lookup(scopes, hn);
        if (name === 'value' || name === 'checked') { late[name] = v; return; }
        if (typeof v === 'boolean') { if (name.indexOf('aria-') === 0) el.setAttribute(name, String(v)); else if (v) el.setAttribute(name, ''); return; }
        if (v == null || typeof v === 'function') return;
        el.setAttribute(name, String(v));
        return;
      }
      var val = a.value.replace(HOLE, function (_, p) { return str(lookup(scopes, p)); });
      if (name === 'value' && (tag === 'input' || tag === 'textarea' || tag === 'select')) { late.value = val; return; }
      if (name === 'href' && /\.dc\.html$/.test(val)) val = window.DC_ROUTES && window.DC_ROUTES[val] || val.replace(/\.dc\.html$/, '.html');
      el.setAttribute(name, val);
    });
    var kids = [];
    node.childNodes.forEach(function (ch) { expand(ch, scopes, kids); });
    kids.forEach(function (k) { el.appendChild(k); });
    if ('value' in late) el.value = late.value == null ? '' : late.value;
    if ('checked' in late) el.checked = !!late.checked;
    out.push(el);
  }

  function boot() {
    var xdc = document.querySelector('x-dc');
    var script = document.querySelector('script[data-dc-script]');
    if (!xdc || !script) return;
    var helmet = xdc.querySelector('helmet');
    if (helmet) { Array.prototype.slice.call(helmet.children).forEach(function (c) { document.head.appendChild(c); }); helmet.remove(); }
    var tpl = xdc.cloneNode(true);
    var root = document.createElement('div');
    root.id = 'dc-root';
    xdc.replaceWith(root);

    var decl = JSON.parse(script.getAttribute('data-props') || '{}');
    var props = {};
    Object.keys(decl).forEach(function (k) { if (k[0] !== '$' && decl[k] && 'default' in decl[k]) props[k] = decl[k].default; });
    var q = new URLSearchParams(location.search);
    q.forEach(function (v, k) { if (k === 'state') return; props[k] = v === 'true' ? true : v === 'false' ? false : v; });
    var seed = null;
    try { if (q.get('state')) seed = JSON.parse(q.get('state')); } catch (e) { console.warn('bad ?state', e); }

    function DCLogic() {}
    var scheduled = false, comp;
    DCLogic.prototype.setState = function (patch) {
      this.state = Object.assign({}, this.state, typeof patch === 'function' ? patch(this.state, this.props) : patch);
      if (!scheduled) { scheduled = true; Promise.resolve().then(function () { scheduled = false; render(); }); }
    };
    DCLogic.prototype.forceUpdate = function () { render(); };
    var Component = new Function('DCLogic', script.textContent + '\nreturn Component;')(DCLogic);
    comp = new Component();
    comp.props = props;
    comp.state = seed ? Object.assign({}, seed) : undefined;

    function render() {
      var a = document.activeElement, focusId = a && a.id, s0 = null, s1 = null;
      try { if (focusId && 'selectionStart' in a) { s0 = a.selectionStart; s1 = a.selectionEnd; } } catch (e) {}
      var vals = comp.renderVals();
      var out = [];
      tpl.childNodes.forEach(function (ch) { expand(ch, [vals], out); });
      root.replaceChildren.apply(root, out);
      if (focusId) {
        var f = document.getElementById(focusId);
        if (f) { f.focus(); try { if (s0 != null) f.setSelectionRange(s0, s1); } catch (e) {} }
      }
    }
    render();
    if (comp.componentDidMount) comp.componentDidMount();
    window.addEventListener('beforeunload', function () { if (comp.componentWillUnmount) comp.componentWillUnmount(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
