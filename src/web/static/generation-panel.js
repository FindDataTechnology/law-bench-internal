// generation-panel.js — 「生成合同模板」面板交互
//
// 序列表单 → 按所选模式发请求：
//   A 母版骨架     只读，直接渲染母版 DOCX/PDF 下载链接（不发请求）。
//   B 标签组装     POST /api/contracts/{type}/generate            （同步 200）
//   C 存储 MinIO   POST /api/contracts/{type}/generate-stored     （同步 200）
//   D 批量组装     POST /api/contracts/{type}/generate-batch       （同步 200）
//   E 自愈流水线   POST /api/contracts/{type}/pipeline             （202 + 轮询）
//   F 自动拒绝     POST /api/contracts/{type}/auto-reject          （202 + 轮询）
//   G LLM 重生成   POST /api/contracts/{type}/regenerate-template  （202 + 轮询）
//
// 异步模式拿到 202 + {job_id} 后轮询 GET /api/generation-jobs/{id}，每 3s 一次，
// 终态(completed/failed)停止。E/F/G 提交前弹确认框，说明各自改写的状态：
//   E/F → clauses 表 + pipeline_runs；F 还会拒绝不合格自定义条款；G → 全局 contracts.json。

(function () {
  'use strict';

  var panel = document.getElementById('generation-panel');
  if (!panel) return;
  var contractType = panel.getAttribute('data-contract-type') || '';
  var form = document.getElementById('generation-form');
  var submitBtn = document.getElementById('gen-submit');
  var statusEl = document.getElementById('gen-status');
  var resultEl = document.getElementById('gen-result');
  if (!form || !submitBtn || !statusEl || !resultEl) return;

  var POLL_MS = 3000;
  var MAX_POLLS = 200; // ~10 min 上限，防止无限轮询

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function setStatus(msg, kind) {
    statusEl.textContent = msg || '';
    var colors = { ok: 'var(--ok)', error: 'var(--danger)', muted: 'var(--muted)' };
    statusEl.style.color = colors[kind || 'muted'] || colors.muted;
  }

  function clearResult() { resultEl.innerHTML = ''; }

  function currentMode() {
    var checked = form.querySelector('input[name="mode"]:checked');
    return checked ? checked.value : 'A';
  }

  // 切换模式时显隐 mode 专属字段（D 的 tag_combinations；E/F 的 rubric/迭代等）。
  function refreshExtras() {
    var mode = currentMode();
    var dExtra = panel.querySelector('.gen-extra[data-mode="D"]');
    var efExtra = panel.querySelector('.gen-extra[data-mode="EF"]');
    if (dExtra) dExtra.style.display = (mode === 'D') ? '' : 'none';
    if (efExtra) efExtra.style.display = (mode === 'E' || mode === 'F') ? '' : 'none';
  }

  function parseIds() {
    var el = form.elements['custom_clause_ids'];
    var raw = (el && el.value || '').trim();
    if (!raw) return null;
    return raw.split(',').map(function (s) {
      return parseInt(s.trim(), 10);
    }).filter(function (n) { return Number.isInteger(n); });
  }

  // 共享字段：B/C/D/E/F/G 都用得到的部分。
  function sharedBody() {
    var body = {};
    var stance = form.elements['stance'].value;
    var scenario = (form.elements['scenario'].value || '').trim();
    var fmt = form.elements['format'].value;
    if (stance) body.stance = stance;
    if (scenario) body.scenario = scenario;
    var ids = parseIds();
    if (ids && ids.length) body.custom_clause_ids = ids;
    body.format = fmt;
    return body;
  }

  // E/F 的请求体：共享字段 + 流水线参数 + mode。
  function pipelineBody(mode) {
    var body = sharedBody();
    body.mode = mode;
    var rubric = (form.elements['rubric'].value || '').trim();
    var taskDesc = (form.elements['task_desc'].value || '').trim();
    var maxIt = parseInt(form.elements['max_iterations'].value, 10);
    var temp = parseFloat(form.elements['temperature'].value);
    if (rubric) body.rubric = rubric;
    if (taskDesc) body.task_desc = taskDesc;
    if (Number.isFinite(maxIt)) body.max_iterations = maxIt;
    if (Number.isFinite(temp)) body.temperature = temp;
    return body;
  }

  // D 的请求体：共享字段 + tag_combinations / enumerate_all + mode。
  function batchBody() {
    var body = sharedBody();
    body.mode = 'D';
    body.enumerate_all = form.elements['enumerate_all'].checked;
    var tcRaw = (form.elements['tag_combinations'].value || '').trim();
    if (tcRaw) {
      try {
        var parsed = JSON.parse(tcRaw);
        if (!Array.isArray(parsed)) throw new Error('不是数组');
        body.tag_combinations = parsed;
      } catch (e) {
        throw new Error('tag_combinations 不是合法的 JSON 数组：' + e.message);
      }
    }
    if (!body.enumerate_all && !(body.tag_combinations && body.tag_combinations.length)) {
      throw new Error('模式 D 需要填写 tag_combinations 或勾选「枚举全部组合」');
    }
    return body;
  }

  // E/F/G 确认文案：点明各自改写的状态。{N} 占位替换为实际迭代上限。
  var CONFIRM = {
    E: '将运行自愈流水线（生成→填充→评价→自愈，最多 {N} 次迭代），可能写入 clauses 表与 pipeline_runs。确认继续？',
    F: '将运行自动拒绝流水线：除自愈外，还会把累计被多次判定不合格的自定义条款标记为 rejected（clauses 表）。确认继续？',
    G: '将通过 LLM 重写该类型的母版正文，直接改写全局文件 src/contracts/data/contracts.json。确认继续？'
  };

  function downloadLink(href, label) {
    if (!href) return '';
    return '<a class="btn btn-sm" href="' + escapeHtml(href) +
      '" target="_blank" rel="noopener">' + escapeHtml(label) + '</a>';
  }

  // 同步模式(B/C/D)结果渲染：下载链接 + 摘要。
  function renderSyncResult(mode, data) {
    var html = '';
    if (mode === 'B') {
      html += '<div class="flash ok">组装完成。</div>';
      html += '<div class="toolbar">' +
        downloadLink(data.docx_url, '下载 DOCX') + downloadLink(data.pdf_url, '下载 PDF') + '</div>';
      if (data.diagnostics) {
        html += '<details><summary class="muted">诊断信息</summary><pre class="prompt-content">' +
          escapeHtml(JSON.stringify(data.diagnostics, null, 2)) + '</pre></details>';
      }
    } else if (mode === 'C') {
      if (data.docx_url || data.pdf_url) {
        var reused = data.reused ? '（复用已有 artifact）' : '';
        html += '<div class="flash ok">已存储到 MinIO' + reused + '。artifact #' +
          escapeHtml(data.artifact_id) + '</div>';
        html += '<div class="toolbar">' +
          downloadLink(data.docx_url, '下载 DOCX') + downloadLink(data.pdf_url, '下载 PDF') + '</div>';
      } else if (Array.isArray(data.artifacts)) {
        html += '<div class="flash ok">批量存储完成：' + (data.count || 0) +
          ' 个 artifact（新增 ' + (data.new || 0) + '，复用 ' + (data.reused || 0) +
          '，失败 ' + (data.failed || 0) + '）</div>';
        if (data.failed) {
          html += '<details><summary class="muted">失败明细</summary><pre class="prompt-content">' +
            escapeHtml(JSON.stringify(data.failures, null, 2)) + '</pre></details>';
        }
      } else {
        html += '<pre class="prompt-content">' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
      }
    } else if (mode === 'D') {
      html += '<div class="flash ok">批量组装：请求 ' + (data.total_requested || 0) +
        '，成功 ' + (data.success_count || 0) + '，失败 ' + (data.failure_count || 0) + '。</div>';
      (data.results || []).forEach(function (r) {
        var tags = r.tags ? JSON.stringify(r.tags) : '';
        if (r.success) {
          html += '<div class="toolbar"><span class="muted">' + escapeHtml(tags) + '</span>' +
            downloadLink(r.docx_url, 'DOCX') + downloadLink(r.pdf_url, 'PDF') + '</div>';
        } else {
          html += '<div class="flash error">' + escapeHtml(tags) + '：' + escapeHtml(r.error) + '</div>';
        }
      });
    } else {
      html += '<pre class="prompt-content">' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
    }
    resultEl.innerHTML = html;
  }

  // 异步模式(E/F/G)终态渲染：按 kind 渲染 result_ref 摘要。
  function renderJobResult(kind, ref, errMsg) {
    var html = '';
    if (errMsg) {
      html += '<div class="flash error">失败：' + escapeHtml(errMsg) + '</div>';
    } else if (kind === 'pipeline') {
      var pass = ref && ref.all_pass;
      html += '<div class="flash ' + (pass ? 'ok' : 'error') + '">自愈流水线完成：第 ' +
        (ref && ref.iteration != null ? ref.iteration : '-') + ' 次迭代，得分 ' +
        (ref && ref.score != null ? ref.score : '-') + '/' +
        (ref && ref.n_criteria != null ? ref.n_criteria : '-') +
        (pass ? '（全部通过）' : '（未全部通过）') + '</div>';
      if (ref && ref.eval_run_id != null) {
        html += '<div class="muted">eval_run_id: ' + escapeHtml(ref.eval_run_id) +
          ' · pipeline_run_id: ' + escapeHtml(ref.pipeline_run_id) + '</div>';
      }
    } else if (kind === 'auto_reject') {
      var pass2 = ref && ref.all_pass;
      html += '<div class="flash ' + (pass2 ? 'ok' : 'error') + '">自动拒绝流水线完成：第 ' +
        (ref && ref.iteration != null ? ref.iteration : '-') + ' 次迭代，得分 ' +
        (ref && ref.score != null ? ref.score : '-') +
        (pass2 ? '（全部通过）' : '') + '</div>';
      if (ref && ref.learn_applied != null) {
        html += '<div class="muted">自动拒绝条款数 learn_applied: ' +
          escapeHtml(ref.learn_applied) + '</div>';
      }
    } else if (kind === 'regenerate') {
      html += '<div class="flash ok">母版重生成完成（exit 0）。刷新页面可查看新正文。</div>';
      if (ref && ref.stdout) {
        html += '<details><summary class="muted">stdout（尾部 2000 字符）</summary>' +
          '<pre class="prompt-content">' + escapeHtml(String(ref.stdout).slice(-2000)) + '</pre></details>';
      }
    } else {
      html += '<pre class="prompt-content">' + escapeHtml(JSON.stringify(ref, null, 2)) + '</pre>';
    }
    resultEl.innerHTML = html;
  }

  // 轮询 job 状态直到终态或超时。
  function pollJob(jobId) {
    var n = 0;
    return new Promise(function (resolve, reject) {
      function tick() {
        fetch('/api/generation-jobs/' + jobId).then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        }).then(function (job) {
          n++;
          if (job.status === 'completed' || job.status === 'failed') {
            submitBtn.disabled = false;
            setStatus(job.status === 'completed' ? '完成。' : '失败。',
              job.status === 'completed' ? 'ok' : 'error');
            renderJobResult(job.kind, job.result_ref, job.error_message);
            resolve(job);
          } else if (n >= MAX_POLLS) {
            submitBtn.disabled = false;
            setStatus('轮询超时，请稍后刷新页面查看 job #' + jobId + '。', 'error');
            reject(new Error('poll timeout'));
          } else {
            setStatus('运行中…（' + job.status + '）');
            setTimeout(tick, POLL_MS);
          }
        }).catch(function (err) {
          submitBtn.disabled = false;
          setStatus('查询失败：' + err.message, 'error');
          reject(err);
        });
      }
      tick();
    });
  }

  // E/F/G：确认 → POST → 202 → 轮询。
  async function submitAsync(url, body, mode) {
    var msg = CONFIRM[mode].replace('{N}', String(body.max_iterations || 3));
    if (!window.confirm(msg)) {
      setStatus('已取消。');
      return;
    }
    submitBtn.disabled = true;
    setStatus('提交中…');
    clearResult();
    try {
      var r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (r.status !== 202) {
        var err1 = await r.json().catch(function () { return {}; });
        throw new Error((err1 && (err1.detail || err1.error)) || ('HTTP ' + r.status));
      }
      var data = await r.json();
      setStatus('已提交，job #' + data.job_id + '，轮询中…');
      await pollJob(data.job_id);
    } catch (err) {
      submitBtn.disabled = false;
      setStatus('错误：' + err.message, 'error');
      resultEl.innerHTML = '<div class="flash error">' + escapeHtml(err.message) + '</div>';
    }
  }

  // B/C/D：同步 POST → 200 → 渲染下载链接。
  async function submitSync(url, body, mode) {
    submitBtn.disabled = true;
    setStatus('生成中…');
    clearResult();
    try {
      var r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      var data = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        throw new Error((data && (data.detail || data.error)) || ('HTTP ' + r.status));
      }
      setStatus('完成。', 'ok');
      renderSyncResult(mode, data);
    } catch (err) {
      setStatus('错误：' + err.message, 'error');
      resultEl.innerHTML = '<div class="flash error">' + escapeHtml(err.message) + '</div>';
    } finally {
      submitBtn.disabled = false;
    }
  }

  // A：只读，直接渲染母版下载链接。
  function renderModeA() {
    clearResult();
    var base = '/contracts/' + encodeURIComponent(contractType) + '/download/';
    var html = '<div class="flash ok">母版骨架：点击下载。</div>';
    html += '<div class="toolbar">' +
      downloadLink(base + 'docx', '下载 DOCX') + downloadLink(base + 'pdf', '下载 PDF') + '</div>';
    resultEl.innerHTML = html;
    setStatus('');
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var mode = currentMode();
    var base = '/api/contracts/' + encodeURIComponent(contractType);
    try {
      if (mode === 'A') {
        renderModeA();
      } else if (mode === 'B') {
        await submitSync(base + '/generate', sharedBody(), 'B');
      } else if (mode === 'C') {
        await submitSync(base + '/generate-stored', sharedBody(), 'C');
      } else if (mode === 'D') {
        await submitSync(base + '/generate-batch', batchBody(), 'D');
      } else if (mode === 'E') {
        await submitAsync(base + '/pipeline', pipelineBody('E'), 'E');
      } else if (mode === 'F') {
        await submitAsync(base + '/auto-reject', pipelineBody('F'), 'F');
      } else if (mode === 'G') {
        await submitAsync(base + '/regenerate-template', { mode: 'G' }, 'G');
      }
    } catch (err) {
      submitBtn.disabled = false;
      setStatus('错误：' + err.message, 'error');
      resultEl.innerHTML = '<div class="flash error">' + escapeHtml(err.message) + '</div>';
    }
  });

  // 切换模式时刷新专属字段显隐。
  Array.prototype.forEach.call(
    form.querySelectorAll('input[name="mode"]'),
    function (r) { r.addEventListener('change', refreshExtras); }
  );
  refreshExtras();
})();
