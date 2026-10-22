/* Programação semanal e prestadores. Persistência exclusiva no SQLite local. */
let PROGRAMACAO = { itens: [], documentos_extrato: [] };
let PRESTADORES = { itens: [], cadastros: [] };
let LAST_PROVIDER_PDF_IDS = [];

function payMoney(value) { return value === null || value === undefined ? 'A confirmar' : fmtBRL(value); }
function payChecked(id, kind) { return document.querySelector(`input[data-${kind}-select="${id}"]`)?.checked || false; }
function payDate(value) { return value ? fmtDateBR(value) : '—'; }
function payEsc(value) { return escapeHtml(value ?? ''); }
function payIcons() { if (window.lucide) lucide.createIcons(); }
function payStatusBadge(value) {
  const cls = ['PAGO','CONFERIDO'].includes(value) ? 'badge-emerald' :
    ['DIVERGENTE','ATRASADO','CANCELADO'].includes(value) ? 'badge-coral' :
    ['ENVIADO'].includes(value) ? 'badge-teal' : 'badge-amber';
  return `<span class="tab-badge ${cls}">${payEsc(value.replaceAll('_',' '))}</span>`;
}

function paySetWeek() {
  const a = document.getElementById('pag-inicio');
  const b = document.getElementById('pag-fim');
  if (a.value && b.value) return;
  const today = new Date();
  const sunday = new Date(today.getFullYear(),today.getMonth(),today.getDate()-today.getDay());
  const saturday = new Date(sunday.getFullYear(),sunday.getMonth(),sunday.getDate()+6);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  a.value = iso(sunday); b.value = iso(saturday);
}

async function loadProgramacao(all = false) {
  paySetWeek();
  const start = document.getElementById('pag-inicio').value;
  const end = document.getElementById('pag-fim').value;
  if (start > end) throw new Error('O início da semana deve preceder o fim.');
  const query = all ? '' : `?inicio=${encodeURIComponent(start)}&fim=${encodeURIComponent(end)}`;
  PROGRAMACAO = await apiGet('/api/programacao' + query);
  const items = PROGRAMACAO.itens;
  const open = items.filter(x => !['PAGO','CANCELADO'].includes(x.status));
  const total = open.reduce((sum,x) => sum + (x.valor === null ? 0 : toCents(x.valor)),0);
  document.getElementById('pag-resumo').textContent = `${items.length} lançamento(s) · ${open.length} em aberto · ${fmtBRL(fromCents(total))} confirmado · ${open.filter(x => x.valor === null).length} a confirmar. Marque as linhas que deverão entrar no PDF.`;
  document.getElementById('pag-body').innerHTML = items.length ? items.map(x => {
    const eligible = x.valor !== null && !['PAGO','CANCELADO'].includes(x.status);
    const inWeek = x.vencimento >= start && x.vencimento <= end;
    return `<tr class="${x.anomalia ? 'payment-anomaly' : ''}">
      <td><input type="checkbox" data-pag-select="${x.id}" ${eligible && inWeek ? 'checked' : ''} ${eligible ? '' : 'disabled'} aria-label="Incluir ${payEsc(x.favorecido)} no relatório" /></td>
      <td>${payDate(x.vencimento)}${!inWeek ? '<small class="payment-note">Fora da semana</small>' : ''}${x.anomalia ? '<small class="payment-warning">Data fora da aba de origem</small>' : ''}</td>
      <td>${payEsc(x.tipo)}<small class="payment-note">${payEsc(x.nf)}</small></td>
      <td>${x.documento_url ? `<a class="payment-link payment-payee-link" href="${payEsc(x.documento_url)}" target="_blank" rel="noopener noreferrer">${payEsc(x.favorecido)}</a>` : `<strong>${payEsc(x.favorecido)}</strong>`}<small class="payment-note">${payEsc(x.observacoes)}</small></td>
      <td class="num">${payMoney(x.valor)}</td><td>${payStatusBadge(x.dda_status)}${x.dda_valor !== null ? `<small class="payment-note">DDA: ${fmtBRL(x.dda_valor)}${x.dda_vencimento ? ' · '+payDate(x.dda_vencimento) : ''}</small>` : ''}</td>
      <td>${payStatusBadge(x.status)}${x.pago_em ? `<small class="payment-note">${payDate(x.pago_em)}</small>` : ''}</td>
      <td>${x.extrato_id_lanc ? `<strong>${payEsc(x.extrato_id_lanc)}</strong><small class="payment-note">${x.extrato_status_rateio === 'RATEIO OK' ? 'Rateio OK' : 'Rateio pendente'}</small>` : '—'}</td>
      <td><div class="payment-actions"><button class="btn btn-outline btn-sm" onclick="openPagamentoEditor(${x.id})">Editar</button>${x.status === 'PAGO' ? `<button class="btn btn-outline btn-sm" onclick="openConciliacaoPagamento(${x.id})">${x.extrato_id_lanc ? 'Revisar vínculo' : 'Conciliar'}</button>` : ''}</div></td></tr>`;
  }).join('') : '<tr><td colspan="9" class="empty-table-cell">Nenhum gasto neste intervalo. Ajuste as datas ou importe a planilha.</td></tr>';
  document.getElementById('pag-links').innerHTML = PROGRAMACAO.documentos_extrato.length ? PROGRAMACAO.documentos_extrato.map(x =>
    `<a href="${payEsc(x.url)}" target="_blank" rel="noopener noreferrer" class="payment-doc"><strong>${payEsc(x.id_lanc)}</strong> · ${payDate(x.data)}<small>${payEsc(x.historico)}</small></a>`).join('') : '<p class="report-scope">Nenhum link lido da conciliação.</p>';
  payIcons();
}

