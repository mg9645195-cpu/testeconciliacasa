/**
 * BIORENAL 2026 — Aplicação Frontend Completa (6 Módulos + IndexedDB Mirror + Chart.js + Editor 1:N)
 * Fidelidade Contábil Absoluta: aritmética em centavos inteiros no cliente + Decimal no servidor Python/SQLite.
 */

const STATE = {
  bootstrap: null,
  periodo: 'ALL',
  regime: 'CAIXA',
  fornecedor: '',
  categoria: '',
  activeTab: 'mod-dashboard',
  filaSubTab: 'nc',
  extratoOffset: 0,
  extratoLimit: 150,
  supplierName: '',
  supplierOffset: 0,
  cadastroPreview: null,
  currentEditLanc: null,
  charts: {},
};

// ============================================================================
// 1. PERSISTÊNCIA HÍBRIDA LOCAL (INDEXEDDB MIRROR + SQLITE BACKEND)
// ============================================================================
const LocalDB = {
  dbPromise: null,
  init() {
    if (!window.indexedDB) return Promise.resolve(null);
    if (this.dbPromise) return this.dbPromise;
    this.dbPromise = new Promise((resolve) => {
      const req = indexedDB.open('BiorenalConciliacao2026_DB', 1);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains('snapshots')) {
          db.createObjectStore('snapshots', { keyPath: 'key' });
        }
      };
      req.onsuccess = (e) => resolve(e.target.result);
      req.onerror = () => resolve(null);
    });
    return this.dbPromise;
  },
  async saveSnapshot(key, data) {
    const db = await this.init();
    if (!db) return;
    return new Promise((resolve) => {
      const tx = db.transaction('snapshots', 'readwrite');
      tx.objectStore('snapshots').put({ key, updatedAt: new Date().toISOString(), data });
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
    });
  },
};

// ============================================================================
// 2. FORMATADORES NUMÉRICOS E ARITMÉTICA DE CENTAVOS
// ============================================================================
function toCents(val) {
  if (val === null || val === undefined || val === '') return 0;
  const num = typeof val === 'number' ? val : parseFloat(String(val).replace(',', '.'));
  if (isNaN(num)) return 0;
  return Math.round(num * 100);
}

function fromCents(cents) {
  return Number((cents / 100).toFixed(2));
}

function fmtBRL(val) {
  const num = typeof val === 'number' ? val : parseFloat(val || 0);
  return num.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(val) {
  const num = typeof val === 'number' ? val : parseFloat(val || 0);
  return num.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%';
}

function fmtDateBR(iso) {
  if (!iso) return '-';
  const p = String(iso).slice(0, 10).split('-');
  if (p.length !== 3) return iso;
  return `${p[2]}/${p[1]}/${p[0]}`;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showToast(msg, isError = false) {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' error' : '');
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, 4200);
}

async function apiGet(url) {
  const res = await fetch(url);
  if (res.status === 401) { location.assign('/login.html'); throw new Error('Sessão encerrada.'); }
  const data = await res.json();
  if (!res.ok) throw new Error(data.erro || 'Erro na requisição');
  return data;
}

async function apiPost(url, body = {}) {
  await window.BioRenalAuth.ready;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.BioRenalAuth.csrf },
    body: JSON.stringify(body),
  });
  if (res.status === 401) { location.assign('/login.html'); throw new Error('Sessão encerrada.'); }
  const data = await res.json();
  if (!res.ok) throw new Error(data.erro || 'Erro ao processar operação');
  return data;
}

// ============================================================================
// 3. INICIALIZAÇÃO E NAVEGAÇÃO GLOBAL
// ============================================================================
document.addEventListener('DOMContentLoaded', async () => {
  initAppShell();
  try {
    await initBootstrap();
    await refreshAllActiveViews();
  } catch (err) {
    showToast('Erro ao inicializar: ' + err.message, true);
  }
});

async function initBootstrap() {
  const data = await apiGet('/api/bootstrap');
  STATE.bootstrap = data;
  await LocalDB.saveSnapshot('bootstrap', data);

  // Populate category filter
  const selCat = document.getElementById('flt-categoria');
  selCat.innerHTML = '<option value="">Todas as 12 Categorias</option>';
  Object.keys(data.plano_de_contas).forEach((cat) => {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = cat;
    selCat.appendChild(opt);
  });

  // Populate supplier filter
  const selForn = document.getElementById('flt-fornecedor');
  selForn.innerHTML = '<option value="">Todos os Fornecedores (Canônicos)</option>';
  (data.fornecedores_canonicos || []).forEach((f) => {
    const opt = document.createElement('option');
    opt.value = f;
    opt.textContent = f;
    selForn.appendChild(opt);
  });

  // Populate parameter inputs
  if (data.parametros) {
    document.getElementById('param-saldo-cc').value = data.parametros.saldo_inicial_cc || '0.00';
    document.getElementById('param-saldo-apl').value = data.parametros.saldo_inicial_aplicacao || '677285.67';
    document.getElementById('param-rend-apl').value = data.parametros.rendimentos_aplicacao || '0.00';
  }
}

function switchTab(tabId) {
  if (!document.getElementById(tabId)) return;
  const changed = STATE.activeTab !== tabId;
  STATE.activeTab = tabId;
  const activeButton = document.querySelector(`.nav-tab[data-target="${tabId}"]`);
  document.getElementById('active-module-name').textContent = activeButton.querySelector('.nav-label').textContent;
  document.querySelectorAll('.nav-tab').forEach((button) => {
    if (button === activeButton) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  document.querySelectorAll('.nav-tab').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-target') === tabId);
  });
  document.querySelectorAll('.module-section').forEach((sec) => {
    sec.classList.toggle('active', sec.id === tabId);
  });
  if (changed) window.scrollTo(0, 0);
  refreshAllActiveViews().catch((error) => showToast(error.message, true));
}

function setRegime(regime) {
  STATE.regime = regime;
  document.getElementById('flt-regime').value = regime;
  refreshAllActiveViews().catch((error) => showToast(error.message, true));
}

function onGlobalFilterChange() {
  STATE.periodo = document.getElementById('flt-periodo').value;
  if (/^(?:[1-9]|10)$/.test(STATE.periodo)) document.getElementById('dre-month').value = STATE.periodo;
  STATE.categoria = document.getElementById('flt-categoria').value;
  STATE.fornecedor = document.getElementById('flt-fornecedor').value;
  refreshAllActiveViews().catch((error) => showToast(error.message, true));
}

function resetGlobalFilters() {
  document.getElementById('flt-periodo').value = 'ALL';
  document.getElementById('flt-categoria').value = '';
  document.getElementById('flt-fornecedor').value = '';
  STATE.periodo = 'ALL';
  STATE.categoria = '';
  STATE.fornecedor = '';
  setRegime('CAIXA');
}

async function refreshAllActiveViews() {
  // Always load dashboard summary to keep header badges accurate
  await loadDashboard();
  if (STATE.activeTab === 'mod-fila') {
    await loadFilaConciliacao();
  } else if (STATE.activeTab === 'mod-extrato') {
    await loadExtratoTable(STATE.extratoOffset);
  } else if (STATE.activeTab === 'mod-dre') {
    await loadDreReport();
  } else if (STATE.activeTab === 'mod-tributos') {
    await loadTributos();
  } else if (STATE.activeTab === 'mod-programacao') {
    await loadProgramacao();
  } else if (STATE.activeTab === 'mod-prestadores') {
    await loadPrestadores();
  } else if (STATE.activeTab === 'mod-integridade' || STATE.activeTab === 'mod-fornecedores') {
    await loadIntegridadeModule();
  } else if (STATE.activeTab === 'mod-cadastros') {
    await loadCadastrosModule();
  }
}

function jumpToDivergencia() {
  if (!STATE.divergenceCount) {
    document.getElementById('ext-status-filter').value = 'ALL';
    showToast('Não há divergências de rateio ativas.');
    return;
  }
  document.getElementById('ext-status-filter').value = 'DIVERGENCIA';
  document.getElementById('ext-mes-filter').value = 'ALL';
  document.getElementById('ext-search').value = '';
  STATE.extratoOffset = 0;
  switchTab('mod-extrato');
}

// ============================================================================
// 4. MÓDULO 1: DASHBOARD EXECUTIVO E BI DA CLÍNICA
// ============================================================================
async function loadDashboard() {
  const qs = new URLSearchParams({
    periodo: STATE.periodo,
    regime: STATE.regime,
    fornecedor: STATE.fornecedor,
    categoria: STATE.categoria,
  });
  const data = await apiGet(`/api/dashboard?${qs.toString()}`);
  await LocalDB.saveSnapshot('dashboard', data);

  const k = data.kpis;
  const t = data.termometro_conciliacao;

  // Update Header & Tab Badges
  const hasDiv = t.movimentos_divergencia > 0;
  STATE.divergenceCount = t.movimentos_divergencia;
  const divergenceOption = document.querySelector('#ext-status-filter option[value="DIVERGENCIA"]');
  divergenceOption.hidden = !hasDiv;
  divergenceOption.disabled = !hasDiv;
  divergenceOption.textContent = `Com divergência (${t.movimentos_divergencia})`;
  document.querySelector('#ext-status-filter option[value="RATEIO_OK"]').textContent = `Rateio OK (${t.movimentos_rateio_ok})`;
  if (!hasDiv && document.getElementById('ext-status-filter').value === 'DIVERGENCIA') {
    document.getElementById('ext-status-filter').value = 'ALL';
  }
  document.getElementById('btn-hdr-divergencia').style.display = hasDiv ? 'inline-flex' : 'none';
  const divergenceIds = t.ids_divergencia || [];
  document.getElementById('hdr-divergencia-label').textContent = divergenceIds.length === 1
    ? divergenceIds[0] : `${t.movimentos_divergencia} divergência(s)`;
  document.getElementById('btn-hdr-divergencia').title = divergenceIds.join(', ');
  document.getElementById('global-anomaly-banner').style.display = divergenceIds.includes('BAN-00697') ? 'flex' : 'none';
  document.getElementById('hdr-pendentes-count').textContent = t.movimentos_nao_classificados;
  document.getElementById('badge-tab-fila').textContent = t.movimentos_nao_classificados + t.qtd_sugeridos;
  document.getElementById('badge-tab-extrato').textContent = t.total_movimentos;

  const alertasCount = (t.movimentos_divergencia > 0 ? 1 : 0)
    + (t.movimentos_nao_classificados > 0 ? 2 : 0)
    + (t.qtd_sugeridos > 0 ? 1 : 0)
    + (t.qtd_pendentes_ativos > 0 ? 1 : 0);
  const badgeInt = document.getElementById('badge-tab-integridade');
  badgeInt.textContent = alertasCount === 0 ? '100% OK' : `${alertasCount} Alertas`;
  badgeInt.className = 'tab-badge ' + (alertasCount === 0 ? 'badge-emerald' : 'badge-coral');

  // Render 4 Executive KPI Cards
  const kpiContainer = document.getElementById('dashboard-kpis');
  kpiContainer.innerHTML = `
    <div class="kpi-card border-teal">
      <div class="kpi-label">1. Saldo Atual em Conta Corrente (Extrato)</div>
      <div class="kpi-value">${fmtBRL(k.saldo_atual_cc)}</div>
      <div class="kpi-meta">
        <span><strong>Entradas Banco:</strong> <span class="num-pos">${fmtBRL(k.total_entradas_banco)}</span></span>
        <span><strong>Saídas Banco:</strong> <span class="num-neg">${fmtBRL(k.total_saidas_banco)}</span></span>
        <span><strong>Despesas Classificadas:</strong> ${fmtBRL(k.total_despesas_classificadas)}</span>
      </div>
    </div>

    <div class="kpi-card border-emerald">
      <div class="kpi-label">2. Geração de Caixa Operacional Pura (${STATE.regime})</div>
      <div class="kpi-value ${k.geracao_caixa_operacional >= 0 ? 'num-pos' : 'num-neg'}">${fmtBRL(k.geracao_caixa_operacional)}</div>
      <div class="kpi-meta">
        <span><strong>Repasses Contrato Estado MA:</strong> ${fmtBRL(k.receita_operacional_estado)}</span>
        <span><strong>Custos Assistenciais/Adm/Impostos:</strong> ${fmtBRL(k.despesa_operacional_pura)}</span>
        <span style="color:var(--teal-primary); font-weight:600;"><i data-lucide="check" aria-hidden="true"></i> Isolado de CDB, Empréstimo BNB, Sócios e Capex</span>
      </div>
    </div>

    <div class="kpi-card border-teal">
      <div class="kpi-label">3. Aplicações Financeiras (CDB DI BB) & Financiamento BNB</div>
      <div class="kpi-value">${fmtBRL(k.saldo_aplicacao_cdb)}</div>
      <div class="kpi-meta">
        <span><strong>Aplicado (Ago/26):</strong> ${fmtBRL(k.total_aplicado_ano)} | <strong>Resgatado Ano:</strong> ${fmtBRL(k.total_resgatado_ano)}</span>
        <span><strong>Fórmula Corrigida (PAINEL!A8):</strong> Saldo/Rend. Ant. (${fmtBRL(data.parametros.saldo_inicial_aplicacao)}) + Aplic. - Resgates</span>
        <span><strong>Financiamento BNB Liberado:</strong> ${fmtBRL(k.financiamento_bnb_entradas)}</span>
      </div>
    </div>

    <div class="kpi-card ${t.movimentos_divergencia > 0 ? 'border-coral' : (t.movimentos_nao_classificados > 0 ? 'border-amber' : 'border-emerald')}">
      <div class="kpi-label">4. Termômetro de Conciliação & Passivo Set/Out</div>
      <div class="kpi-value">${fmtPct(t.percentual_classificado)} <span style="font-size:13px; font-weight:600; color:var(--slate-500);">(${t.movimentos_rateio_ok}/${t.total_movimentos} OK)</span></div>
      <div class="progress-track">
        <div class="progress-fill" style="width:${t.percentual_classificado}%;"></div>
      </div>
      <div class="kpi-meta">
        <span><strong>Sem Classificação (${t.movimentos_nao_classificados} movs):</strong> <span class="num-neg">${fmtBRL(t.valor_pendente_classificacao)}</span></span>
        <span><strong>Sugeridos:</strong> ${t.qtd_sugeridos} | <strong>Pendentes/Revisar:</strong> ${t.qtd_pendentes_ativos} (${t.qtd_pendentes_planilha_bruto} brutos)</span>
        <span><strong>Divergências:</strong> <strong class="${t.movimentos_divergencia > 0 ? 'num-neg' : 'num-pos'}">${t.movimentos_divergencia}</strong> | <strong>Conciliados:</strong> ${t.movimentos_conciliados}/${t.total_movimentos} | <strong>Desconsiderados:</strong> ${t.movimentos_desconsiderados || 0}</span>
      </div>
    </div>
  `;

  renderDashboardCharts(data);
  updateChartTheme();
  renderPisoTable(data.piso_enfermagem);
  renderCurvaAbcTable(data.curva_abc_hd);
  renderPainelSociosTable(data.painel_socios);
  renderCapexCards(data.capex_financiamentos);
}

