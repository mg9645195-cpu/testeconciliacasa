/* Notas e estimativas tributárias. O banco SQLite é a fonte de verdade. */
let TRIBUTOS = null;

const TRIB_LABELS = {
  pis: 'PIS (%)', cofins: 'Cofins (%)',
  irpj_presuncao: 'IRPJ · base presumida (%)', irpj_aliquota: 'IRPJ · alíquota (%)',
  irpj_adicional: 'IRPJ · adicional (%)', irpj_limite_trimestre: 'IRPJ · limite trimestral do adicional (R$)',
  csll_presuncao: 'CSLL · base presumida (%)', csll_aliquota: 'CSLL · alíquota (%)',
};

function tribNumber(value) { return Number(value || 0); }
function tribMoneyOrDash(value) { return value === null || value === undefined ? 'A configurar' : fmtBRL(value); }

async function loadTributos() {
  const year = document.getElementById('trib-ano').value || '2026';
  const data = await apiGet(`/api/tributos?ano=${encodeURIComponent(year)}`);
  TRIBUTOS = data;
  await LocalDB.saveSnapshot('tributos-' + year, data);
  const pending = data.sem_data_recebimento;
  document.getElementById('trib-status').textContent = `${data.notas.length} notas listadas · ${pending} emitidas sem data de recebimento. ${data.criterio}`;
  const totalGross = data.mensal.reduce((sum, row) => sum + toCents(row.bruto_recebido), 0);
  const totalIr = data.mensal.reduce((sum, row) => sum + toCents(row.irrf_retido), 0);
  document.getElementById('trib-kpis').innerHTML = [
    ['Recebido no período', fmtBRL(fromCents(totalGross))],
    ['IRRF retido nas notas', fmtBRL(fromCents(totalIr))],
    ['Notas sem recebimento', String(pending)],
  ].map(([label, value]) => `<div class="card trib-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('');
  document.getElementById('trib-notas-body').innerHTML = data.notas.length ? data.notas.map((note) => {
    const withheld = ['pis', 'cofins', 'csll', 'irrf'].reduce((sum, key) => sum + toCents(note['ret_' + key]), 0);
    return `<tr><td><span class="tab-badge badge-teal">${note.tipo === 'EMITIDA' ? 'Emitida' : 'Tomada'}</span><br />${escapeHtml(note.numero)}</td><td>${escapeHtml(note.empresa)}<small class="trib-muted">${escapeHtml(note.descricao || '')}</small></td><td>${fmtDateBR(note.emissao)}</td><td>${escapeHtml(note.competencia_servico)}</td><td>${note.data_financeira ? fmtDateBR(note.data_financeira) : '<span class="tab-badge badge-amber">Não informado</span>'}</td><td class="num">${fmtBRL(note.bruto)}</td><td class="num">${fmtBRL(fromCents(withheld))}</td><td class="num">${fmtBRL(note.liquido)}</td><td><button class="btn btn-outline btn-sm" onclick="openTributoNota(${note.id})"><i data-lucide="pencil"></i>Editar</button></td></tr>`;
  }).join('') : '<tr><td colspan="9" class="empty-table-cell">Nenhuma nota. Importe a planilha ou cadastre uma nota.</td></tr>';
  const obligation = new Map(data.obrigacoes.filter((item) => item.tipo === 'MENSAL').map((item) => [`${item.periodo_apuracao}-${item.tributo}`, item]));
  document.getElementById('trib-mensal-body').innerHTML = data.mensal.length ? data.mensal.map((row) => `<tr><td>${escapeHtml(row.mes)}</td><td class="num">${fmtBRL(row.bruto_recebido)}</td><td class="num">${fmtBRL(row.irrf_retido)}</td><td class="num">${fmtBRL(obligation.get(`${row.mes}-PIS`)?.valor_estimado || 0)}</td><td class="num">${fmtBRL(obligation.get(`${row.mes}-COFINS`)?.valor_estimado || 0)}</td><td>${escapeHtml(obligation.get(`${row.mes}-PIS`)?.mes_previsto_pagamento || '—')}</td></tr>`).join('') : '<tr><td colspan="6" class="empty-table-cell">Informe a data de recebimento das notas emitidas.</td></tr>';
  document.getElementById('trib-trimestral-body').innerHTML = data.trimestral.length ? data.trimestral.map((row) => `<tr><td>${escapeHtml(row.trimestre)}</td><td class="num">${fmtBRL(row.base_recebida)}</td><td class="num">${tribMoneyOrDash(row.irpj_estimado)}</td><td class="num">${tribMoneyOrDash(row.csll_estimada)}</td><td>${escapeHtml(row.mes_previsto_pagamento)}</td></tr>`).join('') : '<tr><td colspan="5" class="empty-table-cell">Ainda não há recebimentos.</td></tr>';
  document.getElementById('trib-guias-body').innerHTML = data.guias.length ? data.guias.map((guide) => `<tr><td>${escapeHtml(guide.tributo)}<small class="trib-muted">${escapeHtml(guide.documento || guide.observacao)}</small></td><td>${escapeHtml(guide.tipo)}</td><td>${escapeHtml(guide.competencia)}</td><td class="num">${fmtBRL(guide.base)}</td><td>${guide.aliquota ? fmtPct(Number(guide.aliquota) * 100) : '—'}</td><td class="num">${fmtBRL(guide.valor)}</td><td>${escapeHtml(guide.mes_previsto_pagamento)}</td><td>${guide.data_pagamento ? fmtDateBR(guide.data_pagamento) : '—'}</td><td><span class="tab-badge ${guide.status === 'PAGO' ? 'badge-emerald' : 'badge-amber'}">${guide.status}</span></td><td><button class="btn btn-outline btn-sm" onclick="openTributoGuia(${guide.id})">Editar</button></td></tr>`).join('') : '<tr><td colspan="10" class="empty-table-cell">Nenhuma guia cadastrada.</td></tr>';
  document.getElementById('trib-config-fields').innerHTML = Object.entries(TRIB_LABELS).map(([key, label]) => {
    const raw = data.config[key];
    const shown = raw === '' ? '' : key === 'irpj_limite_trimestre' ? raw : String(Number(raw) * 100);
    return `<label>${escapeHtml(label)}<input type="number" min="0" ${key === 'irpj_limite_trimestre' ? '' : 'max="100"'} step="0.0001" data-trib-config="${key}" value="${escapeHtml(shown)}" placeholder="A confirmar" /></label>`;
  }).join('');
  if (window.lucide) lucide.createIcons();
}

function openTributoNota(id = null) {
  const note = id === null ? null : TRIBUTOS?.notas.find((item) => item.id === id);
  let card = document.getElementById('trib-editor');
  if (!card) {
    card = document.createElement('div');
    card.id = 'trib-editor';
    card.className = 'card trib-editor';
    document.getElementById('mod-tributos').insertBefore(card, document.getElementById('trib-kpis'));
  }
  const fields = [
    ['tipo', 'Tipo', 'select'], ['numero', 'Número da NF', 'text'], ['empresa', 'Empresa / tomador', 'text'],
    ['emissao', 'Emissão', 'date'], ['competencia_servico', 'Competência do serviço (AAAA-MM)', 'month'],
    ['data_financeira', 'Recebido / pago em', 'date'], ['bruto', 'Valor bruto (R$)', 'number'],
    ['ret_pis', 'PIS retido (R$)', 'number'], ['ret_cofins', 'Cofins retida (R$)', 'number'],
    ['ret_csll', 'CSLL retida (R$)', 'number'], ['ret_irrf', 'IRRF retido (R$)', 'number'],
    ['descricao', 'Descrição / referência', 'text'],
  ];
  card.innerHTML = `<div class="card-header"><h3 class="card-title">${note ? 'Editar nota' : 'Cadastrar nota'}</h3><button class="btn btn-outline btn-sm" onclick="document.getElementById('trib-editor').remove()">Fechar</button></div><form id="trib-form" onsubmit="saveTributoNota(event)"><input type="hidden" name="id" value="${note?.id || ''}" /><div class="tributos-config">${fields.map(([key, label, type]) => `<label>${escapeHtml(label)}${type === 'select' ? `<select name="tipo"><option value="EMITIDA" ${note?.tipo === 'TOMADA' ? '' : 'selected'}>Emitida · recebimento do Estado</option><option value="TOMADA" ${note?.tipo === 'TOMADA' ? 'selected' : ''}>Tomada · serviço pago</option></select>` : `<input name="${key}" type="${type}" ${type === 'number' ? 'min="0" step="0.01"' : ''} value="${escapeHtml(note?.[key] ?? (key === 'bruto' || key.startsWith('ret_') ? '0' : ''))}" ${['numero', 'empresa', 'emissao', 'bruto'].includes(key) ? 'required' : ''} />`}</label>`).join('')}</div><button class="btn btn-teal" type="submit"><i data-lucide="save"></i>Salvar nota</button></form>`;
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (window.lucide) lucide.createIcons();
}

async function saveTributoNota(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    await apiPost('/api/tributos/nota', data);
    document.getElementById('trib-editor').remove();
    showToast('Nota salva no banco local.');
    await loadTributos();
  } catch (error) { showToast(error.message, true); }
}

function openTributoGuia(id = null) {
  const guide = id === null ? null : TRIBUTOS?.guias.find((item) => item.id === id);
  let card = document.getElementById('trib-guia-editor');
  if (!card) {
    card = document.createElement('div');
    card.id = 'trib-guia-editor';
    card.className = 'card trib-editor';
    document.getElementById('mod-tributos').insertBefore(card, document.getElementById('trib-kpis'));
  }
  const fields = [
    ['tributo', 'Tributo', 'text'], ['documento', 'Documento / DARF', 'text'],
    ['tipo', 'Periodicidade', 'select'], ['competencia', 'Competência', 'month'],
    ['base', 'Base de cálculo (R$)', 'number'], ['aliquota', 'Alíquota (%)', 'number'],
    ['valor', 'Valor confirmado (R$)', 'number'], ['mes_previsto_pagamento', 'Mês previsto', 'month'],
    ['data_pagamento', 'Pago em', 'date'], ['observacao', 'Observação', 'text'],
  ];
  card.innerHTML = `<div class="card-header"><h3 class="card-title">${guide ? 'Editar guia' : 'Registrar tributo / guia'}</h3><button class="btn btn-outline btn-sm" onclick="document.getElementById('trib-guia-editor').remove()">Fechar</button></div><p class="card-subtitle">Se informar base e alíquota, o valor será calculado. Caso contrário, use o valor confirmado na guia.</p><form id="trib-guia-form" onsubmit="saveTributoGuia(event)"><input type="hidden" name="id" value="${guide?.id || ''}" /><div class="tributos-config">${fields.map(([key, label, type]) => `<label>${escapeHtml(label)}${type === 'select' ? `<select name="tipo">${['MENSAL', 'TRIMESTRAL', 'AVULSO'].map((option) => `<option value="${option}" ${guide?.tipo === option ? 'selected' : ''}>${option}</option>`).join('')}</select>` : `<input name="${key}" type="${type}" ${type === 'number' ? 'min="0" step="0.0001"' : ''} value="${escapeHtml(key === 'aliquota' && guide?.aliquota ? Number(guide.aliquota) * 100 : guide?.[key] ?? '')}" ${['tributo', 'competencia', 'mes_previsto_pagamento'].includes(key) ? 'required' : ''} />`}</label>`).join('')}</div><button class="btn btn-teal" type="submit">Salvar guia</button></form>`;
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function saveTributoGuia(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget).entries());
  data.aliquota = data.aliquota === '' ? '' : String(Number(data.aliquota) / 100);
  try {
    await apiPost('/api/tributos/guia', data);
    document.getElementById('trib-guia-editor').remove();
    showToast('Guia salva no banco local.');
    await loadTributos();
  } catch (error) { showToast(error.message, true); }
}

async function saveTributosConfig() {
  const config = {};
  document.querySelectorAll('[data-trib-config]').forEach((input) => {
    config[input.dataset.tribConfig] = input.value === '' ? '' : input.dataset.tribConfig === 'irpj_limite_trimestre' ? input.value : String(Number(input.value) / 100);
  });
  try {
    await apiPost('/api/tributos/config', { config });
    showToast('Parâmetros salvos. Confira os valores com a contabilidade.');
    await loadTributos();
  } catch (error) { showToast(error.message, true); }
}

async function importTributos(input) {
  const file = input.files?.[0];
  if (!file) return;
  try {
    if (file.size > 10_000_000) throw new Error('Planilha acima do limite de 10 MB.');
    const base64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Falha ao ler a planilha.'));
      reader.onload = () => resolve(String(reader.result).split(',')[1]);
      reader.readAsDataURL(file);
    });
    const result = await apiPost('/api/tributos/importar', { file_base64: base64 });
    showToast(`${result.importadas} notas importadas; ${result.ja_existentes} já existentes preservadas.`);
    await loadTributos();
  } catch (error) { showToast(error.message, true); }
  finally { input.value = ''; }
}
