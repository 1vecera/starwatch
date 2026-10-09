import React, { useState } from 'react';
import Markdown from 'react-markdown';

const DRAFT_KEY = 'starwatch-product-draft-v1';
function readDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_KEY));
    return typeof draft?.markdown === 'string' && typeof draft?.baseVersion === 'string' ? draft : null;
  } catch { return null; }
}
function retainDraft(draft) {
  try {
    if (draft) localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    else localStorage.removeItem(DRAFT_KEY);
    return true;
  } catch { return false; }
}
function MarkdownView({ text, sources }) {
  const urlTransform = url => {
    if (/^https?:\/\//i.test(url)) {
      try { const parsed = new URL(url); return parsed.username || parsed.password ? '' : parsed.href; } catch { return ''; }
    }
    if (/^#[a-zA-Z0-9_-]+$/.test(url)) return url;
    try {
      const parsed = new URL(url, 'https://local.invalid/docs/product-state.md');
      if (parsed.origin !== 'https://local.invalid' || parsed.search || parsed.hash) return '';
      const source = sources.find(s => s.name === parsed.pathname.slice(1));
      return source ? `/api/source?id=${encodeURIComponent(source.id)}` : '';
    } catch { return ''; }
  };
  return <div className="product-markdown" data-testid="product-rendered"><Markdown skipHtml urlTransform={urlTransform} components={{
    a: ({ href, children }) => href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
    img: ({ alt }) => <span>{alt || 'Image reference'}</span>,
  }}>{text}</Markdown></div>;
}

export default function ProductPage({ document, sources, accept }) {
  const [draft, setDraft] = useState(readDraft), [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false), [notice, setNotice] = useState('');
  const changed = editing && draft?.baseVersion !== document.version;
  const update = value => { setDraft(value); if (!retainDraft(value) && value) setNotice('Browser storage is unavailable. Keep this tab open until saving to retain your draft.'); };
  const start = () => { setNotice(''); if (!draft) update({ markdown: document.markdown, baseVersion: document.version }); setEditing(true); };
  const save = async e => {
    e.preventDefault();
    if (saving || changed) return;
    setSaving(true); setNotice('Saving…');
    try {
      const response = await fetch('/api/control', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ op: 'product.save', actor: 'Daniel', base_version: draft.baseVersion, markdown: draft.markdown }),
      });
      const result = await response.json();
      if (result.state) accept(result.state);
      if (response.status === 409) { setNotice('The file changed. Your draft is preserved; review the latest version below.'); return; }
      if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to save product page');
      update(null); setEditing(false); setNotice('Saved to docs/product-state.md. Previous text retained for recovery.');
    } catch (error) { setNotice(error.message); } finally { setSaving(false); }
  };
  return <section className="product-page" aria-label="Product one-pager" data-testid="product-page">
    <div className="section-head"><div><p className="eyebrow">THE PRODUCT · ONE MAINTAINED PAGE</p><h2>Product specification</h2></div>{!editing && <button className="secondary" data-testid="product-edit" disabled={!document.editable} onClick={start}>{draft ? 'Resume Markdown draft' : 'Edit Markdown'}</button>}</div>
    {!document.editable && <p role="alert">{document.error} The file has been preserved.</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {editing ? <form onSubmit={save}>
      {changed && <div className="conflict" data-testid="product-conflict" role="alert"><strong>The product file changed while you were editing.</strong><p>Your draft is intact. Read the current file before choosing the version to save.</p><details open><summary>Latest saved Markdown</summary><textarea aria-label="Latest saved product Markdown" value={document.markdown} readOnly rows={10} /></details><div className="toolbar"><button type="button" className="secondary" disabled={saving || !document.editable} onClick={() => { update({ ...draft, baseVersion: document.version }); setNotice('Latest version reviewed. Your draft is ready for an explicit save.'); }}>I reviewed latest; keep my draft</button><button type="button" className="secondary" disabled={saving || !document.editable} onClick={() => { if (window.confirm('Replace your retained draft with the latest saved Markdown?')) update({ markdown: document.markdown, baseVersion: document.version }); }}>Use latest text</button></div></div>}
      <div className="actions"><span className="caption">Draft stays in this tab; browser storage keeps it across reloads when available. Saves update the exact local file.</span><div className="toolbar"><button type="button" className="secondary" disabled={saving} onClick={() => setEditing(false)}>Close · keep draft</button><button type="button" className="secondary" disabled={saving} onClick={() => { if (window.confirm('Discard this local Markdown draft? The saved file will stay unchanged.')) { update(null); setEditing(false); } }}>Discard draft</button><button data-testid="product-save" disabled={saving || changed || !document.editable}>Save product page</button></div></div>
      <div className="product-edit-grid"><label className="field"><span>Product Markdown</span><textarea aria-label="Product Markdown" data-testid="product-markdown-input" value={draft.markdown} onChange={e => update({ ...draft, markdown: e.target.value })} rows={25} disabled={saving} maxLength={48000} /></label><div><p className="caption">Draft preview</p><MarkdownView text={draft.markdown} sources={sources} /></div></div>

    </form> : <MarkdownView text={document.exists ? document.markdown : 'The product page has not been written yet.'} sources={sources} />}
  </section>;
}
