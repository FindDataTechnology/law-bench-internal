'use strict';
// law-query-api: the public-facing law retrieval service.
// POST /v1/search {query, top_k?, filters?, group_by_law?, expand?}
// GET  /v1/laws/{law_id}
// Reads only Qdrant + embedding-svc; no API keys, no billing logic (gateway's job).
const http = require('http');

const CFG = {
  embed: (process.env.EMBED || 'http://embedding-svc.law-rag:6100').replace(/\/$/, ''),
  qdrant: (process.env.QDRANT || 'http://100.64.0.15:6333').replace(/\/$/, ''),
  collection: process.env.COLLECTION || 'law_chunks_v2',
  port: Number(process.env.PORT || 6200),
};

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function embedQuery(text) {
  for (let a = 1; a <= 3; a++) {
    try {
      const r = await fetch(`${CFG.embed}/embed`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: text }),
        signal: AbortSignal.timeout(20000),
      });
      if (!r.ok) throw new Error('embed ' + r.status);
      return (await r.json()).embeddings[0];
    } catch (e) { if (a === 3) throw e; await sleep(500 * a); }
  }
}

async function qdrant(path, body) {
  const r = await fetch(`${CFG.qdrant}${path}`, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(20000),
  });
  const j = await r.json();
  if (!r.ok) throw new Error('qdrant ' + r.status + ' ' + JSON.stringify(j).slice(0, 120));
  return j.result !== undefined ? j.result : j;
}