function renderDashboardCharts(data) {
  const ev = data.evolucao_mensal || [];
  const labels = ev.map((x) => x.mes_nome);

  // Chart 1: Fluxo Operacional Puro
  if (STATE.charts.fluxoOp) STATE.charts.fluxoOp.destroy();
  const ctx1 = document.getElementById('chart-fluxo-operacional').getContext('2d');
  STATE.charts.fluxoOp = new Chart(ctx1, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Repasse Estado MA (Receita Op.)',
          data: ev.map((x) => x.receita_operacional),
          backgroundColor: '#0056a6',
          borderRadius: 4,
        },
        {
          label: 'Custos Assistenciais/Adm/Impostos',
          data: ev.map((x) => x.despesa_operacional),
          backgroundColor: '#475569',
          borderRadius: 4,
        },
        {
          label: 'Não Classificado (Passivo Set/Out)',
          data: ev.map((x) => x.nao_classificado),
          backgroundColor: '#f59e0b',
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
      scales: {
        y: {
          ticks: { callback: (v) => 'R$ ' + (v / 1000).toFixed(0) + 'k' },
        },
      },
    },
  });

  // Chart 2: Evolução de Custos Críticos
  if (STATE.charts.custosCriticos) STATE.charts.custosCriticos.destroy();
  const ctx2 = document.getElementById('chart-custos-criticos').getContext('2d');
  STATE.charts.custosCriticos = new Chart(ctx2, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Materiais e Insumos HD',
          data: ev.map((x) => x.insumos_hd),
          borderColor: '#0056a6',
          backgroundColor: 'rgba(0, 86, 166, 0.1)',
          tension: 0.3,
          fill: true,
        },
        {
          label: 'Folha de Pagamento Funcionários',
          data: ev.map((x) => x.folha_pagamento),
          borderColor: '#2563eb',
          tension: 0.3,
        },
        {
          label: 'Impostos (ISS/PIS/COFINS/IRPJ/CSLL)',
          data: ev.map((x) => x.impostos),
          borderColor: '#d97706',
          tension: 0.3,
        },
        {
          label: 'Energia Elétrica (Equatorial)',
          data: ev.map((x) => x.energia_eletrica),
          borderColor: '#dc2626',
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
      scales: {
        y: {
          ticks: { callback: (v) => 'R$ ' + (v / 1000).toFixed(0) + 'k' },
        },
      },
    },
  });

  // Chart 3: Piso da Enfermagem (Pass-Through)
  const pm = data.piso_enfermagem.por_mes || [];
  if (STATE.charts.pisoEnf) STATE.charts.pisoEnf.destroy();
  const ctx3 = document.getElementById('chart-piso-enfermagem').getContext('2d');
  STATE.charts.pisoEnf = new Chart(ctx3, {
    type: 'bar',
    data: {
      labels: pm.map((x) => x.mes_nome),
      datasets: [
        {
          label: 'Entrada: Repasse Piso Enfermagem',
          data: pm.map((x) => x.entrada_total),
          backgroundColor: '#0056a6',
          borderRadius: 4,
        },
        {
          label: 'Saída: Folha Piso Enfermagem',
          data: pm.map((x) => x.saida_total),
          backgroundColor: '#e30620',
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
    },
  });

  // Chart 4: Curva ABC Materiais de Hemodiálise
  const abc = (data.curva_abc_hd.itens || []).slice(0, 8);
  if (STATE.charts.curvaAbc) STATE.charts.curvaAbc.destroy();
  const ctx4 = document.getElementById('chart-curva-abc').getContext('2d');
  STATE.charts.curvaAbc = new Chart(ctx4, {
    type: 'bar',
    data: {
      labels: abc.map((x) => x.subcategoria.length > 26 ? x.subcategoria.slice(0, 26) + '...' : x.subcategoria),
      datasets: [
        {
          label: 'Valor Acumulado (R$)',
          data: abc.map((x) => x.valor),
          backgroundColor: abc.map((x) => x.classe_abc === 'A' ? '#0056a6' : (x.classe_abc === 'B' ? '#e30620' : '#64748b')),
          borderRadius: 4,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
    },
  });
}

function renderPisoTable(pisoData) {
  const rows = pisoData.por_mes || [];
  const tbody = document.querySelector('#table-piso-enfermagem tbody');
  document.getElementById('piso-badges-summary').innerHTML = `
    <span class="tab-badge badge-emerald">Classificado: Entrada ${fmtBRL(pisoData.entrada_classificada_total)} = Saída ${fmtBRL(pisoData.saida_classificada_total)}</span>
  `;
  tbody.innerHTML = rows.map((r) => {
    const pend = r.entrada_pendente + r.saida_pendente;
    const badgeCls = pend > 0 ? 'badge-amber' : (Math.abs(r.saldo_retido) < 0.01 ? 'badge-emerald' : 'badge-coral');
    return `
      <tr>
        <td><strong>${r.mes_nome}/2026</strong></td>
        <td><code>${escapeHtml(r.competencias)}</code></td>
        <td class="num num-pos">${fmtBRL(r.entrada_classificada)}</td>
        <td class="num">${fmtBRL(r.saida_classificada)}</td>
        <td class="num ${pend > 0 ? 'num-neg' : ''}">${pend > 0 ? fmtBRL(r.entrada_pendente) + ' (E/S)' : 'R$ 0,00'}</td>
        <td class="num">${fmtBRL(r.saldo_retido)}</td>
        <td><span class="tab-badge ${badgeCls}">${escapeHtml(r.status)}</span></td>
      </tr>
    `;
  }).join('');
}

function renderCurvaAbcTable(abcData) {
  document.getElementById('abc-total-badge').textContent = 'Total Categoria HD: ' + fmtBRL(abcData.total_categoria_hd);
  const tbody = document.querySelector('#table-curva-abc tbody');
  tbody.innerHTML = (abcData.itens || []).map((item) => {
    const bCls = item.classe_abc === 'A' ? 'badge-teal' : (item.classe_abc === 'B' ? 'badge-amber' : 'badge-slate');
    return `
      <tr style="cursor:pointer;" onclick="filterExtratoByText('${escapeHtml(item.subcategoria.split(',')[0])}')">
        <td><span class="tab-badge ${bCls}">Classe ${item.classe_abc}</span></td>
        <td><strong>${escapeHtml(item.subcategoria)}</strong></td>
        <td class="num">${fmtBRL(item.valor)}</td>
        <td class="num">${fmtPct(item.percentual)}</td>
        <td class="num">${fmtPct(item.percentual_acumulado)}</td>
      </tr>
    `;
  }).join('');
}

function renderPainelSociosTable(sociosList) {
  const tbody = document.querySelector('#table-painel-socios tbody');
  tbody.innerHTML = (sociosList || []).map((s) => `
    <tr>
      <td><strong>${escapeHtml(s.nome)}</strong></td>
      <td><span class="tab-badge badge-slate">${escapeHtml(s.tipo)}</span></td>
      <td class="num">${fmtBRL(s.plantoes_procedimentos)}</td>
      <td class="num">${fmtBRL(s.pro_labore)}</td>
      <td class="num">${fmtBRL(s.responsabilidade_tecnica)}</td>
      <td class="num">${fmtBRL(s.distribuicao_lucros)}</td>
      <td class="num num-pos">${fmtBRL(s.aportes_recebidos)}</td>
      <td class="num">${fmtBRL(s.devolucao_aportes)}</td>
      <td class="num">${fmtBRL(s.reembolsos_icatu_eng)}</td>
      <td class="num ${s.pendente_classificacao > 0 ? 'num-neg' : ''}">${fmtBRL(s.pendente_classificacao)}</td>
      <td class="num"><strong>${fmtBRL(s.total_pago)}</strong></td>
    </tr>
  `).join('');
}

function renderCapexCards(capex) {
  const n21 = capex.nipro_21;
  const n04 = capex.nipro_04;
  const ntot = capex.nipro_consolidado;
  const vw = capex.veiculo_vw;

  const pctNipro = Math.round((n21.parcela_atual / n21.total_parcelas) * 100);
  const pctVw = Math.round((vw.parcela_atual / vw.total_parcelas) * 100);

  document.getElementById('capex-cards-container').innerHTML = `
    <div class="kpi-card border-teal">
      <div class="kpi-label">Capex Nipro — 21 Máquinas HD (NF 18971)</div>
      <div class="kpi-value">${fmtBRL(n21.parcela_mensal)}<span style="font-size:13px; color:var(--slate-500);">/mês</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:${pctNipro}%;"></div></div>
      <div class="kpi-meta">
        <span><strong>Progresso:</strong> Parcela 12/24 (${n21.parcelas_pagas_2026} pagas em 2026 | 12 restantes)</span>
        <span><strong>Pago em 2026:</strong> ${fmtBRL(n21.valor_pago_2026)}</span>
        <span><strong>Saldo Contratual Restante (12x):</strong> ${fmtBRL(n21.saldo_devedor_restante)}</span>
      </div>
    </div>

    <div class="kpi-card border-teal">
      <div class="kpi-label">Capex Nipro — 04 Máquinas HD (NF 158863)</div>
      <div class="kpi-value">${fmtBRL(n04.parcela_mensal)}<span style="font-size:13px; color:var(--slate-500);">/mês</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:${pctNipro}%;"></div></div>
      <div class="kpi-meta">
        <span><strong>Progresso:</strong> Parcela 12/24 (${n04.parcelas_pagas_2026} pagas em 2026 | 12 restantes)</span>
        <span><strong>Pago em 2026:</strong> ${fmtBRL(n04.valor_pago_2026)}</span>
        <span><strong>Saldo Contratual Restante (12x):</strong> ${fmtBRL(n04.saldo_devedor_restante)}</span>
      </div>
    </div>

    <div class="kpi-card border-emerald">
      <div class="kpi-label">Consolidado Capex Nipro (25 Máquinas de HD)</div>
      <div class="kpi-value">${fmtBRL(ntot.parcela_mensal_combinada)}<span style="font-size:13px; color:var(--slate-500);">/mês</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:${pctNipro}%;"></div></div>
      <div class="kpi-meta">
        <span><strong>Total Desembolsado 2026:</strong> ${fmtBRL(ntot.valor_pago_2026)}</span>
        <span><strong>Saldo Restante até 24/24:</strong> ${fmtBRL(ntot.saldo_contratual_restante)}</span>
        <span><strong>Status:</strong> 50% do contrato quitado até Set/2026</span>
      </div>
    </div>

    <div class="kpi-card border-amber">
      <div class="kpi-label">Frota — Financiamento Banco Volkswagen (48x)</div>
      <div class="kpi-value">${fmtBRL(vw.parcela_mensal_base)}<span style="font-size:13px; color:var(--slate-500);">/mês</span></div>
      <div class="progress-track"><div class="progress-fill" style="width:${pctVw}%;"></div></div>
      <div class="kpi-meta">
        <span><strong>Progresso:</strong> Parcela ${vw.parcela_atual}/${vw.total_parcelas} (${vw.parcelas_pagas_2026} pagas em 2026 | ${vw.parcelas_restantes} restantes)</span>
        <span><strong>Pago em 2026:</strong> ${fmtBRL(vw.valor_pago_2026)}</span>
        <span><strong>Saldo Contratual Restante (34x):</strong> ${fmtBRL(vw.saldo_devedor_restante)}</span>
      </div>
    </div>
  `;
}

// ============================================================================
// 5. MÓDULO 2: FILA RÁPIDA DE CONCILIAÇÃO ("TINDER DA CONCILIAÇÃO")
// ============================================================================
function switchFilaSubTab(sub) {
  STATE.filaSubTab = sub;
  ['nc', 'sug', 'forn', 'pend', 'desc'].forEach((k) => {
    document.getElementById(`subtab-btn-${k}`).classList.toggle('active', k === sub);
    document.getElementById(`fila-pane-${k}`).style.display = k === sub ? 'block' : 'none';
  });
}

async function loadFilaConciliacao() {
  const data = await apiGet('/api/conciliacao/fila');
  await LocalDB.saveSnapshot('fila_conciliacao', data);

  // Counts
  const ncList = data.aba_nao_classificados.itens || [];
  const sugList = data.aba_sugeridos.itens || [];
  const fornList = data.aba_higienizacao_fornecedores.itens || [];
  const pendList = data.aba_pendentes_classificados.itens || [];

  document.getElementById('cnt-fila-nc').textContent = ncList.length;
  document.getElementById('btn-cnt-nc').textContent = ncList.length;
  document.getElementById('cnt-fila-sug').textContent = sugList.length;
  document.getElementById('btn-cnt-sug').textContent = sugList.length;
  document.getElementById('cnt-fila-forn').textContent = fornList.length;
  document.getElementById('cnt-fila-pend').textContent = pendList.length;

  // Render Sub-tab 1: 165 Não Classificados
  const tbodyNc = document.querySelector('#table-fila-nc tbody');
  if (ncList.length === 0) {
    tbodyNc.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:24px; color:var(--emerald-600); font-weight:700;"><i data-lucide="check" aria-hidden="true"></i> Parabéns! Todos os movimentos bancários estão 100% classificados!</td></tr>`;
  } else {
    tbodyNc.innerHTML = ncList.map((row) => {
      const m = row.movimento;
      const s = row.sugestao;
      const splitsHtml = s.rateios_sugeridos.map((r) => `
        <div style="margin-bottom:3px;">
          <span class="tab-badge badge-teal">${escapeHtml(r.categoria)}</span>
          &rarr; <strong>${escapeHtml(r.subcategoria)}</strong>
          (${fmtBRL(r.valor)})
        </div>
      `).join('');

      const fornHtml = (!m.fornecedor_favorecido || m.fornecedor_favorecido === '-')
        ? `<span class="tab-badge badge-amber">Vazio &rarr; ${escapeHtml(s.fornecedor_sugerido)}</span>`
        : escapeHtml(m.fornecedor_favorecido);

      return `
        <tr>
          <td><strong>${escapeHtml(m.id_lanc)}</strong></td>
          <td>${fmtDateBR(m.data)}<br/><small style="color:var(--slate-500);">Comp: ${escapeHtml(m.competencia_extraida)}</small></td>
          <td style="max-width:300px;">${escapeHtml(m.historico_banco)}</td>
          <td>${fornHtml}</td>
          <td class="num"><strong>${fmtBRL(row.valor_movimento)}</strong></td>
          <td>
            <div style="font-size:11px; color:var(--slate-500); margin-bottom:3px;">
              ${s.is_split ? '<i data-lucide="zap" aria-hidden="true"></i> <strong>Divisão Automática 1:N</strong> — ' : ''}${escapeHtml(s.regra_aplicada)}
            </div>
            ${splitsHtml}
          </td>
          <td>
            <div style="display:flex; gap:6px;">
              <button class="btn btn-emerald btn-sm" onclick="aplicarSugestaoUnica('${m.id_lanc}')">
                <i data-lucide="check" aria-hidden="true"></i> Aceitar (1 Clique)
              </button>
              <button class="btn btn-outline btn-sm" onclick="openRateioModalById('${m.id_lanc}')">
                Editar 1:N
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  // Render Sub-tab 2: 170 Sugeridos
  const cardsBox = document.getElementById('sugeridos-fornecedor-cards');
  const grupos = data.aba_sugeridos.grupos_por_fornecedor || [];
  cardsBox.innerHTML = grupos.map((g) => `
    <button class="btn btn-outline btn-sm" onclick="aprovarSugeridosPorFornecedor('${escapeHtml(g.fornecedor)}')" title="Aprovar todos deste fornecedor">
      <strong>${escapeHtml(g.fornecedor)}</strong>
      <span class="tab-badge badge-amber">${g.qtd} itens • ${fmtBRL(g.valor_total)}</span>
      <span style="color:var(--emerald-600); font-weight:700;"><i data-lucide="check" aria-hidden="true"></i> Aprovar Lote</span>
    </button>
  `).join('');

  const tbodySug = document.querySelector('#table-fila-sug tbody');
  if (sugList.length === 0) {
    tbodySug.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--emerald-600); font-weight:700;"><i data-lucide="check" aria-hidden="true"></i> Nenhum item pendente na fila de SUGERIDOS!</td></tr>`;
  } else {
    tbodySug.innerHTML = sugList.map((s) => `
      <tr>
        <td><strong>${escapeHtml(s.id_lanc)}</strong></td>
        <td>${fmtDateBR(s.data)}</td>
        <td><strong>${escapeHtml(s.fornecedor_canonico || s.fornecedor)}</strong></td>
        <td>${escapeHtml(s.categoria)}</td>
        <td><strong>${escapeHtml(s.subcategoria)}</strong></td>
        <td class="num">${fmtBRL(s.valor)}</td>
        <td><span class="tab-badge badge-teal">${escapeHtml(s.origem_classificacao)}</span></td>
        <td>
          <button class="btn btn-emerald btn-sm" onclick="aprovarSugeridoUnico(${s.id_rateio})">
            <i data-lucide="check" aria-hidden="true"></i> Confirmar
          </button>
        </td>
      </tr>
    `).join('');
  }

  // Render Sub-tab 3: 35 Sem Fornecedor / Status (BAN-01029 a BAN-01061)
  const tbodyForn = document.querySelector('#table-fila-forn tbody');
  if (fornList.length === 0) {
    tbodyForn.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--emerald-600); font-weight:700;"><i data-lucide="check" aria-hidden="true"></i> Todos os movimentos possuem Fornecedor e Status de Conciliação preenchidos!</td></tr>`;
  } else {
    tbodyForn.innerHTML = fornList.map((f) => `
      <tr>
        <td><strong>${escapeHtml(f.id_lanc)}</strong></td>
        <td>${fmtDateBR(f.data)}</td>
        <td style="max-width:340px;">${escapeHtml(f.historico_banco)}</td>
        <td><span class="tab-badge badge-coral">${escapeHtml(f.fornecedor_atual || '(VAZIO)')}</span></td>
        <td><span class="tab-badge badge-emerald">${escapeHtml(f.fornecedor_sugerido)}</span></td>
        <td>${escapeHtml(f.status_conciliacao_atual || '(VAZIO)')} &rarr; <strong>Conciliado</strong></td>
        <td class="num">${fmtBRL(f.valor)}</td>
        <td>
          <button class="btn btn-teal btn-sm" onclick="autopreencherFornecedorUnico('${f.id_lanc}')">
            <i data-lucide="check" aria-hidden="true"></i> Preencher & Conciliar
          </button>
        </td>
      </tr>
    `).join('');
  }

  // Render Sub-tab 5: Desconsiderados no Rateio
  const descData = data.aba_desconsiderados || { itens: [], valor_total: 0 };
  const descList = descData.itens || [];
  document.getElementById('cnt-fila-desc').textContent = descList.length;
  document.getElementById('desc-total-valor').textContent = fmtBRL(descData.valor_total);
  const tbodyDesc = document.querySelector('#table-fila-desc tbody');
  if (descList.length === 0) {
    tbodyDesc.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:24px; color:var(--slate-500);">Nenhum lançamento desconsiderado no rateio.</td></tr>`;
  } else {
    tbodyDesc.innerHTML = descList.map((d) => {
      const v = fromCents(toCents(d.entrada) + toCents(d.saida) + toCents(d.aplicacao) + toCents(d.resgate));
      return `
        <tr class="row-desconsiderado">
          <td><strong>${escapeHtml(d.id_lanc)}</strong></td>
          <td>${fmtDateBR(d.data)}</td>
          <td style="max-width:340px;">${escapeHtml(d.historico_banco)}</td>
          <td>${escapeHtml(d.fornecedor_canonico || d.fornecedor_favorecido || '-')}</td>
          <td><span class="tab-badge badge-slate">${escapeHtml(d.tipo_movimentacao)}</span></td>
          <td class="num">${fmtBRL(v)}</td>
          <td>
            <button class="btn btn-outline btn-sm" onclick="toggleDesconsiderar('${d.id_lanc}', false)"><i data-lucide="rotate-ccw" aria-hidden="true"></i> Reativar no rateio</button>
          </td>
        </tr>
      `;
    }).join('');
  }

  // Render Sub-tab 4: Pendentes/Revisar Já Classificados
  const tbodyPend = document.querySelector('#table-fila-pend tbody');
  if (pendList.length === 0) {
    tbodyPend.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--emerald-600); font-weight:700;"><i data-lucide="check" aria-hidden="true"></i> Nenhuma linha pendente de revisão!</td></tr>`;
  } else {
    tbodyPend.innerHTML = pendList.map((p) => `
      <tr>
        <td><strong>${escapeHtml(p.id_lanc)}</strong></td>
        <td>${fmtDateBR(p.data)}</td>
        <td>${escapeHtml(p.fornecedor_canonico || p.fornecedor)}</td>
        <td>${escapeHtml(p.categoria)}</td>
        <td><strong>${escapeHtml(p.subcategoria)}</strong></td>
        <td class="num">${fmtBRL(p.valor)}</td>
        <td><span class="tab-badge badge-amber">${escapeHtml(p.origem_classificacao)}</span></td>
        <td>
          <button class="btn btn-emerald btn-sm" onclick="aprovarPendenteClassificadoUnico(${p.id_rateio})">
            <i data-lucide="check" aria-hidden="true"></i> Confirmar
          </button>
        </td>
      </tr>
    `).join('');
  }
}

async function aplicarSugestaoUnica(idLanc) {
  try {
    await apiPost('/api/conciliacao/aplicar-sugestoes', { ids_lanc: [idLanc] });
    showToast(`Lançamento ${idLanc} classificado e conciliado com sucesso!`);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function aplicarTodasSugestoesNaoClassificados() {
  try {
    const res = await apiPost('/api/conciliacao/aplicar-sugestoes', { aplicar_todos: true });
    showToast(`${res.movimentos_classificados} movimentos classificados em ${res.linhas_rateio_geradas} linhas de rateio!`);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function aprovarSugeridoUnico(idRateio) {
  try {
    await apiPost('/api/conciliacao/aprovar-sugeridos', { ids_rateio: [idRateio] });
    showToast('Sugestão confirmada!');
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function aprovarSugeridosPorFornecedor(fornecedor) {
  try {
    const res = await apiPost('/api/conciliacao/aprovar-sugeridos', { fornecedor });
    showToast(`${res.linhas_aprovadas} linhas de ${fornecedor} confirmadas!`);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function aprovarTodosSugeridos() {
  try {
    const res = await apiPost('/api/conciliacao/aprovar-sugeridos', { aprovar_todos: true });
    showToast(`Todas as ${res.linhas_aprovadas} linhas sugeridas foram aprovadas para CONFIRMADO!`);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function autopreencherFornecedorUnico(idLanc) {
  try {
    await apiPost('/api/conciliacao/autopreencher-fornecedores', { ids_lanc: [idLanc] });
    showToast(`Fornecedor e conciliação de ${idLanc} atualizados!`);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function autopreencherTodosFornecedores() {
  try {
    const res = await apiPost('/api/conciliacao/autopreencher-fornecedores', {});
    showToast(`${res.movimentos_atualizados} movimentos autopreenchidos e conciliados!`);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function aprovarPendenteClassificadoUnico(idRateio) {
  try {
    await apiPost('/api/conciliacao/aprovar-pendentes-revisar', { ids_rateio: [idRateio] });
    showToast('Linha confirmada!');
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function aprovarTodosPendentesClassificados() {
  try {
    const res = await apiPost('/api/conciliacao/aprovar-pendentes-revisar', { aprovar_todos: true });
    showToast(`${res.linhas_aprovadas} linhas convertidas para CONFIRMADO!`);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function executarDestravamentoCompletoPassivo() {
  try {
    await apiPost('/api/conciliacao/autopreencher-fornecedores', {});
    await apiPost('/api/conciliacao/aprovar-sugeridos', { aprovar_todos: true });
    await apiPost('/api/conciliacao/aplicar-sugestoes', { aplicar_todos: true });
    await apiPost('/api/conciliacao/aprovar-pendentes-revisar', { aprovar_todos: true });
    showToast('Passivo operacional de Set/Out 100% destravado, classificado e conciliado!');
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// 6. MÓDULO 3: EXTRATO BANCÁRIO E EDITOR DE RATEIO INTELIGENTE (1:N)
// ============================================================================
function filterExtratoByText(text) {
  document.getElementById('ext-search').value = text;
  document.getElementById('ext-status-filter').value = 'ALL';
  switchTab('mod-extrato');
}

function clearExtratoFilters() {
  document.getElementById('ext-search').value = '';
  document.getElementById('ext-status-filter').value = 'ALL';
  document.getElementById('ext-mes-filter').value = 'ALL';
  loadExtratoTable(0).catch((error) => showToast(error.message, true));
}

async function loadExtratoTable(offset = 0) {
  STATE.extratoOffset = offset;
  const mes = document.getElementById('ext-mes-filter').value;
  const st = document.getElementById('ext-status-filter').value;
  const busca = document.getElementById('ext-search').value;

  const qs = new URLSearchParams({
    mes,
    status_rateio: st,
    busca,
    offset: String(offset),
    limit: String(STATE.extratoLimit),
  });
  const data = await apiGet(`/api/extrato?${qs.toString()}`);

  const tbody = document.querySelector('#table-extrato tbody');
  tbody.innerHTML = (data.itens || []).map((e) => {
    const valBanco = fromCents(toCents(e.entrada) + toCents(e.saida) + toCents(e.aplicacao) + toCents(e.resgate));
    const isDiv = e.status_rateio === 'DIVERGÊNCIA';
    const isNc = e.status_rateio === 'NÃO CLASSIFICADO' || e.status_rateio === 'PENDENTE DE RATEIO';
    const isDesc = e.status_rateio === 'DESCONSIDERADO';
    const rowCls = isDesc ? 'row-desconsiderado' : (isDiv ? 'row-divergencia' : (isNc ? 'row-nao-classificado' : ''));
    const badgeCls = isDesc ? 'badge-descons' : (isDiv ? 'badge-coral' : (isNc ? 'badge-amber' : 'badge-emerald'));
    const qtdRat = (e.rateios || []).length;

    return `
      <tr class="${rowCls}">
        <td><strong>${escapeHtml(e.id_lanc)}</strong></td>
        <td>${fmtDateBR(e.data)}</td>
        <td><code>${escapeHtml(e.competencia_extraida)}</code></td>
        <td>
          <span class="tab-badge badge-slate">${escapeHtml(e.tipo_movimentacao)}</span>
          <small style="display:block; color:var(--slate-500);">${escapeHtml(e.tipo_pagamento)}</small>
        </td>
        <td style="max-width:290px;">${escapeHtml(e.historico_banco)}</td>
        <td>
          <strong>${escapeHtml(e.fornecedor_canonico || '-')}</strong>
          ${e.fornecedor_favorecido && e.fornecedor_favorecido !== e.fornecedor_canonico ? `<small style="display:block; color:var(--slate-500);">Orig: ${escapeHtml(e.fornecedor_favorecido)}</small>` : ''}
        </td>
        <td>${escapeHtml(e.documento || '-')}</td>
        <td class="num ${e.tipo_movimentacao === 'ENTRADA' || e.tipo_movimentacao === 'RESGATE' ? 'num-pos' : ''}">
          <strong>${fmtBRL(valBanco)}</strong>
        </td>
        <td class="num">${fmtBRL(e.total_rateado)} <small style="color:var(--slate-500);">(${qtdRat}x)</small></td>
        <td class="num ${Math.abs(e.diferenca) > 0.005 ? 'num-neg' : ''}">${fmtBRL(e.diferenca)}</td>
        <td class="num">${fmtBRL(e.saldo_acumulado)}</td>
        <td><span class="tab-badge ${badgeCls}">${escapeHtml(e.status_rateio)}</span></td>
        <td>
          <div style="display:flex; gap:4px; flex-wrap:wrap;">
            <button class="btn btn-outline btn-sm" title="Editar dados do lançamento" onclick="openEditarLancamentoModal('${e.id_lanc}')"><i data-lucide="pencil" aria-hidden="true"></i> Editar</button>
            ${isDesc
              ? `<button class="btn btn-outline btn-sm" title="Voltar a considerar no rateio" onclick="toggleDesconsiderar('${e.id_lanc}', false)"><i data-lucide="rotate-ccw" aria-hidden="true"></i> Reativar</button>`
              : `<button class="btn ${isDiv ? 'btn-coral' : (isNc ? 'btn-amber' : 'btn-outline')} btn-sm" onclick="openRateioModalById('${e.id_lanc}')">Ratear (${qtdRat})</button>
                 <button class="btn btn-outline btn-sm" title="Desconsiderar no rateio" onclick="toggleDesconsiderar('${e.id_lanc}', true)"><i data-lucide="circle-slash" aria-hidden="true"></i> Desconsiderar</button>`}
          </div>
        </td>
      </tr>
    `;
  }).join('');
  if (!data.itens.length) {
    tbody.innerHTML = `<tr><td colspan="13" class="empty-table-cell">Nenhum lançamento corresponde aos filtros. <button type="button" class="btn btn-outline btn-sm" onclick="clearExtratoFilters()">Limpar filtros e mostrar o extrato</button></td></tr>`;
  }

  const activeFilters = [busca && `Busca: ${busca}`, st !== 'ALL' && `Status: ${document.getElementById('ext-status-filter').selectedOptions[0].textContent.trim()}`, mes !== 'ALL' && `Mês: ${document.getElementById('ext-mes-filter').selectedOptions[0].textContent.trim()}`].filter(Boolean);
  document.getElementById('extrato-filter-summary').textContent = activeFilters.length
    ? `Filtros ativos — ${activeFilters.join(' · ')}. Busca inclui as categorias e subcategorias dos rateios.`
    : 'Exibindo todos os lançamentos do extrato.';

  // Pagination controls
  const info = document.getElementById('extrato-pagination-info');
  const start = data.total === 0 ? 0 : offset + 1;
  const end = Math.min(data.total, offset + STATE.extratoLimit);
  info.textContent = `Exibindo ${start} a ${end} de ${data.total} movimentos`;

  const btns = document.getElementById('extrato-pagination-btns');
  btns.innerHTML = '';
  if (offset > 0) {
    const prev = document.createElement('button');
    prev.className = 'btn btn-outline btn-sm';
    prev.textContent = '← Anterior';
    prev.onclick = () => loadExtratoTable(Math.max(0, offset - STATE.extratoLimit));
    btns.appendChild(prev);
  }
  if (offset + STATE.extratoLimit < data.total) {
    const next = document.createElement('button');
    next.className = 'btn btn-outline btn-sm';
    next.textContent = 'Próxima →';
    next.onclick = () => loadExtratoTable(offset + STATE.extratoLimit);
    btns.appendChild(next);
  }
}

async function corrigirBan00697Direto() {
  try {
    const res = await apiPost('/api/extrato/corrigir-ban00697', {});
    showToast(res.mensagem);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// 7. MODAL DO EDITOR DE RATEIO INTELIGENTE (1:N) COM TEMPLATES
// ============================================================================
async function openRateioModalById(idLanc) {
  try {
    const data = await apiGet(`/api/extrato?id_lanc=${encodeURIComponent(idLanc)}`);
    if (!data.itens || data.itens.length === 0) {
      throw new Error(`Lançamento ${idLanc} não encontrado.`);
    }
    const mov = data.itens[0];
    STATE.currentEditLanc = mov;

    const valBanco = fromCents(toCents(mov.entrada) + toCents(mov.saida) + toCents(mov.aplicacao) + toCents(mov.resgate));
    mov._valorBanco = valBanco;

    document.getElementById('modal-rat-title').textContent = `Editor de Rateio Inteligente (1:N) — ${mov.id_lanc}`;
    document.getElementById('modal-rat-subtitle').textContent = `Data: ${fmtDateBR(mov.data)} • Competência Extraída: ${mov.competencia_extraida} • Natureza: ${mov.tipo_movimentacao}`;
    document.getElementById('mrat-historico').value = mov.historico_banco || '';
    document.getElementById('mrat-fornecedor').value = mov.fornecedor_favorecido || mov.fornecedor_canonico || '';
    document.getElementById('mrat-documento').value = mov.documento || '';
    document.getElementById('mrat-status-conc').value = mov.status_conciliacao || 'Conciliado';

    const tbody = document.getElementById('mrat-lines-tbody');
    tbody.innerHTML = '';

    const isDesc = mov.status_rateio === 'DESCONSIDERADO' || Number(mov.desconsiderar_rateio) === 1;
    document.getElementById('mrat-desconsiderar').checked = isDesc;

    const rateiosValidos = (mov.rateios || []).filter((r) => r.categoria !== 'DESCONSIDERADO NO RATEIO');
    const rateios = rateiosValidos.length > 0 ? rateiosValidos : [{
      categoria: '',
      subcategoria: '',
      valor: valBanco,
      detalhe_componente: mov.historico_banco || '',
    }];

    rateios.forEach((r) => addRateioModalLine(r));
    onToggleDesconsiderarModal();
    document.getElementById('modal-rateio').classList.add('open');
  } catch (err) {
    showToast(err.message, true);
  }
}

function closeRateioModal() {
  document.getElementById('modal-rateio').classList.remove('open');
  STATE.currentEditLanc = null;
}

function addRateioModalLine(item = {}) {
  const tbody = document.getElementById('mrat-lines-tbody');
  const tr = document.createElement('tr');
  const plano = STATE.bootstrap ? STATE.bootstrap.plano_de_contas : {};
  const cats = Object.keys(plano);
  const selectedCat = item.categoria || cats[0] || '';
  const subs = plano[selectedCat] || [];
  const selectedSub = item.subcategoria || subs[0] || '';

  const catOptions = cats.map((c) => `<option value="${escapeHtml(c)}" ${c === selectedCat ? 'selected' : ''}>${escapeHtml(c)}</option>`).join('');
  const subOptions = subs.map((s) => `<option value="${escapeHtml(s)}" ${s === selectedSub ? 'selected' : ''}>${escapeHtml(s)}</option>`).join('');

  tr.innerHTML = `
    <td>
      <select class="mrat-cat" style="width:100%;" onchange="onModalCatChange(this)">
        ${catOptions}
      </select>
    </td>
    <td>
      <select class="mrat-sub" style="width:100%;">
        ${subOptions}
      </select>
    </td>
    <td>
      <input type="number" step="0.01" class="mrat-val num" style="width:100%;" value="${Number(item.valor || 0).toFixed(2)}" oninput="updateRateioModalCalculator()" />
    </td>
    <td>
      <input type="text" class="mrat-det" style="width:100%;" value="${escapeHtml(item.detalhe_componente || '')}" />
    </td>
    <td style="text-align:center;">
      <button type="button" class="btn btn-coral btn-sm" onclick="removeRateioModalLine(this)">&times;</button>
    </td>
  `;
  tbody.appendChild(tr);
  updateRateioModalCalculator();
}

function onModalCatChange(selCatEl) {
  const tr = selCatEl.closest('tr');
  const selSubEl = tr.querySelector('.mrat-sub');
  const cat = selCatEl.value;
  const subs = (STATE.bootstrap && STATE.bootstrap.plano_de_contas[cat]) || [];
  selSubEl.innerHTML = subs.map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
}

function removeRateioModalLine(btnEl) {
  const tbody = document.getElementById('mrat-lines-tbody');
  if (tbody.querySelectorAll('tr').length <= 1) {
    showToast('O lançamento precisa ter pelo menos 1 linha de rateio.', true);
    return;
  }
  btnEl.closest('tr').remove();
  updateRateioModalCalculator();
}

function updateRateioModalCalculator() {
  if (!STATE.currentEditLanc) return;
  const descChk = document.getElementById('mrat-desconsiderar');
  if (descChk && descChk.checked) {
    document.getElementById('mrat-validation-msg').innerHTML =
      `<span style="color:var(--slate-600);"><i data-lucide="circle-slash" aria-hidden="true"></i> Este lançamento será <strong>desconsiderado no rateio</strong> (fica fora da Prestação de Contas).</span>`;
    document.getElementById('btn-mrat-save').disabled = false;
    return;
  }
  const bancoCents = toCents(STATE.currentEditLanc._valorBanco);
  let rateadoCents = 0;
  document.querySelectorAll('#mrat-lines-tbody .mrat-val').forEach((inp) => {
    rateadoCents += toCents(inp.value);
  });

  const difCents = bancoCents - rateadoCents;
  const bancoVal = fromCents(bancoCents);
  const rateadoVal = fromCents(rateadoCents);
  const difVal = fromCents(difCents);

  document.getElementById('mrat-calc-banco').textContent = fmtBRL(bancoVal);
  document.getElementById('mrat-calc-rateado').textContent = fmtBRL(rateadoVal);

  const difEl = document.getElementById('mrat-calc-dif');
  difEl.textContent = fmtBRL(difVal);
  difEl.className = Math.abs(difCents) === 0 ? 'num-pos' : 'num-neg';

  const msgEl = document.getElementById('mrat-validation-msg');
  const saveBtn = document.getElementById('btn-mrat-save');
  if (Math.abs(difCents) === 0) {
    msgEl.innerHTML = `<span style="color:var(--emerald-600);"><i data-lucide="check" aria-hidden="true"></i> Fechamento Contábil Exato (Diferença = R$ 0,00). Pronto para salvar!</span>`;
    saveBtn.disabled = false;
  } else {
    msgEl.innerHTML = `<span style="color:var(--coral-600);"><i data-lucide="triangle-alert" aria-hidden="true"></i> Bloqueio de Fidelidade Contábil: Diferença de ${fmtBRL(difVal)}. Ajuste as parcelas para R$ 0,00!</span>`;
    saveBtn.disabled = true;
  }
}

function ajustarDiferencaUltimaLinha() {
  if (!STATE.currentEditLanc) return;
  const inputs = Array.from(document.querySelectorAll('#mrat-lines-tbody .mrat-val'));
  if (inputs.length === 0) return;

  const bancoCents = toCents(STATE.currentEditLanc._valorBanco);
  let somaAnteriores = 0;
  for (let i = 0; i < inputs.length - 1; i++) {
    somaAnteriores += toCents(inputs[i].value);
  }
  const ultimoCents = bancoCents - somaAnteriores;
  if (ultimoCents <= 0) {
    showToast('A soma das linhas anteriores já ultrapassa o valor do banco!', true);
    return;
  }
  inputs[inputs.length - 1].value = fromCents(ultimoCents).toFixed(2);
  updateRateioModalCalculator();
}

async function aplicarTemplateNoModal(templateName) {
  if (!STATE.currentEditLanc) return;
  try {
    const res = await apiPost('/api/templates/gerar', {
      template: templateName,
      valor: STATE.currentEditLanc._valorBanco,
      fornecedor: document.getElementById('mrat-fornecedor').value,
      historico: document.getElementById('mrat-historico').value,
    });
    const tbody = document.getElementById('mrat-lines-tbody');
    tbody.innerHTML = '';
    (res.itens || []).forEach((it) => addRateioModalLine(it));
    updateRateioModalCalculator();
    showToast(`Template ${templateName} aplicado com fechamento exato!`);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function saveRateioModal() {
  if (!STATE.currentEditLanc) return;
  const rows = Array.from(document.querySelectorAll('#mrat-lines-tbody tr'));
  const rateios = rows.map((tr) => ({
    categoria: tr.querySelector('.mrat-cat').value,
    subcategoria: tr.querySelector('.mrat-sub').value,
    valor: parseFloat(tr.querySelector('.mrat-val').value || '0'),
    detalhe_componente: tr.querySelector('.mrat-det').value,
    origem_classificacao: 'CONFIRMADO',
  }));

  try {
    await apiPost('/api/extrato/salvar-rateio', {
      id_lanc: STATE.currentEditLanc.id_lanc,
      historico_banco: document.getElementById('mrat-historico').value,
      fornecedor_favorecido: document.getElementById('mrat-fornecedor').value,
      documento: document.getElementById('mrat-documento').value,
      status_conciliacao: document.getElementById('mrat-status-conc').value,
      desconsiderar_rateio: document.getElementById('mrat-desconsiderar').checked,
      rateios,
    });
    showToast(`Rateio de ${STATE.currentEditLanc.id_lanc} salvo e conciliado com sucesso!`);
    closeRateioModal();
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// 8. MODAL DE NOVO MOVIMENTO BANCÁRIO (BAN-01062+)
// ============================================================================
function openNovoMovimentoModal() {
  document.getElementById('nmov-historico').value = '';
  document.getElementById('nmov-valor').value = '';
  document.getElementById('nmov-fornecedor').value = '';
  document.getElementById('nmov-doc').value = '';
  document.getElementById('modal-novo-mov').classList.add('open');
}

function closeNovoMovimentoModal() {
  document.getElementById('modal-novo-mov').classList.remove('open');
}

async function salvarNovoMovimento() {
  try {
    const payload = {
      data: document.getElementById('nmov-data').value,
      tipo_movimentacao: document.getElementById('nmov-tipo-mov').value,
      tipo_pagamento: document.getElementById('nmov-tipo-pag').value,
      historico_banco: document.getElementById('nmov-historico').value,
      valor: parseFloat(document.getElementById('nmov-valor').value || '0'),
      fornecedor_favorecido: document.getElementById('nmov-fornecedor').value,
      documento: document.getElementById('nmov-doc').value,
    };
    const res = await apiPost('/api/extrato/novo', payload);
    showToast(`Novo movimento ${res.id_lanc} cadastrado e classificado com sucesso!`);
    closeNovoMovimentoModal();
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// 9. MÓDULO 4: RELATÓRIO DE PRESTAÇÃO DE CONTAS (DRE GERENCIAL)
// ============================================================================
async function loadDreReport() {
  if (dreView === 'oficial') return loadOfficialPreview();
  const request = ++dreRequest;
  const periodo = STATE.periodo, regime = STATE.regime;
  const qs = new URLSearchParams({ periodo, regime });
  const data = await apiGet(`/api/prestacao-contas?${qs.toString()}`);
  if (request !== dreRequest) return;
  await LocalDB.saveSnapshot('dre_prestacao', data);
  document.getElementById('dre-status').textContent = '';

  const container = document.getElementById('dre-report-container');

  const entRowsHtml = (data.entradas.itens || []).map((it) => `
    <tr>
      <td style="padding-left:24px;">${escapeHtml(it.descricao)} <em>${escapeHtml(it.observacao_resumo)}</em></td>
      <td class="num ${it.sinal === '-' ? 'num-neg' : 'num-pos'}">${fmtBRL(it.valor)}</td>
      <td class="num">-</td>
    </tr>
  `).join('');

  const despGroupsHtml = (data.despesas.grupos || []).map((g, idx) => {
    const pctTotal = data.despesas.total > 0 ? (g.total / data.despesas.total) * 100 : 0;
    const subRows = (g.subcategorias || []).map((s) => `
      <tr class="dre-sub-row dre-grp-${idx}">
        <td style="padding-left:32px; color:var(--slate-600);">${escapeHtml(s.subcategoria)} <em>${escapeHtml(s.observacao_resumo)}</em></td>
        <td class="num">${fmtBRL(s.valor)}</td>
        <td class="num">${fmtPct(s.percentual_grupo)}</td>
      </tr>
    `).join('');

    return `
      <tr style="background:var(--slate-100); cursor:pointer; font-weight:700;" >
        <td><button class="dre-group-toggle" onclick="toggleDreGroup(${idx})" aria-expanded="true" data-dre-group="${idx}"><i data-lucide="chevron-down"></i> ${escapeHtml(g.categoria)}</button></td>
        <td class="num">${fmtBRL(g.total)}</td>
        <td class="num">${fmtPct(pctTotal)}</td>
      </tr>
      ${subRows}
    `;
  }).join('');

  container.innerHTML = `
    <div class="dre-summary">
      <div>
        <strong>PRESTAÇÃO DE CONTAS — BIORENAL 2026</strong>
        <span style="margin-left:12px; font-size:12px; color:var(--text-secondary);">Período: ${escapeHtml(periodo)} | Regime: ${escapeHtml(regime)}</span>
      </div>
      <div>
        <span class="tab-badge badge-emerald">Saldo do Período: ${fmtBRL(data.saldo_periodo)}</span>
      </div>
    </div>

    ${(data.avisos || []).map((message) => `<p class="dre-warning">${escapeHtml(message)}</p>`).join('')}
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Descrição (Estrutura Oficial Aba PRESTAÇÃO DE CONTAS)</th>
            <th class="num">Valor (R$)</th>
            <th class="num">% Grupo / Total</th>
          </tr>
        </thead>
        <tbody>
          <tr style="background:var(--emerald-50); font-weight:800; font-size:13.5px;">
            <td>1. ENTRADAS (LÍQUIDO DE APLICAÇÕES)</td>
            <td class="num num-pos">${fmtBRL(data.entradas.total_liquido_prestacao)}</td>
            <td class="num">100,00%</td>
          </tr>
          ${entRowsHtml}

          <tr style="background:var(--coral-50); font-weight:800; font-size:13.5px;">
            <td>2. DESPESAS CLASSIFICADAS (11 GRUPOS DO PLANO DE CONTAS)</td>
            <td class="num num-neg">${fmtBRL(data.despesas.total)}</td>
            <td class="num">100,00%</td>
          </tr>
          ${despGroupsHtml}

          <tr style="background:var(--amber-50); font-weight:800;">
            <td>3. LANÇAMENTOS AINDA NÃO CLASSIFICADOS (${data.nao_classificados.quantidade} itens)</td>
            <td class="num num-neg">${fmtBRL(data.nao_classificados.total)}</td>
            <td class="num">-</td>
          </tr>

          <tr style="background:var(--teal-50); font-weight:800; font-size:14px;">
            <td>4. SALDO DO PERÍODO (ENTRADAS - DESPESAS CLASSIFICADAS)</td>
            <td class="num ${data.saldo_periodo >= 0 ? 'num-pos' : 'num-neg'}">${fmtBRL(data.saldo_periodo)}</td>
            <td class="num">-</td>
          </tr>

          <tr>
            <td style="color:var(--slate-600);"><em>Memória: Repasse do Piso da Enfermagem (Entrada Classificada no Período)</em></td>
            <td class="num">${fmtBRL(data.memoria_piso_enfermagem.entrada_repasse_piso)}</td>
            <td class="num">Pass-Through</td>
          </tr>
          <tr>
            <td style="color:var(--slate-600);"><em>Memória: Folha do Repasse do Piso (Despesa Classificada no Período)</em></td>
            <td class="num">${fmtBRL(data.memoria_piso_enfermagem.saida_folha_piso)}</td>
            <td class="num">Pass-Through</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="dre-note">${escapeHtml(data.nota_rodape)}</p>
  `;
}

function toggleDreGroup(idx) {
  const button = document.querySelector(`[data-dre-group="${idx}"]`);
  button.setAttribute('aria-expanded', String(button.getAttribute('aria-expanded') !== 'true'));
  document.querySelectorAll(`.dre-grp-${idx}`).forEach((el) => {
    el.style.display = el.style.display === 'none' ? 'table-row' : 'none';
  });
}

function toggleAllDreGroups(expand) {
  document.querySelectorAll('[data-dre-group]').forEach((button) => button.setAttribute('aria-expanded', String(expand)));
  document.querySelectorAll('.dre-sub-row').forEach((el) => {
    el.style.display = expand ? 'table-row' : 'none';
  });
}

// ============================================================================
// 10. MÓDULO 5: CENTRAL DE INTEGRIDADE E UNIFICADOR DE FORNECEDORES
// ============================================================================
async function loadIntegridadeModule() {
  const data = await apiGet('/api/integridade');
  await LocalDB.saveSnapshot('integridade', data);

  const okCount = data.testes_integridade.filter((t) => t.situacao === 'OK').length;
  const verCount = data.testes_integridade.filter((t) => t.situacao === 'VERIFICAR').length;
  const fechOk = data.testes_fechamento.filter((f) => f.ok).length;

  document.getElementById('integridade-summary-cards').innerHTML = `
    <div class="kpi-card ${verCount === 0 ? 'border-emerald' : 'border-amber'}">
      <div class="kpi-label">14 Verificações de Integridade</div>
      <div class="kpi-value">${okCount}/14 OK <span style="font-size:13px; color:var(--slate-500);">(${verCount} a verificar)</span></div>
      <div class="kpi-meta"><span>Clique em qualquer alerta na tabela abaixo para corrigir imediatamente</span></div>
    </div>
    <div class="kpi-card ${fechOk === 4 ? 'border-emerald' : 'border-coral'}">
      <div class="kpi-label">4 Testes de Fechamento Contábil</div>
      <div class="kpi-value">${fechOk}/4 Fechados</div>
      <div class="kpi-meta"><span>Tolerância máxima de ponto flutuante: &le; 0,005</span></div>
    </div>
    <div class="kpi-card border-teal">
      <div class="kpi-label">Higienização de Linhas Órfãs / Pré-Alocadas</div>
      <div class="kpi-value">100% Saneado</div>
      <div class="kpi-meta">
        <span><strong>Linhas Órfãs RATEIOS removidas:</strong> Linhas ${escapeHtml(data.higienizacao_planilha.linhas_orfas_rateio_removidas)}</span>
        <span><strong>Pré-alocadas vazias limpas:</strong> ${data.higienizacao_planilha.linhas_prealocadas_rateio_removidas} em RATEIOS</span>
      </div>
    </div>
  `;

  // 14 Tests Table
  const tbody14 = document.querySelector('#table-integridade-14 tbody');
  tbody14.innerHTML = (data.testes_integridade || []).map((t) => {
    const bCls = t.situacao === 'OK' ? 'badge-emerald' : (t.situacao === 'VERIFICAR' ? 'badge-coral' : 'badge-slate');
    let btnHtml = '-';
    if (t.situacao === 'VERIFICAR') {
      btnHtml = `<button class="btn btn-coral btn-sm" onclick="handleIntegridadeAction('${t.acao_filtro}')">Resolver Agora &rarr;</button>`;
    }
    return `
      <tr>
        <td><strong>#${t.id}</strong></td>
        <td>
          <strong>${escapeHtml(t.verificacao)}</strong>
          <small style="display:block; color:var(--slate-500);">${escapeHtml(t.o_que_fazer)}</small>
        </td>
        <td class="num"><strong>${t.resultado}</strong></td>
        <td><span class="tab-badge ${bCls}">${escapeHtml(t.situacao)}</span></td>
        <td>${btnHtml}</td>
      </tr>
    `;
  }).join('');

  // 4 Closing Tests Table
  const tbody4 = document.querySelector('#table-fechamento-4 tbody');
  tbody4.innerHTML = (data.testes_fechamento || []).map((f) => `
    <tr>
      <td><strong>${escapeHtml(f.teste)}</strong></td>
      <td class="num">${fmtBRL(f.valor_a)}</td>
      <td class="num">${fmtBRL(f.valor_b)}</td>
      <td class="num ${f.ok ? 'num-pos' : 'num-neg'}"><strong>${fmtBRL(f.diferenca)}</strong></td>
      <td><span class="tab-badge ${f.ok ? 'badge-emerald' : 'badge-coral'}">${f.ok ? 'FECHADO (OK)' : 'DIVERGÊNCIA'}</span></td>
    </tr>
  `).join('');

  // Structural Sanitization Info
  document.getElementById('higienizacao-estrutural-box').innerHTML = `
    <ul style="list-style:none; display:flex; flex-direction:column; gap:8px; font-size:12.5px;">
      <li><i data-lucide="check" aria-hidden="true"></i> <strong>Fórmula de Saldo da Aplicação (<code>PAINEL!A8</code>):</strong> Corrigida de <code>=SUM(EXTRATO!L2:L3000)-SUM(EXTRATO!M850:M3000)</code> para <code>=CADASTROS!B5+SUM(EXTRATO!L2:L3000)-SUM(EXTRATO!M2:M3000)</code>.</li>
      <li><i data-lucide="check" aria-hidden="true"></i> <strong>Linhas em Branco Órfãs em <code>RATEIOS</code>:</strong> Removidas as linhas vazias <strong>799</strong> (antes de <code>BAN-00697</code>) e <strong>980</strong> (antes de <code>BAN-00843</code>).</li>
      <li><i data-lucide="check" aria-hidden="true"></i> <strong>Linhas Pré-Alocadas Vazias:</strong> Ignoradas as 39 linhas pré-alocadas vazias (<code>BAN-01062</code> a <code>BAN-01100</code>) que inflavam o contador de PENDENTES de 264 para 303.</li>
    </ul>
  `;

  // 13 Canonical Supplier Groups
  document.getElementById('canonical-groups-pills').innerHTML = (data.grupos_canonicos_oficiais || []).map((g) => `
    <div style="padding:10px 12px; background:var(--slate-100); border:1px solid var(--slate-200); border-radius:var(--radius-sm);">
      <div style="font-weight:700; color:var(--teal-primary); font-size:12.5px; margin-bottom:4px;">
        <i data-lucide="link" aria-hidden="true"></i> ${escapeHtml(g.canonico)}
      </div>
      <div style="font-size:11.5px; color:var(--slate-600);">
        Agrupa: ${g.variantes.map((v) => `<code>${escapeHtml(v)}</code>`).join(' + ')}
      </div>
    </div>
  `).join('');

  // Supplier Ranking Table
  const tbodyRank = document.querySelector('#table-ranking-fornecedores tbody');
  tbodyRank.innerHTML = (data.ranking_fornecedores || []).map((r, i) => `
    <tr class="supplier-row" data-fornecedor="${encodeURIComponent(r.fornecedor_canonico)}" tabindex="0" title="Ver lançamentos de ${escapeHtml(r.fornecedor_canonico)}">
      <td>${i + 1}</td>
      <td>
        <strong>${escapeHtml(r.fornecedor_canonico)}</strong>
        ${r.unificado ? '<span class="tab-badge badge-teal" style="margin-left:6px;">Unificado De-Para</span>' : ''}
      </td>
      <td>${r.grafias_originais.map((g) => `<code>${escapeHtml(g)}</code>`).join(', ')}</td>
      <td class="num">${r.qtd_movimentos}</td>
      <td class="num">${fmtBRL(r.total_saidas)}</td>
      <td class="num num-pos">${fmtBRL(r.total_entradas)}</td>
    </tr>
  `).join('');
  tbodyRank.onclick = (event) => {
    const row = event.target.closest('tr[data-fornecedor]');
    if (row) openFornecedorDetalhe(decodeURIComponent(row.dataset.fornecedor));
  };
  tbodyRank.onkeydown = (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const row = event.target.closest('tr[data-fornecedor]');
    if (row) { event.preventDefault(); openFornecedorDetalhe(decodeURIComponent(row.dataset.fornecedor)); }
  };
  if (STATE.activeTab === 'mod-fornecedores' && STATE.supplierName) await loadFornecedorMovimentos(STATE.supplierOffset);
}

function openFornecedorDetalhe(name) {
  STATE.supplierName = name;
  STATE.supplierOffset = 0;
  document.getElementById('fornecedor-detalhe-card').hidden = false;
  document.getElementById('fornecedor-detalhe-titulo').textContent = `Lançamentos de ${name}`;
  loadFornecedorMovimentos(0).then(() => document.getElementById('fornecedor-detalhe-card').scrollIntoView({ behavior: 'smooth', block: 'start' }))
    .catch((error) => showToast(error.message, true));
}

function closeFornecedorDetalhe() {
  STATE.supplierName = '';
  STATE.supplierOffset = 0;
  document.getElementById('fornecedor-detalhe-card').hidden = true;
}

async function loadFornecedorMovimentos(offset = 0) {
  if (!STATE.supplierName) return;
  STATE.supplierOffset = offset;
  const params = new URLSearchParams({ fornecedor: STATE.supplierName, offset: String(offset), limit: '50' });
  const data = await apiGet(`/api/extrato?${params.toString()}`);
  document.getElementById('fornecedor-detalhe-subtitulo').textContent = `${data.total} lançamento(s) vinculados ao nome canônico. O nome original do extrato é preservado.`;
  const tbody = document.querySelector('#table-fornecedor-movimentos tbody');
  tbody.innerHTML = data.itens.map((e) => {
    const amount = fromCents(toCents(e.entrada) + toCents(e.resgate) - toCents(e.saida) - toCents(e.aplicacao));
    const categories = (e.rateios || []).map((r) => `${escapeHtml(r.categoria || 'Sem categoria')} / ${escapeHtml(r.subcategoria || 'Sem subcategoria')}`).join('<br>') || 'Sem rateio';
    return `<tr><td><strong>${escapeHtml(e.id_lanc)}</strong></td><td>${fmtDateBR(e.data)}</td><td>${escapeHtml(e.historico_banco || '')}<br><small>${escapeHtml(e.documento || '')}</small></td><td>${escapeHtml(e.fornecedor_favorecido || '-')}</td><td>${categories}</td><td class="num ${amount < 0 ? 'num-neg' : 'num-pos'}">${fmtBRL(amount)}</td><td>${escapeHtml(e.status_rateio)}</td><td><button class="btn btn-outline btn-sm" type="button" data-id="${escapeHtml(e.id_lanc)}">Ver rateio</button></td></tr>`;
  }).join('') || '<tr><td colspan="8" class="empty-table-cell">Nenhum lançamento encontrado.</td></tr>';
  tbody.onclick = (event) => {
    const button = event.target.closest('button[data-id]');
    if (button) openRateioModalById(button.dataset.id);
  };
  const first = data.total ? offset + 1 : 0;
  document.getElementById('fornecedor-detalhe-paginacao').textContent = `${first}–${Math.min(offset + 50, data.total)} de ${data.total}`;
  const buttons = document.getElementById('fornecedor-detalhe-botoes');
  buttons.replaceChildren();
  if (offset > 0) {
    const previous = document.createElement('button'); previous.className = 'btn btn-outline btn-sm'; previous.textContent = 'Anterior';
    previous.onclick = () => loadFornecedorMovimentos(Math.max(0, offset - 50)); buttons.appendChild(previous);
  }
  if (offset + 50 < data.total) {
    const next = document.createElement('button'); next.className = 'btn btn-outline btn-sm'; next.textContent = 'Próxima';
    next.onclick = () => loadFornecedorMovimentos(offset + 50); buttons.appendChild(next);
  }
}

function resetCadastroPreview() {
  STATE.cadastroPreview = null;
  document.getElementById('cadastro-salvar').disabled = true;
  document.getElementById('cadastro-preview').textContent = 'Confira o impacto novamente antes de salvar.';
}

async function loadCadastrosModule() {
  const data = await apiGet('/api/cadastros/fornecedores');
  document.getElementById('cadastro-origem-list').innerHTML = [...new Set([...data.nomes_origem, ...data.fornecedores])]
    .map((name) => `<option value="${escapeHtml(name)}"></option>`).join('');
  document.getElementById('cadastro-canon-list').innerHTML = data.fornecedores
    .map((name) => `<option value="${escapeHtml(name)}"></option>`).join('');
  const aliases = document.querySelector('#table-cadastro-aliases tbody');
  aliases.innerHTML = data.aliases.map((row) => `<tr><td>${escapeHtml(row.alias)}</td><td>${escapeHtml(row.canonico)}</td><td>${escapeHtml(row.atualizado_em)}</td><td><button type="button" class="btn btn-outline btn-sm" data-alias="${encodeURIComponent(row.alias)}">Remover vínculo</button></td></tr>`).join('')
    || '<tr><td colspan="4" class="empty-table-cell">Ainda não há vínculos manuais.</td></tr>';
  aliases.onclick = (event) => {
    const button = event.target.closest('button[data-alias]');
    if (button) removerCadastroFornecedor(decodeURIComponent(button.dataset.alias));
  };
  document.querySelector('#table-cadastro-auditoria tbody').innerHTML = data.auditoria.map((row) => `<tr><td>${escapeHtml(row.criado_em)}</td><td>${escapeHtml(row.acao)}</td><td>${escapeHtml(row.alias)}</td><td>${escapeHtml(row.canonico_anterior || '—')}</td><td>${escapeHtml(row.canonico_novo || '—')}</td></tr>`).join('')
    || '<tr><td colspan="5" class="empty-table-cell">Nenhuma alteração registrada.</td></tr>';
}

async function previewCadastroFornecedor() {
  const alias = document.getElementById('cadastro-alias').value.trim();
  const canonico = document.getElementById('cadastro-canonico').value.trim();
  try {
    const data = await apiGet(`/api/cadastros/fornecedores/preview?${new URLSearchParams({ alias, canonico })}`);
    STATE.cadastroPreview = data;
    document.getElementById('cadastro-preview').innerHTML = `<strong>${data.qtd_afetada} lançamento(s)</strong> seriam agrupados em <strong>${escapeHtml(data.canonico)}</strong>. Pagamentos: ${fmtBRL(data.total_saidas)}; recebimentos: ${fmtBRL(data.total_entradas)}. IDs de amostra: ${escapeHtml(data.ids_amostra.join(', ') || 'nenhum')}. Confira esses lançamentos antes de salvar; homônimos podem ser pessoas diferentes.`;
    document.getElementById('cadastro-salvar').disabled = data.qtd_afetada === 0;
  } catch (error) {
    resetCadastroPreview();
    showToast(error.message, true);
  }
}

async function salvarCadastroFornecedor() {
  const preview = STATE.cadastroPreview;
  if (!preview) return;
  if (document.getElementById('cadastro-alias').value.trim() !== preview.alias || document.getElementById('cadastro-canonico').value.trim() !== preview.canonico) {
    resetCadastroPreview();
    return showToast('Os nomes mudaram. Confira o impacto novamente.', true);
  }
  if (!window.confirm(`Confirma unir ${preview.qtd_afetada} lançamento(s) de "${preview.alias}" sob "${preview.canonico}"?`)) return;
  try {
    await apiPost('/api/cadastros/fornecedores/salvar', preview);
    resetCadastroPreview();
    showToast('Vínculo salvo. O extrato original foi preservado.');
    await initBootstrap();
    await loadCadastrosModule();
  } catch (error) { showToast(error.message, true); }
}

async function removerCadastroFornecedor(alias) {
  if (!window.confirm(`Remover o vínculo de "${alias}" e recalcular os nomes canônicos?`)) return;
  try {
    await apiPost('/api/cadastros/fornecedores/remover', { alias });
    showToast('Vínculo removido.');
    await initBootstrap();
    await loadCadastrosModule();
  } catch (error) { showToast(error.message, true); }
}

function handleIntegridadeAction(acao) {
  if (acao === 'DIVERGENCIA') {
    jumpToDivergencia();
  } else if (acao === 'NAO_CLASSIFICADO' || acao === 'FILA_PENDENTES') {
    switchTab('mod-fila');
    switchFilaSubTab('nc');
  } else if (acao === 'FILA_SUGERIDOS') {
    switchTab('mod-fila');
    switchFilaSubTab('sug');
  } else {
    switchTab('mod-extrato');
  }
}

// ============================================================================
// 11. MÓDULO 6: SINCRONIZADOR HÍBRIDO (.XLSX <-> SQLITE) E PARÂMETROS
// ============================================================================
async function salvarParametros() {
  try {
    await apiPost('/api/parametros', {
      saldo_inicial_cc: document.getElementById('param-saldo-cc').value,
      saldo_inicial_aplicacao: document.getElementById('param-saldo-apl').value,
      rendimentos_aplicacao: document.getElementById('param-rend-apl').value,
    });
    showToast('Parâmetros contábeis salvos e saldos recalculados!');
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function resetDatabaseToOriginal() {
  try {
    const res = await apiPost('/api/xlsx/reset', {});
    showToast(res.mensagem);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function uploadXlsxFile() {
  const inp = document.getElementById('input-xlsx-upload');
  if (!inp.files || inp.files.length === 0) {
    showToast('Selecione um arquivo .xlsx antes de importar.', true);
    return;
  }
  const file = inp.files[0];
  const reader = new FileReader();
  reader.onload = async (e) => {
    try {
      const bytes = new Uint8Array(e.target.result);
      let binary = '';
      for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      const b64 = btoa(binary);
      const res = await apiPost('/api/xlsx/upload', { file_base64: b64 });
      showToast(res.mensagem);
      await refreshAllActiveViews();
    } catch (err) {
      showToast(err.message, true);
    }
  };
  reader.readAsArrayBuffer(file);
}


// ============================================================================
// 12. DESCONSIDERAR NO RATEIO
// ============================================================================
function onToggleDesconsiderarModal() {
  const chk = document.getElementById('mrat-desconsiderar');
  const area = document.getElementById('mrat-rateio-area');
  const box = document.getElementById('mrat-descons-box');
  const on = chk.checked;
  area.style.display = on ? 'none' : 'block';
  box.classList.toggle('active', on);
  updateRateioModalCalculator();
}

async function toggleDesconsiderar(idLanc, desconsiderar) {
  const msg = desconsiderar
    ? `Desconsiderar ${idLanc} no rateio?\n\nEle continua no extrato e no saldo, mas sai da Prestação de Contas e do Dashboard.`
    : `Reativar ${idLanc} no rateio?\n\nEle volta como PENDENTE para ser classificado.`;
  if (!confirm(msg)) return;
  try {
    const res = await apiPost('/api/extrato/desconsiderar-rateio', { ids_lanc: [idLanc], desconsiderar });
    showToast(res.mensagem);
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// 13. EDITAR LANÇAMENTO
// ============================================================================
async function openEditarLancamentoModal(idLanc) {
  try {
    const data = await apiGet(`/api/extrato?id_lanc=${encodeURIComponent(idLanc)}`);
    if (!data.itens || data.itens.length === 0) throw new Error(`Lançamento ${idLanc} não encontrado.`);
    const m = data.itens[0];
    const valor = fromCents(toCents(m.entrada) + toCents(m.saida) + toCents(m.aplicacao) + toCents(m.resgate));

    const selPag = document.getElementById('elanc-tipo-pag');
    const tipos = (STATE.bootstrap && STATE.bootstrap.tipos_pagamento) || ['PIX', 'BOLETO', 'TRANSFERÊNCIA', 'TED', 'OUTROS'];
    const listaPag = tipos.includes(m.tipo_pagamento) || !m.tipo_pagamento ? tipos : [m.tipo_pagamento, ...tipos];
    selPag.innerHTML = listaPag.map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join('');

    document.getElementById('elanc-title').textContent = `✎ Editar Lançamento — ${m.id_lanc}`;
    document.getElementById('elanc-id').value = m.id_lanc;
    document.getElementById('elanc-data').value = (m.data || '').slice(0, 10);
    document.getElementById('elanc-tipo-mov').value = m.tipo_movimentacao || 'SAÍDA';
    selPag.value = m.tipo_pagamento || 'PIX';
    document.getElementById('elanc-valor').value = valor.toFixed(2);
    document.getElementById('elanc-historico').value = m.historico_banco || '';
    document.getElementById('elanc-fornecedor').value = m.fornecedor_favorecido || '';
    document.getElementById('elanc-documento').value = m.documento || '';
    document.getElementById('elanc-status').value = m.status_conciliacao || 'Conciliado';
    document.getElementById('elanc-obs').value = m.observacao || '';

    const isDesc = m.status_rateio === 'DESCONSIDERADO' || Number(m.desconsiderar_rateio) === 1;
    document.getElementById('elanc-desconsiderar').checked = isDesc;
    document.getElementById('elanc-descons-box').classList.toggle('active', isDesc);

    const qtdRat = (m.rateios || []).length;
    const aviso = document.getElementById('elanc-aviso-rateio');
    if (qtdRat > 1 && !isDesc) {
      aviso.style.display = 'block';
      aviso.innerHTML = `Este lançamento está dividido em <strong>${qtdRat} linhas de rateio</strong>. Se mudar o valor, abra o <strong>Ratear</strong> depois para ajustar as linhas (senão ficará como DIVERGÊNCIA).`;
    } else {
      aviso.style.display = 'none';
    }

    STATE.editLancValorOriginal = valor;
    document.getElementById('modal-editar-lanc').classList.add('open');
  } catch (err) {
    showToast(err.message, true);
  }
}

function closeEditarLancamentoModal() {
  document.getElementById('modal-editar-lanc').classList.remove('open');
}

async function salvarEdicaoLancamento() {
  const idLanc = document.getElementById('elanc-id').value;
  const valor = parseFloat(document.getElementById('elanc-valor').value || '0');
  if (!(valor > 0)) {
    showToast('Informe um valor maior que zero.', true);
    return;
  }
  if (!document.getElementById('elanc-data').value) {
    showToast('Informe a data do lançamento.', true);
    return;
  }
  try {
    await apiPost('/api/extrato/editar-lancamento', {
      id_lanc: idLanc,
      data: document.getElementById('elanc-data').value,
      tipo_movimentacao: document.getElementById('elanc-tipo-mov').value,
      tipo_pagamento: document.getElementById('elanc-tipo-pag').value,
      valor,
      historico_banco: document.getElementById('elanc-historico').value,
      fornecedor_favorecido: document.getElementById('elanc-fornecedor').value,
      documento: document.getElementById('elanc-documento').value,
      status_conciliacao: document.getElementById('elanc-status').value,
      observacao: document.getElementById('elanc-obs').value,
      desconsiderar_rateio: document.getElementById('elanc-desconsiderar').checked,
    });
    showToast(`Lançamento ${idLanc} atualizado com sucesso!`);
    closeEditarLancamentoModal();
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function excluirLancamento() {
  const idLanc = document.getElementById('elanc-id').value;
  if (!confirm(`Excluir DEFINITIVAMENTE o lançamento ${idLanc} e todos os seus rateios?\n\nUse apenas para lançamentos duplicados ou digitados por engano.`)) return;
  try {
    await apiPost('/api/extrato/excluir', { id_lanc: idLanc });
    showToast(`Lançamento ${idLanc} excluído.`);
    closeEditarLancamentoModal();
    await refreshAllActiveViews();
  } catch (err) {
    showToast(err.message, true);
  }
}

// Theme and shell controls share semantic CSS tokens with all existing modules.
function refreshIcons() {
  if (window.lucide && document.querySelector('i[data-lucide]')) lucide.createIcons();
}

function updateChartTheme() {
  if (!window.Chart) return;
  const css = getComputedStyle(document.documentElement);
  const token = (name) => css.getPropertyValue(name).trim();
  Chart.defaults.color = token('--text-secondary');
  Chart.defaults.borderColor = token('--chart-grid');
  Object.values(STATE.charts).forEach((chart) => {
    chart.options.color = token('--text-secondary');
    chart.options.plugins.legend.labels.color = token('--text-secondary');
    Object.assign(chart.options.plugins.tooltip, {
      backgroundColor: token('--tooltip-bg'), titleColor: token('--tooltip-text'),
      bodyColor: token('--tooltip-text'), borderColor: token('--border'), borderWidth: 1,
    });
    Object.values(chart.options.scales || {}).forEach((scale) => {
      scale.ticks.color = token('--text-secondary');
      scale.grid.color = token('--chart-grid');
      scale.border.color = token('--chart-grid');
      if (scale.title) scale.title.color = token('--text-secondary');
    });
    chart.update('none');
  });
}

function applyTheme(theme, persist = true) {
  const dark = theme === 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  if (persist) {
    try { localStorage.setItem('biorenal.theme', dark ? 'dark' : 'light'); } catch (_) { /* Optional persistence. */ }
  }
  const button = document.getElementById('btn-theme-toggle');
  button.setAttribute('aria-pressed', String(dark));
  button.setAttribute('aria-label', dark ? 'Ativar tema claro' : 'Ativar tema escuro');
  button.title = dark ? 'Tema escuro · alternar para claro' : 'Tema claro · alternar para escuro';
  button.innerHTML = `<i data-lucide="${dark ? 'sun' : 'moon'}" aria-hidden="true"></i>`;
  updateChartTheme();
  refreshIcons();
}

function toggleTheme() { applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'); }

function toggleSidebar(force) {
  const collapsed = typeof force === 'boolean' ? force : !document.documentElement.classList.contains('sidebar-collapsed');
  document.documentElement.classList.toggle('sidebar-collapsed', collapsed);
  const button = document.getElementById('btn-sidebar-toggle');
  button.setAttribute('aria-expanded', String(!collapsed));
  button.setAttribute('aria-label', collapsed ? 'Expandir menu' : 'Recolher menu');
  button.innerHTML = `<i data-lucide="${collapsed ? 'panel-left-open' : 'panel-left-close'}" aria-hidden="true"></i>`;
  try { localStorage.setItem('biorenal.sidebar.collapsed', String(collapsed)); } catch (_) { /* Optional persistence. */ }
  refreshIcons();
}

function initAppShell() {
  applyTheme(document.documentElement.dataset.theme, false);
  try { toggleSidebar(localStorage.getItem('biorenal.sidebar.collapsed') === 'true'); } catch (_) { /* Keep expanded. */ }
  const observer = new MutationObserver(refreshIcons);
  observer.observe(document.body, { childList: true, subtree: true });
  window.addEventListener('storage', (event) => {
    if (event.key === 'biorenal.theme' && ['dark', 'light'].includes(event.newValue)) applyTheme(event.newValue, false);
  });
  window.addEventListener('beforeprint', () => {
    const root = document.getElementById('print-report-root');
    if (!root.children.length) {
      const preview = document.getElementById('dre-official-container');
      root.innerHTML = STATE.activeTab === 'mod-dre' && !preview.hidden && preview.querySelector('.official-page')
        ? preview.innerHTML : '<p>Abra Prestação de Contas e use “Exportar mês em PDF” ou “Exportar selecionados”.</p>';
    }
  });
  window.addEventListener('afterprint', () => { document.getElementById('print-report-root').replaceChildren(); });
}

// Official monthly statements always use full cash data, independently of analytics filters.
const REPORT_MONTHS = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro'];
const HD_GROUP = 'DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS';
let dreView = 'analitica';
let dreRequest = 0;
let officialRequest = 0;
let reportExportBusy = false;

function setDreView(view) {
  dreView = view;
  const official = view === 'oficial';
  document.getElementById('dre-report-container').hidden = official;
  document.getElementById('dre-official-container').hidden = !official;
  document.getElementById('dre-analytic-actions').hidden = official;
  ['analitica', 'oficial'].forEach((key) => {
    const button = document.getElementById(`dre-view-${key}`);
    button.classList.toggle('active', key === view);
    button.setAttribute('aria-pressed', String(key === view));
  });
  loadDreReport().catch((error) => showToast(error.message, true));
}

function onOfficialMonthChange() {
  if (dreView === 'oficial') loadOfficialPreview();
}

function officialAmount(value) {
  return toCents(value) === 0 ? '-' : Number(value).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function officialRow(label, value, cssClass = '', note = '') {
  return `<tr class="${cssClass}"><td>${escapeHtml(label)}${note ? ` <em>${escapeHtml(note)}</em>` : ''}</td><td>${value === null ? '' : officialAmount(value)}</td></tr>`;
}

function renderOfficialMonth(data, month) {
  const name = REPORT_MONTHS[month - 1];
  if (!name) throw new Error('Selecione um mês de janeiro a outubro de 2026.');
  let first = officialRow('ENTRADAS', data.entradas.total_liquido_prestacao, 'official-entry');
  data.entradas.itens.forEach((item) => {
    if (item.subcategoria === 'Resgate do Financiamento (Banco do Nordeste)' && !toCents(item.valor)) return;
    first += officialRow(item.descricao, item.valor, '', item.observacao_resumo);
  });
  first += officialRow('DESPESAS', data.despesas.total, 'official-expense');
  let second = '';
  let afterBreak = false;
  data.despesas.grupos.forEach((group) => {
    const rows = group.subcategorias.map((sub) => officialRow(sub.subcategoria, sub.valor, '', sub.observacao_resumo));
    const heading = officialRow(group.categoria, group.total, 'official-group');
    if (group.categoria === HD_GROUP) {
      const split = group.subcategorias.findIndex((sub) => sub.subcategoria === 'CDL e Perm-cath') + 1;
      first += heading + rows.slice(0, split).join('');
      second += officialRow(`${group.categoria} (continuação)`, null, 'official-group') + rows.slice(split).join('');
      afterBreak = true;
    } else if (afterBreak) second += heading + rows.join('');
    else first += heading + rows.join('');
  });
  second += officialRow(data.fechamento.titulo, null, 'official-balance');
  second += officialRow('Saldo final em Conta Corrente', data.fechamento.saldo_final_cc);
  second += officialRow('TOTAL', data.fechamento.total, 'official-total');
  const alerts = (data.avisos || []).length
    ? `<p class="official-discrepancy">Conferência pendente: ${data.nao_classificados.quantidade} rateios não classificados. Diferença para o banco: ${fmtBRL(data.diferenca_saldo_bancario)}.</p>` : '';
  return [first, second].map((rows, index) => `<article class="official-page" aria-label="${name} de 2026, página ${index + 1} de 2">
    <header class="official-header"><div class="official-brand"><img src="/img/logo-biorenal.png" alt="Logomarca BioRenal" /><div><strong>BIORENAL</strong><small>Centro de Hemodiálise de Santa Inês</small></div></div><div class="official-period">${name} / 2026<small>Prestação de contas</small></div></header>
    <table class="official-table"><colgroup><col /><col style="width:31mm" /></colgroup><thead><tr><th>DESCRIÇÃO E OBSERVAÇÕES</th><th>VALOR (R$)</th></tr></thead><tbody>${rows}</tbody></table>
    <footer class="official-footer"><p>${escapeHtml(data.nota_rodape)}</p>${alerts}<div><span>${name}/2026 - ${index + 1}/2</span><span>Página ${index + 1} de 2</span></div></footer>
  </article>`).join('');
}

async function loadOfficialPreview() {
  const request = ++officialRequest;
  const month = Number(document.getElementById('dre-month').value);
  const container = document.getElementById('dre-official-container');
  container.replaceChildren();
  document.getElementById('dre-status').textContent = 'Carregando folha mensal…';
  try {
    const data = await apiGet(`/api/prestacao-contas?periodo=${month}&regime=CAIXA`);
    if (request !== officialRequest) return;
    container.innerHTML = renderOfficialMonth(data, month);
    document.getElementById('dre-status').textContent = (data.avisos || []).join(' ');
  } catch (error) {
    if (request === officialRequest) document.getElementById('dre-status').textContent = `Não foi possível carregar a folha: ${error.message}`;
  }
}

async function exportOfficialReport(batch) {
  if (reportExportBusy) return;
  const months = batch
    ? [...document.querySelectorAll('input[name="dre-batch-month"]:checked')].map((input) => Number(input.value))
    : [Number(document.getElementById('dre-month').value)];
  if (!months.length) { showToast('Selecione pelo menos um mês para exportar.', true); return; }
  const root = document.getElementById('print-report-root');
  root.replaceChildren();
  reportExportBusy = true;
  const status = document.getElementById('dre-status');
  status.textContent = `Preparando ${months.length * 2} páginas A4…`;
  try {
    // Fetch all selected months before opening print; partial batches are never emitted.
    const reports = await Promise.all(months.map((month) => apiGet(`/api/prestacao-contas?periodo=${month}&regime=CAIXA`)));
    root.innerHTML = reports.map((data, index) => renderOfficialMonth(data, months[index])).join('');
    // Measure at paper width before printing to avoid silently clipping future long notes.
    root.style.cssText = 'display:block; position:absolute; left:-10000px; top:0';
    await document.fonts.ready;
    const overflow = [...root.querySelectorAll('.official-page')].some((page) => {
      const table = page.querySelector('table').getBoundingClientRect();
      const footer = page.querySelector('footer').getBoundingClientRect();
      return table.bottom > footer.top || page.scrollHeight > page.clientHeight + 1;
    });
    root.style.cssText = '';
    if (overflow) throw new Error('O conteúdo excede duas páginas. Revise as observações antes de exportar.');
    status.textContent = `${months.length} mês(es), ${months.length * 2} páginas. Salve como PDF na janela de impressão.`;
    window.print();
  } catch (error) {
    root.style.cssText = '';
    root.replaceChildren();
    status.textContent = `Exportação não concluída: ${error.message}`;
    showToast(error.message, true);
  } finally { reportExportBusy = false; }
}
