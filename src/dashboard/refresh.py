"""Fixed CSP-authorized progressive enhancement; HTML remains server rendered."""
from base64 import b64encode
from hashlib import sha256

AUTO_REFRESH_SCRIPT = r"""(() => {
  const start = () => {
    let running = false;
    const dirty = new WeakSet();
    document.addEventListener('input', e => { if (e.target.form) dirty.add(e.target.form); });
    document.addEventListener('change', e => { if (e.target.form) dirty.add(e.target.form); });
    const key = n => {
      if (n.nodeType !== 1) return '';
      if (n.id) return n.tagName + '#' + n.id;
      if (n.tagName === 'FORM') return 'FORM:' + n.method + ':' +
        ['command_kind','thread_id','review_id','post_record_id','reconciliation_request_id'].map(k => n.elements.namedItem(k)?.value || '').join(':');
      if (n.tagName === 'DETAILS') return 'DETAILS:' + n.querySelector('summary')?.textContent;
      return '';
    };
    const protectedNode = n => n.nodeType === 1 &&
      ([...(n.matches('form') ? [n] : []), ...n.querySelectorAll('form')].some(f => dirty.has(f) || f.contains(document.activeElement)));
    const patch = (old, fresh) => {
      if (old.isEqualNode(fresh)) return;
      if (old.nodeType !== 1) { if (old.nodeValue !== fresh.nodeValue) old.nodeValue = fresh.nodeValue; return; }
      if (old.tagName === 'FORM' && (dirty.has(old) || old.contains(document.activeElement))) return;
      for (const a of [...old.attributes]) {
        if (a.name === 'open' && old.tagName === 'DETAILS') continue;
        if (!fresh.hasAttribute(a.name)) old.removeAttribute(a.name);
      }
      for (const a of fresh.attributes) {
        if (a.name === 'open' && old.tagName === 'DETAILS') continue;
        if (old.getAttribute(a.name) !== a.value) old.setAttribute(a.name, a.value);
      }
      let cursor = old.firstChild;
      for (const next of [...fresh.childNodes]) {
        const k = key(next);
        let match = k ? [...old.childNodes].find(n => key(n) === k) :
          (cursor && !key(cursor) && cursor.nodeType === next.nodeType && cursor.nodeName === next.nodeName ? cursor : null);
        if (match) {
          if (match !== cursor) old.insertBefore(match, cursor);
          patch(match, next);
          cursor = match.nextSibling;
        } else {
          const added = next.cloneNode(true);
          old.insertBefore(added, cursor);
        }
      }
      while (cursor) {
        const next = cursor.nextSibling;
        if (!protectedNode(cursor)) cursor.remove();
        else {
          // A draft whose target disappeared remains visible but cannot submit stale work.
          cursor.querySelectorAll('button').forEach(b => { b.disabled = true; b.title = 'Target changed; copy your draft and refresh.'; });
          if (!cursor.querySelector('[data-stale-draft]')) {
            const note = document.createElement('p');
            note.dataset.staleDraft = 'true';
            note.textContent = 'This target changed or left the view. Your draft is preserved; copy it before refreshing. Submission is disabled.';
            cursor.appendChild(note);
          }
        }
        cursor = next;
      }
    };
    const refresh = async () => {
      if (document.hidden || running) return;
      running = true;
      const indicator = document.getElementById('refresh-status');
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch('/snapshot' + location.search, {cache: 'no-store', signal: controller.signal});
        if (!response.ok) throw new Error('snapshot unavailable');
        const value = await response.json();
        if (typeof value.html !== 'string' || value.html.length > 8000000) throw new Error('snapshot too large');
        const incoming = new DOMParser().parseFromString(value.html, 'text/html').querySelector('main');
        if (!incoming) throw new Error('invalid snapshot');
        const focus = document.activeElement;
        const x = window.scrollX, y = window.scrollY;
        const anchor = [...document.querySelectorAll('main [id]')].find(n => n.getBoundingClientRect().top >= 0 && n.getBoundingClientRect().top < innerHeight);
        const top = anchor?.getBoundingClientRect().top;
        patch(document.querySelector('main'), incoming);
        if (focus?.isConnected && document.activeElement !== focus) focus.focus({preventScroll: true});
        window.scrollTo(x, anchor?.isConnected ? y + anchor.getBoundingClientRect().top - top : y);
        document.getElementById('refresh-status').textContent = 'Updated at ' + value.updated_at + ' · UTC';
      } catch (_) {
        if (indicator) indicator.textContent = 'Update unavailable; showing last snapshot. Retrying automatically.';
      } finally { clearTimeout(timeout); running = false; }
    };
    setInterval(refresh, 10000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();"""
AUTO_REFRESH_CSP = "'sha256-" + b64encode(sha256(AUTO_REFRESH_SCRIPT.encode()).digest()).decode() + "'"