// ---------- citation parsing: "民法典第1085条" -> {lawHint:'民法典', article:1085} ----------
const CN_NUM = { 零: 0, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
function cnToInt(s) {
  if (/^\d+$/.test(s)) return Number(s);
  let total = 0, section = 0, num = 0;
  for (const ch of s) {
    if (ch in CN_NUM) { num = CN_NUM[ch]; }
    else if (ch === '十') { section += (num || 1) * 10; num = 0; }
    else if (ch === '百') { section += (num || 1) * 100; num = 0; }
    else if (ch === '千') { section += (num || 1) * 1000; num = 0; }
    else if (ch === '万') { section = (section + num) * 10000; num = 0; total += section; section = 0; }
  }
  return total + section + num;
}
function intToCn(n) {
  const digits = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九'];
  if (n === 0) return '零';
  const units = ['', '十', '百', '千'];
  let s = '', str = String(n), zero = false;
  for (let i = 0; i < str.length; i++) {
    const d = Number(str[i]), pos = str.length - 1 - i;
    if (d === 0) { zero = true; continue; }
    if (zero) { s += '零'; zero = false; }
    s += digits[d] + units[pos];
  }
  return s.replace(/^一十/, '十');
}
function parseCitation(query) {
  // law hint = up to 12 chars before 第X条; article number in arabic or chinese numerals
  const m = query.match(/([\u4e00-\u9fa5A-Za-z《》]{2,16}?)第([0-9零一二三四五六七八九十百千]+)条/);
  if (!m) return null;
  const article = cnToInt(m[2]);
  if (!article || article > 9999) return null;
  // law hint cleanup: strip connectors; require >=2 meaningful chars
  let hint = m[1].replace(/[的关于及和]/g, '');
  if (hint.length < 2) return null;
  // strip common leading verbs
  hint = hint.replace(/.*(查询|看看|找|搜|检索)/, '');
  if (hint.length < 2) return null;
  return { hint, article };
}

async function resolveCitation(cite) {
  // candidate laws by title full-text match
  const found = await qdrant(`/collections/${CFG.collection}/points/scroll`, {
    filter: { must: [{ key: 'title', match: { text: cite.hint } }] },
    limit: 24, with_payload: ['title', 'law_id'], with_vector: false,
  });
  let lawIds = [...new Set(found.points.map(p => p.payload.law_id))];
  if (!lawIds.length) {
    // tokenizer often fails on short hints; resolve the canonical full title semantically
    try {
      const hits = await semanticSearch(cite.hint, 10, {});
      lawIds = [...new Set(hits.filter(h => h.payload.title.includes(cite.hint)).map(h => h.payload.law_id))];
    } catch (e) { /* keep empty */ }
  }
  if (!lawIds.length) return null;
  const cnArticle = intToCn(cite.article);
  const wantArabic = new RegExp('^\\s*第' + cite.article + '条');
  const wantCn = new RegExp('^\\s*第' + cnArticle + '条');
  // check each candidate law's chunks (prefer most-voted title match = first lawIds)
  for (const lawId of lawIds.slice(0, 8)) {
    let offset = null, matched = null;
    for (let i = 0; i < 12; i++) {
      const body = { filter: { must: [{ key: 'law_id', match: { value: lawId } }] }, limit: 256, with_payload: true, with_vector: false };
      if (offset !== null) body.offset = offset;
      const page = await qdrant(`/collections/${CFG.collection}/points/scroll`, body);
      for (const p of page.points) {
        if (wantArabic.test(p.payload.chunk_text) || wantCn.test(p.payload.chunk_text)) { matched = p; break; }
      }
      if (matched || !page.next_page_offset) break;
      offset = page.next_page_offset;
    }
    if (matched) return matched;
  }
  return null;
}

async function semanticSearch(query, topK, filter) {
  const vec = await embedQuery(query);
  const body = { vector: vec, limit: Math.min(200, topK * 6), with_payload: true, with_vector: false };
  if (filter && Object.keys(filter).length) {
    body.filter = { must: Object.entries(filter).map(([k, v]) => ({ key: k, match: { value: v } })) };
  }
  const hits = await qdrant(`/collections/${CFG.collection}/points/search`, body);
  return hits;
}

async function expandChunk(lawId, chunkNo, each = 1) {
  const body = {
    filter: { must: [
      { key: 'law_id', match: { value: lawId } },
      { key: 'chunk_no', range: { gte: chunkNo - each, lte: chunkNo + each } },
    ] },
    limit: 2 * each + 1, with_payload: true, with_vector: false,
  };
  const r = await qdrant(`/collections/${CFG.collection}/points/scroll`, body);
  return r.points.sort((a, b) => a.payload.chunk_no - b.payload.chunk_no);
}

async function handleSearch(q) {
  const { query, top_k = 10, filters = {}, group_by_law = true, expand = 0 } = q;
  if (!query || typeof query !== 'string' || !query.trim()) throw new Error('query required');
  const topK = Math.max(1, Math.min(50, Number(top_k) || 10));
  const exp = Math.max(0, Math.min(2, Number(expand) || 0));

  let exact = null;
  const cite = parseCitation(query);
  if (cite) {
    try { exact = await resolveCitation(cite); } catch (e) { /* fall back to semantic */ }
  }
  const hits = await semanticSearch(query, topK, filters);

  const results = [];
  const seenLaws = new Set();
  for (const h of hits) {
    const p = h.payload;
    if (group_by_law) {
      if (seenLaws.has(p.law_id)) continue;
      seenLaws.add(p.law_id);
    }
    if (exact && exact.payload.law_id === p.law_id && exact.payload.chunk_no === p.chunk_no) continue; // avoid dup of exact hit
    results.push({
      law_id: p.law_id, title: p.title, category: p.category, publish: p.publish,
      law_status: p.law_status, law_type: p.law_type, chunk_no: p.chunk_no,
      chunk_text: p.chunk_text, score: Number(h.score.toFixed(4)), exact: false,
    });
    if (results.length >= topK) break;
  }
  if (exp > 0) {
    for (const r of results) {
      try { r.context = (await expandChunk(r.law_id, r.chunk_no, exp)).map(c => c.payload.chunk_text); } catch (e) { /* optional */ }
    }
  }
  const out = { query, top_k: topK, filters, results };
  if (exact) {
    const p = exact.payload;
    out.results.unshift({
      law_id: p.law_id, title: p.title, category: p.category, publish: p.publish,
      law_status: p.law_status, law_type: p.law_type, chunk_no: p.chunk_no,
      chunk_text: p.chunk_text, score: 1, exact: true,
    });
    out.results = out.results.slice(0, topK);
  }
  return out;
}

async function handleLaw(id) {
  // payload law_id is stored as STRING (pg bigint export); match raw without numeric coercion
  const mk = extra => ({ filter: { must: [{ key: 'law_id', match: { value: id } }] }, limit: 256, with_payload: true, with_vector: false, order_by: { key: 'chunk_no', ascending: true }, ...extra });
  const first = await qdrant(`/collections/${CFG.collection}/points/scroll`, mk({}));
  if (!first.points.length) return null;
  let points = first.points, offset = first.next_page_offset;
  while (offset) {
    const page = await qdrant(`/collections/${CFG.collection}/points/scroll`, mk({ offset }));
    points = points.concat(page.points);
    offset = page.next_page_offset;
  }
  points.sort((a, b) => a.payload.chunk_no - b.payload.chunk_no);
  const head = points[0].payload;
  return {
    law_id: Number(id), title: head.title, category: head.category, publish: head.publish,
    law_status: head.law_status, law_type: head.law_type,
    content: points.map(p => p.payload.chunk_text).join('\n'),
    chunks: points.length,
  };
}

const server = http.createServer((req, res) => {
  const json = (code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)); };
  // metering lives solely in the APISIX http-logger → meter-adapter path (spec: this service holds no billing logic)
  if (req.method === 'GET' && req.url === '/healthz') return json(200, { ok: true });
  if (req.method === 'POST' && req.url === '/v1/search') {
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', async () => {
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
        const out = await handleSearch(body);
        json(200, out);
      } catch (e) {
        if (String(e.message).includes('embed')) return json(503, { error: 'embedding unavailable' });
        if (String(e.message).includes('qdrant')) return json(503, { error: 'vector store unavailable' });
        json(400, { error: String(e.message || e).slice(0, 160) });
      }
    });
    return;
  }
  const lawMatch = req.url.match(/^\/v1\/laws\/(\d+)$/);
  if (req.method === 'GET' && lawMatch) {
    handleLaw(lawMatch[1]).then(r => { return r ? json(200, r) : json(404, { error: 'law not found' }); })
      .catch(e => json(503, { error: String(e.message || e).slice(0, 120) }));
    return;
  }
  json(404, { error: 'not found' });
});
server.listen(CFG.port, () => console.log('law-query-api on :' + CFG.port));