function openPagamentoEditor(id = null) {
  const item = id === null ? null : PROGRAMACAO.itens.find(x => x.id === id);
  const slot = document.getElementById('pag-editor-slot');
  slot.innerHTML = `<div class="card payment-editor"><div class="card-header"><h3 class="card-title">${item ? 'Editar gasto previsto' : 'Novo gasto previsto'}</h3><button class="btn btn-outline btn-sm" onclick="document.getElementById('pag-editor-slot').replaceChildren()">Fechar</button></div>
    <form onsubmit="savePagamento(event)"><input type="hidden" name="id" value="${item?.id || ''}" /><div class="payment-form">
      <label>Vencimento<input type="date" name="vencimento" required value="${payEsc(item?.vencimento || '')}" /></label>
      <label>Tipo<input name="tipo" value="${payEsc(item?.tipo || '')}" placeholder="Boleto, DARF, PIX…" /></label>
      <label>NF / documento<input name="nf" value="${payEsc(item?.nf || '')}" /></label>
      <label>Fornecedor / credor<input name="favorecido" required value="${payEsc(item?.favorecido || '')}" /></label>
      <label>Valor (vazio = a confirmar)<input type="number" min="0" step="0.01" name="valor" value="${item?.valor ?? ''}" /></label>
      <label>Situação<select name="status">${['PREVISTO','ENVIADO','PAGO','CANCELADO'].map(s => `<option value="${s}" ${item?.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
      <label>Conferência DDA<select name="dda_status">${['NAO_CONFERIDO','CONFERIDO','DIVERGENTE','NAO_APLICA'].map(s => `<option value="${s}" ${item?.dda_status === s ? 'selected' : ''}>${s.replaceAll('_',' ')}</option>`).join('')}</select></label>
      <label>Valor visto no DDA<input type="number" min="0" step="0.01" name="dda_valor" value="${item?.dda_valor ?? ''}" /></label>
      <label>Vencimento visto no DDA<input type="date" name="dda_vencimento" value="${payEsc(item?.dda_vencimento || '')}" /></label>
      <label>Pago em<input type="date" name="pago_em" value="${payEsc(item?.pago_em || '')}" /></label>
      <label class="payment-wide">Link HTTPS do boleto, DARF ou comprovante<input type="url" name="documento_url" value="${payEsc(item?.documento_url || '')}" placeholder="https://drive.google.com/…" /></label>
      <label class="payment-wide">Observações<textarea name="observacoes" rows="3">${payEsc(item?.observacoes || '')}</textarea></label>
    </div><button class="btn btn-teal" type="submit"><i data-lucide="save"></i>Salvar</button></form></div>`;
  slot.scrollIntoView({behavior:'smooth',block:'start'}); payIcons();
}

async function savePagamento(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget).entries());
  try { await apiPost('/api/programacao/salvar',data); document.getElementById('pag-editor-slot').replaceChildren(); await loadProgramacao(); showToast('Programação salva.'); }
  catch(error) { showToast(error.message,true); }
}

async function openConciliacaoPagamento(id) {
  const item = PROGRAMACAO.itens.find(x => x.id === id);
  if (!item) return showToast('Recarregue a programação antes de conciliar.', true);
  const slot = document.getElementById('pag-conciliacao-slot');
  slot.innerHTML = '<div class="card payment-editor">Buscando saídas bancárias do mesmo valor…</div>';
  try {
    const data = await apiGet(`/api/programacao/candidatos?id=${id}`);
    slot.innerHTML = `<div class="card payment-editor"><div class="card-header"><div><h3 class="card-title">Vincular pagamento ao extrato</h3><p class="card-subtitle">${payEsc(item.favorecido)} · ${payMoney(item.valor)} · pago em ${payDate(item.pago_em)}</p></div><button class="btn btn-outline btn-sm" onclick="document.getElementById('pag-conciliacao-slot').replaceChildren()">Fechar</button></div>
      <p class="payment-hint">Confira data, favorecido e histórico. Só aparecem saídas de mesmo valor; o vínculo não altera o rateio nem cria outro lançamento bancário.</p>
      ${data.vinculado ? `<p class="report-scope">Vínculo atual: <strong>${payEsc(data.vinculado)}</strong>. <button class="btn btn-outline btn-sm" onclick="openRateioModalById('${payEsc(data.vinculado)}')">Abrir rateio</button> <button class="btn btn-outline btn-sm" onclick="desvincularPagamento(${id})">Desvincular</button></p>` : ''}
      <div class="payment-candidates">${data.candidatos.length ? data.candidatos.map(x => `<label class="payment-candidate"><input type="radio" name="pag-candidato" value="${payEsc(x.id_lanc)}" ${x.id_lanc === data.vinculado ? 'checked' : ''} /><span><strong>${payEsc(x.id_lanc)}</strong> · ${payDate(x.data)} · ${payMoney(x.valor)}<small>${payEsc(x.fornecedor_canonico)} · ${payEsc(x.historico_banco)} · Rateio: ${payEsc(x.status_rateio)}${x.dias_distancia ? ` · ${x.dias_distancia} dia(s) da data informada` : ''}</small></span></label>`).join('') : '<p class="payment-warning">Nenhuma saída de mesmo valor está disponível no extrato. Confira o pagamento no banco e importe o extrato antes de vincular.</p>'}</div>
      ${data.candidatos.length ? `<button class="btn btn-teal" onclick="confirmarConciliacaoPagamento(${id})"><i data-lucide="link"></i>Confirmar vínculo selecionado</button>` : ''}</div>`;
    slot.scrollIntoView({behavior:'smooth',block:'start'}); payIcons();
  } catch(error) { slot.replaceChildren(); showToast(error.message,true); }
}

async function confirmarConciliacaoPagamento(id) {
  const selected = document.querySelector('input[name="pag-candidato"]:checked');
  if (!selected) return showToast('Selecione uma saída do extrato.',true);
  try {
    const result = await apiPost('/api/programacao/vincular-extrato',{id,id_lanc:selected.value});
    document.getElementById('pag-conciliacao-slot').replaceChildren();
    await loadProgramacao();
    showToast(result.status_rateio === 'RATEIO OK' ? 'Pagamento vinculado; rateio do extrato está OK.' : 'Pagamento vinculado. Revise o rateio pendente no extrato.');
  } catch(error) { showToast(error.message,true); }
}

async function desvincularPagamento(id) {
  if (!window.confirm('Desvincular este gasto do movimento bancário?')) return;
  try {
    await apiPost('/api/programacao/vincular-extrato',{id,id_lanc:''});
    document.getElementById('pag-conciliacao-slot').replaceChildren();
    await loadProgramacao();
    showToast('Vínculo removido. O movimento do extrato foi preservado.');
  } catch(error) { showToast(error.message,true); }
}

async function importarPagamentos(input,kind) {
  const file = input.files?.[0]; if (!file) return;
  try {
    if (file.size > (kind === 'links' ? 15_000_000 : 10_000_000)) throw new Error('Arquivo acima do limite permitido.');
    const base64 = await new Promise((resolve,reject) => {
      const reader = new FileReader(); reader.onerror = () => reject(new Error('Falha ao ler arquivo.'));
      reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.readAsDataURL(file);
    });
    const path = kind === 'links' ? '/api/programacao/importar-links-extrato' : kind === 'prestadores' ? '/api/prestadores/importar' : '/api/programacao/importar';
    const result = await apiPost(path,{file_base64:base64});
    showToast(Object.entries(result).filter(([key]) => key !== 'sucesso').map(([key,value]) => `${key.replaceAll('_',' ')}: ${value}`).join(' · '));
    if (kind === 'prestadores') await loadPrestadores(); else await loadProgramacao();
  } catch(error) { showToast(error.message,true); } finally { input.value=''; }
}

async function loadPrestadores() {
  const start = document.getElementById('prest-inicio').value;
  const end = document.getElementById('prest-fim').value;
  if (start && end && start > end) throw new Error('Data inicial posterior à final.');
  PRESTADORES = await apiGet(`/api/prestadores?inicio=${encodeURIComponent(start)}&fim=${encodeURIComponent(end)}`);
  renderPrestadores();
}

function renderPrestadores() {
  const filter = document.getElementById('prest-status').value;
  const dueMonth = document.getElementById('prest-mes').value;
  const competence = document.getElementById('prest-competencia').value;
  const type = document.getElementById('prest-tipo').value;
  const rows = PRESTADORES.itens.filter(x =>
    (!dueMonth || x.vencimento.startsWith(dueMonth)) &&
    (!competence || x.competencia === competence) &&
    (type === 'TODOS' || x.tipo === type) &&
    (filter === 'TODOS' || (filter === 'ABERTOS' ? x.situacao !== 'PAGO' :
      filter === 'ENVIADO' ? Boolean(x.enviado) :
      filter === 'NAO_ENVIADO' ? !x.enviado && x.situacao !== 'PAGO' : x.situacao === filter)));
  const total = rows.filter(x => x.situacao !== 'PAGO' && x.valor !== null).reduce((sum,x) => sum+toCents(x.valor),0);
  document.getElementById('prest-resumo').textContent = `${rows.length} lançamento(s) exibido(s) · ${fmtBRL(fromCents(total))} em aberto com valor confirmado · ${rows.filter(x => x.valor === null).length} a confirmar. Selecione as linhas para o relatório.`;
  document.getElementById('prest-body').innerHTML = rows.length ? rows.map(x => `<tr>
    <td><input type="checkbox" data-prest-select="${x.id}" ${x.situacao !== 'PAGO' && x.valor !== null ? '' : 'disabled'} aria-label="Incluir ${payEsc(x.nome)}" /></td>
    <td>${payEsc(x.competencia)}<small class="payment-note">NF ${payEsc(x.nf || 'pendente')}</small></td>
    <td><strong>${payEsc(x.nome)}</strong><small class="payment-note">${x.tipo === 'PLANTAO' ? 'Plantão médico' : 'Prestador / fornecedor'}</small></td>
    <td>${payEsc(x.descricao)}${x.tipo === 'PLANTAO' ? `<small class="payment-note">${x.quantidade ?? 'Qtd. a confirmar'} × ${payMoney(x.valor_unitario)}</small>` : ''}</td>
    <td>${payDate(x.vencimento)}</td><td class="num">${payMoney(x.valor)}</td><td>${payStatusBadge(x.situacao)}${x.enviado ? '<small class="payment-note">Enviado p/ pagamento</small>' : ''}</td>
    <td>${x.banco_id ? `<button class="btn btn-outline btn-sm" onclick="openBancoEditor(${x.banco_id})">Ver dados bancários</button><small class="payment-note">${x.banco_conferido ? 'Conferido' : 'A conferir'}</small>` : '<span class="tab-badge badge-coral">Sem vínculo</span>'}</td>
    <td><button class="btn btn-outline btn-sm" onclick="openPrestadorEditor(${x.id})">Editar</button></td></tr>`).join('') : '<tr><td colspan="9" class="empty-table-cell">Nenhum lançamento. Ajuste os filtros ou importe a planilha.</td></tr>';
  document.getElementById('prest-bancos-body').innerHTML = PRESTADORES.cadastros.map(x => `<tr><td>${payEsc(x.nome)}</td><td>${payEsc(x.tipo)}</td><td>${payStatusBadge(x.conferido ? 'CONFERIDO' : 'NAO_CONFERIDO')}</td><td><button class="btn btn-outline btn-sm" onclick="openBancoEditor(${x.id})">Conferir / editar</button></td></tr>`).join('');
  payIcons();
}

function openPrestadorEditor(id = null) {
  const x = id === null ? null : PRESTADORES.itens.find(row => row.id === id);
  const slot = document.getElementById('prest-editor-slot');
  slot.innerHTML = `<div class="card payment-editor"><div class="card-header"><h3 class="card-title">${x ? 'Editar lançamento' : 'Novo lançamento'}</h3><button class="btn btn-outline btn-sm" onclick="document.getElementById('prest-editor-slot').replaceChildren()">Fechar</button></div>
    <form onsubmit="savePrestador(event)"><input type="hidden" name="id" value="${x?.id || ''}" /><div class="payment-form">
    <label>Tipo<select name="tipo"><option value="PRESTADOR" ${x?.tipo === 'PLANTAO' ? '' : 'selected'}>Prestador</option><option value="PLANTAO" ${x?.tipo === 'PLANTAO' ? 'selected' : ''}>Plantão médico</option></select></label>
    <label>Competência (AAAA-MM)<input name="competencia" type="month" value="${payEsc(x?.competencia || '')}" /></label>
    <label>NF<input name="nf" value="${payEsc(x?.nf || '')}" /></label>
    <label>Prestador / médico<input name="nome" required value="${payEsc(x?.nome || '')}" /></label>
    <label>Vencimento<input type="date" name="vencimento" value="${payEsc(x?.vencimento || '')}" /></label>
    <label>Valor total (R$; vazio = a confirmar)<input type="number" min="0" step="0.01" name="valor" value="${x?.valor ?? ''}" /></label>
    <label>Quantidade de plantões<input type="number" min="0" step="0.5" name="quantidade" value="${x?.quantidade ?? ''}" /></label>
    <label>Valor por plantão<input type="number" min="0" step="0.01" name="valor_unitario" value="${x?.valor_unitario ?? ''}" /></label>
    <label>Cadastro bancário<select name="banco_id"><option value="">A vincular</option>${PRESTADORES.cadastros.map(b => `<option value="${b.id}" ${x?.banco_id === b.id ? 'selected' : ''}>${payEsc(b.nome)}${b.conferido ? ' · conferido' : ' · a conferir'}</option>`).join('')}</select></label>
    <label>Pago em<input type="date" name="pago_em" value="${payEsc(x?.pago_em || '')}" /></label>
    <label>Enviado para pagamento<select name="enviado"><option value="" ${x?.enviado ? '' : 'selected'}>Não</option><option value="1" ${x?.enviado ? 'selected' : ''}>Sim</option></select></label>
    <label class="payment-wide">Descrição<input name="descricao" value="${payEsc(x?.descricao || '')}" /></label>
    <label class="payment-wide">Observações<textarea name="observacoes">${payEsc(x?.observacoes || '')}</textarea></label>
    </div><button class="btn btn-teal" type="submit"><i data-lucide="save"></i>Salvar</button></form></div>`;
  slot.scrollIntoView({behavior:'smooth',block:'start'}); payIcons();
}

async function savePrestador(event) {
  event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget).entries());
  try { await apiPost('/api/prestadores/salvar',body); document.getElementById('prest-editor-slot').replaceChildren(); await loadPrestadores(); showToast('Lançamento salvo.'); }
  catch(error) { showToast(error.message,true); }
}

async function registrarEnvioPrestadores() {
  const selected = PRESTADORES.itens.filter(x => payChecked(x.id,'prest')).map(x => x.id);
  if (!selected.length || selected.length !== LAST_PROVIDER_PDF_IDS.length || selected.some(id => !LAST_PROVIDER_PDF_IDS.includes(id))) {
    return showToast('Selecione os mesmos lançamentos do PDF gerado nesta sessão.',true);
  }
  if (!window.confirm(`O PDF de ${selected.length} lançamento(s) foi salvo e encaminhado para pagamento?`)) return;
  try {
    const result = await apiPost('/api/prestadores/registrar-envio',{ids:selected});
    LAST_PROVIDER_PDF_IDS = [];
    await loadPrestadores();
    showToast(`${result.enviados} lançamento(s) marcados como enviados.`);
  } catch(error) { showToast(error.message,true); }
}

async function openBancoEditor(id = null) {
  try {
    const x = id === null ? null : await apiGet(`/api/prestadores/banco?id=${id}`);
    const slot = document.getElementById('prest-editor-slot');
    slot.innerHTML = `<div class="card payment-editor"><div class="card-header"><h3 class="card-title">Cadastro bancário · ${x ? payEsc(x.nome) : 'novo'}</h3><button class="btn btn-outline btn-sm" onclick="document.getElementById('prest-editor-slot').replaceChildren()">Fechar</button></div>
      <p class="payment-hint">Confira o titular e os dados diretamente com o documento de origem antes de marcar como conferido. Esta tela é local e ainda não possui controle de usuários.</p>
      <form onsubmit="saveBanco(event)"><input type="hidden" name="id" value="${x?.id || ''}" /><div class="payment-form">
      ${[['nome','Favorecido'],['tipo','Tipo'],['banco','Banco'],['agencia','Agência'],['conta','Conta'],['documento','CNPJ / CPF'],['pix','Chave PIX'],['observacoes','Observações']].map(([k,label]) => `<label>${label}<input name="${k}" value="${payEsc(x?.[k] || '')}" ${k === 'nome' ? 'required' : ''} /></label>`).join('')}
      <label>Conferência<select name="conferido"><option value="" ${x?.conferido ? '' : 'selected'}>A conferir</option><option value="1" ${x?.conferido ? 'selected' : ''}>Conferido</option></select></label>
      </div><button class="btn btn-teal" type="submit"><i data-lucide="save"></i>Salvar cadastro</button></form></div>`;
    slot.scrollIntoView({behavior:'smooth',block:'start'}); payIcons();
  } catch(error) { showToast(error.message,true); }
}

async function saveBanco(event) {
  event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget).entries());
  try { await apiPost('/api/prestadores/banco/salvar',body); document.getElementById('prest-editor-slot').replaceChildren(); await loadPrestadores(); showToast('Cadastro bancário salvo.'); }
  catch(error) { showToast(error.message,true); }
}

async function paymentPrint(html) {
  const root = document.getElementById('print-report-root');
  root.innerHTML = html;
  let style = document.getElementById('payment-page-rule');
  if (!style) { style=document.createElement('style'); style.id='payment-page-rule'; document.head.appendChild(style); }
  style.textContent='@page { size: A4 landscape; margin: 0; }';
  await Promise.all([...root.querySelectorAll('img')].map(img => img.decode().catch(() => undefined)));
  await document.fonts.ready;
  window.print();
}
window.addEventListener('afterprint',() => { document.getElementById('payment-page-rule')?.remove(); });

function paymentHeader(title,subtitle) {
  return `<header class="payment-print-header"><img src="/img/logo-biorenal.png" alt="" /><div><strong>BIORENAL</strong><small>Centro de Hemodiálise de Santa Inês</small></div><div class="payment-print-title"><strong>${payEsc(title)}</strong><small>${payEsc(subtitle)}</small></div></header>`;
}

async function printProgramacao() {
  const selected = PROGRAMACAO.itens.filter(x => payChecked(x.id,'pag'));
  if (!selected.length) { showToast('Selecione ao menos um gasto com valor confirmado.',true); return; }
  const start = document.getElementById('pag-inicio').value, end=document.getElementById('pag-fim').value;
  const sum = selected.reduce((s,x) => s+toCents(x.valor),0);
  const tr = selected.map(x => `<tr><td>${payDate(x.vencimento)}${x.vencimento < start || x.vencimento > end ? '<br><em>Fora da semana</em>' : ''}</td><td>${payEsc(x.tipo)}</td><td>${payEsc(x.nf)}</td><td>${x.documento_url ? `<a href="${payEsc(x.documento_url)}">${payEsc(x.favorecido)}</a>` : payEsc(x.favorecido)}</td><td class="num">${fmtBRL(x.valor)}</td><td>${payEsc(x.observacoes)}</td></tr>`).join('');
  await paymentPrint(`<article class="payment-print-page">${paymentHeader('PROGRAMAÇÃO DE PAGAMENTOS',`${payDate(start)} a ${payDate(end)}`)}<table class="payment-print-table weekly"><thead><tr><th>Vencimento</th><th>Tipo</th><th>NF</th><th>Fornecedor / credor</th><th class="num">Valor</th><th>Observações</th></tr></thead><tbody>${tr}</tbody><tfoot><tr><th colspan="4">TOTAL DA SELEÇÃO · ${selected.length} itens</th><th class="num">${fmtBRL(fromCents(sum))}</th><th></th></tr></tfoot></table></article>`);
}

async function printPrestadores() {
  const ids = new Set(PRESTADORES.itens.filter(x => payChecked(x.id,'prest')).map(x => x.id));
  if (!ids.size) { showToast('Selecione prestadores com valor confirmado.',true); return; }
  try {
    const start=document.getElementById('prest-inicio').value, end=document.getElementById('prest-fim').value;
    const data = await apiGet(`/api/prestadores/relatorio?inicio=${encodeURIComponent(start)}&fim=${encodeURIComponent(end)}`);
    const selected=data.itens.filter(x => ids.has(x.id));
    const unconfirmed=selected.filter(x => !x.banco_id || !x.banco_conferido);
    const sum=selected.reduce((s,x) => s+toCents(x.valor),0);
    const tr=selected.map(x => `<tr><td>${payEsc(x.nf || 'Pendente')}</td><td>${payEsc(x.nome)}<br><small>${payEsc(x.tipo === 'PLANTAO' ? `${x.quantidade ?? 'Qtd. a conferir'} plantões` : x.descricao)}</small></td><td>${payEsc(x.competencia)}</td><td>${payDate(x.vencimento)}</td><td class="num">${fmtBRL(x.valor)}</td><td>${x.banco_id ? `${payEsc(x.banco || '')} · Ag. ${payEsc(x.agencia || '')} · Conta ${payEsc(x.conta || '')}<br>${payEsc(x.pix || '')}<br>${payEsc(x.documento || '')}` : 'Cadastro não vinculado'}${!x.banco_conferido ? '<br><strong>CONFERIR FAVORECIDO E CONTA</strong>' : ''}</td></tr>`).join('');
    LAST_PROVIDER_PDF_IDS = selected.map(x => x.id);
    await paymentPrint(`<article class="payment-print-page">${paymentHeader('PAGAMENTO DE PRESTADORES E PLANTÕES',`${selected.length} pagamentos selecionados`)}<p class="payment-print-warning">${unconfirmed.length} cadastro(s) bancário(s) pendente(s) de conferência. Não encaminhar estes pagamentos sem validar o favorecido.</p><table class="payment-print-table providers"><thead><tr><th>NF</th><th>Prestador / médico</th><th>Competência</th><th>Vencimento</th><th class="num">Valor</th><th>Dados para pagamento</th></tr></thead><tbody>${tr}</tbody><tfoot><tr><th colspan="4">TOTAL DA SELEÇÃO</th><th class="num">${fmtBRL(fromCents(sum))}</th><th></th></tr></tfoot></table></article>`);
  } catch(error) { showToast(error.message,true); }
}
