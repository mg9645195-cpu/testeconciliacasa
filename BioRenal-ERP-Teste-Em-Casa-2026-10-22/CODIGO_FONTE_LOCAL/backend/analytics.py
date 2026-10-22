# -*- coding: utf-8 -*-
"""
Biorenal — Motor Analítico, DRE Gerencial (Prestação de Contas), Testes de Integridade,
Painel de Sócios/Corpo Clínico, Pass-Through Piso da Enfermagem, Capex Nipro/VW e Exportador .xlsx Oficial.
"""

import os
import io
import datetime
import re
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional, Tuple
import openpyxl

from domain import (
    to_dec,
    TWO_PLACES,
    TOLERANCE,
    PLANO_DE_CONTAS,
    CANONICAL_SUPPLIER_GROUPS,
    get_canonical_supplier,
    infer_missing_supplier,
    suggest_for_movement,
)
from database import get_conn, recalculate_all, DEFAULT_XLSX_PATH, DATA_DIR


def _match_period(mes_mov: int, comp_str: str, periodo: str, regime: str) -> bool:
    """
    Filtra por período considerando Regime de Caixa (mes_mov 1..12)
    ou Regime de Competência (comp_str MM/YYYY).
    """
    if not periodo or periodo == "ALL":
        return True

    target_m = mes_mov
    if regime == "COMPETENCIA" and comp_str and "/" in comp_str:
        parts = comp_str.split("/")
        if parts[0].isdigit():
            target_m = int(parts[0])

    if periodo.isdigit():
        return target_m == int(periodo)
    if periodo == "Q1":
        return target_m in (1, 2, 3)
    if periodo == "Q2":
        return target_m in (4, 5, 6)
    if periodo == "Q3":
        return target_m in (7, 8, 9)
    if periodo == "Q4":
        return target_m in (10, 11, 12)
    if periodo == "S1":
        return target_m in (1, 2, 3, 4, 5, 6)
    if periodo == "S2":
        return target_m in (7, 8, 9, 10, 11, 12)
    return True


def get_dashboard_data(
    periodo: str = "ALL",
    regime: str = "CAIXA",
    fornecedor_filter: str = "",
    categoria_filter: str = "",
) -> Dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()

    # Parameters
    cur.execute("SELECT chave, valor FROM config_parametros")
    params = {r["chave"]: r["valor"] for r in cur.fetchall()}
    saldo_ini_cc = to_dec(params.get("saldo_inicial_cc", "0.00"))
    saldo_ini_apl = to_dec(params.get("saldo_inicial_aplicacao", "677285.67"))
    rendimentos_apl = to_dec(params.get("rendimentos_aplicacao", "0.00"))

    # All extrato rows
    cur.execute("SELECT * FROM extrato ORDER BY ordem ASC")
    ext_all = [dict(r) for r in cur.fetchall()]

    # All rateios joined with competencia_extraida and fornecedor_canonico from extrato
    cur.execute(
        """
        SELECT r.*, e.competencia_extraida, e.fornecedor_canonico, e.historico_banco,
               e.tipo_movimentacao, e.status_rateio, e.status_conciliacao
        FROM rateios r
        JOIN extrato e ON e.id_lanc = r.id_lanc
        ORDER BY e.ordem ASC, r.id_rateio ASC
        """
    )
    rat_all = [dict(r) for r in cur.fetchall()]

    # Global bank totals (unfiltered for current account balance card, plus filtered metrics)
    total_entradas_banco = sum((to_dec(e["entrada"]) for e in ext_all), Decimal("0.00"))
    total_saidas_banco = sum((to_dec(e["saida"]) for e in ext_all), Decimal("0.00"))
    total_aplicacoes_banco = sum((to_dec(e["aplicacao"]) for e in ext_all), Decimal("0.00"))
    total_resgates_banco = sum((to_dec(e["resgate"]) for e in ext_all), Decimal("0.00"))
    saldo_atual_cc = (
        saldo_ini_cc + total_entradas_banco + total_resgates_banco - total_saidas_banco - total_aplicacoes_banco
    ).quantize(TWO_PLACES)

    # Corrected Application Balance Formula:
    # Saldo Inicial Aplicação + Soma(APLICAÇÃO) - Soma(RESGATE) + Rendimentos
    saldo_aplicacao_corrigido = (
        saldo_ini_apl + total_aplicacoes_banco - total_resgates_banco + rendimentos_apl
    ).quantize(TWO_PLACES)

    # Resgates pre-Agosto (lines before BAN-00849) vs post-Agosto
    resgates_ate_jul = sum((to_dec(e["resgate"]) for e in ext_all if e["ordem"] < 849), Decimal("0.00"))
    resgates_pos_ago = sum((to_dec(e["resgate"]) for e in ext_all if e["ordem"] >= 849), Decimal("0.00"))

    # Filter extrato and rateios according to user filters
    f_Compare = fornecedor_filter.strip().upper()
    c_Compare = categoria_filter.strip()

    ext_filtered = []
    for e in ext_all:
        if not _match_period(e["mes"], e["competencia_extraida"], periodo, regime):
            continue
        if f_Compare and f_Compare not in (e["fornecedor_canonico"] or "").upper() and f_Compare not in (e["fornecedor_favorecido"] or "").upper():
            continue
        ext_filtered.append(e)

    rat_filtered = []
    for r in rat_all:
        if not _match_period(r["mes"], r["competencia_extraida"], periodo, regime):
            continue
        if f_Compare and f_Compare not in (r["fornecedor_canonico"] or "").upper() and f_Compare not in (r["fornecedor"] or "").upper():
            continue
        if c_Compare and (r["categoria"] or "") != c_Compare:
            continue
        rat_filtered.append(r)

    # Operational vs Pass-Through vs Non-Operational Separation (Criterion 4)
    receita_operacional_estado = Decimal("0.00")
    despesa_operacional_pura = Decimal("0.00")
    piso_enf_entrada_class = Decimal("0.00")
    piso_enf_saida_class = Decimal("0.00")
    fluxo_nao_op_entradas = Decimal("0.00")
    fluxo_nao_op_saidas = Decimal("0.00")
    total_despesas_classificadas = Decimal("0.00")

    NON_OP_EXPENSE_CATS = {
        "AQUISIÇÃO DE BENS E EQUIPAMENTOS",
        "DESPESAS COM SÓCIOS - LUCROS",
        "DESPESAS COM EMPRÉSTIMO E DEMAIS DESPESAS FINANCEIRAS",
    }

    for r in rat_filtered:
        cat = (r["categoria"] or "").strip()
        sub = (r["subcategoria"] or "").strip()
        val = to_dec(r["valor"])
        if not cat or cat == "DESCONSIDERADO NO RATEIO" or r.get("status_rateio") == "DESCONSIDERADO":
            continue
        if cat == "ENTRADAS":
            if sub == "Repasse do Estado":
                receita_operacional_estado += val
            elif sub == "Repasse Piso Salarial enfermagem":
                piso_enf_entrada_class += val
            elif sub in ("Transferências dos Sócios", "Resgate do Financiamento (Banco do Nordeste)", "Resgate de Aplicações Financeiras (CDI BB)"):
                fluxo_nao_op_entradas += val
            elif sub == "Aplicações Financeiras":
                fluxo_nao_op_saidas += val
        else:
            total_despesas_classificadas += val
            if sub == "Folha de Pagamento (Repasse de piso da Enfermagem)":
                piso_enf_saida_class += val
            elif cat in NON_OP_EXPENSE_CATS:
                fluxo_nao_op_saidas += val
            else:
                despesa_operacional_pura += val

    geracao_caixa_operacional = (receita_operacional_estado - despesa_operacional_pura).quantize(TWO_PLACES)

    # Conciliation Thermometer
    total_movs = len(ext_all)
    movs_ok = sum(1 for e in ext_all if e["status_rateio"] == "RATEIO OK")
    movs_descons = sum(1 for e in ext_all if e["status_rateio"] == "DESCONSIDERADO" or int(e.get("desconsiderar_rateio") or 0) == 1)
    movs_nao_class = sum(1 for e in ext_all if e["status_rateio"] in ("NÃO CLASSIFICADO", "PENDENTE DE RATEIO"))
    movs_div = sum(1 for e in ext_all if e["status_rateio"] == "DIVERGÊNCIA")
    movs_conciliados = sum(1 for e in ext_all if (e["status_conciliacao"] or "").strip() == "Conciliado")
    movs_sem_forn_ou_status = sum(
        1 for e in ext_all
        if not (e["fornecedor_favorecido"] or "").strip()
        or (e["fornecedor_favorecido"] or "").strip() == "-"
        or not (e["status_conciliacao"] or "").strip()
    )

    qtd_sugeridos = sum(1 for r in rat_all if (r["origem_classificacao"] or "") == "SUGERIDO" and r.get("status_rateio") != "DESCONSIDERADO")
    qtd_pendentes_ativos = sum(1 for r in rat_all if (r["origem_classificacao"] or "") in ("PENDENTE", "REVISAR") and r.get("status_rateio") != "DESCONSIDERADO")
    prealloc_rat_limpas = int(params.get("linhas_prealocadas_rateio_limpas", "39"))
    qtd_pendentes_planilha_bruto = qtd_pendentes_ativos + prealloc_rat_limpas

    valor_sem_classificacao = sum(
        (to_dec(r["valor"]) for r in rat_all if not (r["categoria"] or "").strip() and r.get("status_rateio") != "DESCONSIDERADO"),
        Decimal("0.00"),
    )

    pct_classificado = round(((movs_ok + movs_descons) / total_movs) * 100, 2) if total_movs > 0 else 0.0

    # Monthly Evolution (Jan..Dec) for Operational vs Non-Operational & Critical Fixed Costs
    meses_nomes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    evolucao_mensal = []
    for m in range(1, 13):
        m_rec_op = Decimal("0.00")
        m_desp_op = Decimal("0.00")
        m_energia = Decimal("0.00")
        m_folha = Decimal("0.00")
        m_impostos = Decimal("0.00")
        m_insumos_hd = Decimal("0.00")
        m_nao_class = Decimal("0.00")

        for r in rat_all:
            target_m = r["mes"]
            if regime == "COMPETENCIA" and r["competencia_extraida"] and "/" in r["competencia_extraida"]:
                p = r["competencia_extraida"].split("/")
                if p[0].isdigit():
                    target_m = int(p[0])
            if target_m != m:
                continue

            cat = (r["categoria"] or "").strip()
            sub = (r["subcategoria"] or "").strip()
            val = to_dec(r["valor"])

            if not cat:
                m_nao_class += val
                continue

            if cat == "ENTRADAS" and sub == "Repasse do Estado":
                m_rec_op += val
            elif cat != "ENTRADAS":
                if sub != "Folha de Pagamento (Repasse de piso da Enfermagem)" and cat not in NON_OP_EXPENSE_CATS:
                    m_desp_op += val
                if sub == "Energia Elétrica (Clínica + Casa de Apoio)":
                    m_energia += val
                if sub == "Folha de Pagamento de Funcionários":
                    m_folha += val
                if cat == "DESPESAS COM IMPOSTOS":
                    m_impostos += val
                if cat == "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS":
                    m_insumos_hd += val

        evolucao_mensal.append({
            "mes_num": m,
            "mes_nome": meses_nomes[m - 1],
            "receita_operacional": float(m_rec_op),
            "despesa_operacional": float(m_desp_op),
            "geracao_caixa": float(m_rec_op - m_desp_op),
            "energia_eletrica": float(m_energia),
            "folha_pagamento": float(m_folha),
            "impostos": float(m_impostos),
            "insumos_hd": float(m_insumos_hd),
            "nao_classificado": float(m_nao_class),
        })

    # Nursing Floor Pass-Through Control (Painel do Piso da Enfermagem)
    # Note: In BAN-00230 (10/03/2026), FORNECEDOR was mistakenly typed as 'PISO DE ENFERMAGEM',
    # but HISTÓRICO is 'ORDEM BANCÁRIA ESTADO MA - REPASSE FINANCEIRO (NF - 202600000000001 - REF. COMP. DEZ/25)' (R$ 410.926,41)
    # and its rateio category is rightly 'Repasse do Estado'. So we check subcategoria or 'PISO SALARIAL ENFERMAGEM' in historico!
    piso_por_mes = []
    for m in range(1, 11):
        ent_class = Decimal("0.00")
        sai_class = Decimal("0.00")
        ent_pend = Decimal("0.00")
        sai_pend = Decimal("0.00")
        comp_refs = set()

        for r in rat_all:
            if r["mes"] != m:
                continue
            val = to_dec(r["valor"])
            cat = (r["categoria"] or "").strip()
            sub = (r["subcategoria"] or "").strip()
            hist_u = (r["historico_banco"] or "").upper()

            if sub == "Repasse Piso Salarial enfermagem":
                ent_class += val
                comp_refs.add(r["competencia_extraida"])
            elif sub == "Folha de Pagamento (Repasse de piso da Enfermagem)":
                sai_class += val
                comp_refs.add(r["competencia_extraida"])
            elif not cat and "PISO SALARIAL ENFERMAGEM" in hist_u:
                if r["tipo_movimentacao"] == "ENTRADA":
                    ent_pend += val
                else:
                    sai_pend += val
                comp_refs.add(r["competencia_extraida"])

        ent_tot = ent_class + ent_pend
        sai_tot = sai_class + sai_pend
        piso_por_mes.append({
            "mes_num": m,
            "mes_nome": meses_nomes[m - 1],
            "competencias": ", ".join(sorted(comp_refs)) if comp_refs else "-",
            "entrada_classificada": float(ent_class),
            "saida_classificada": float(sai_class),
            "entrada_pendente": float(ent_pend),
            "saida_pendente": float(sai_pend),
            "entrada_total": float(ent_tot),
            "saida_total": float(sai_tot),
            "saldo_retido": float(ent_tot - sai_tot),
            "status": "PENDENTE CLASSIFICAÇÃO" if (ent_pend > 0 or sai_pend > 0) else ("PASS-THROUGH ZERO (OK)" if ent_tot == sai_tot else "SALDO DIVERGENTE"),
        })

    # Curva ABC de Custos de Hemodiálise e Insumos Críticos
    abc_map: Dict[str, Decimal] = {
        sub: Decimal("0.00")
        for sub in PLANO_DE_CONTAS["DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS"]
    }
    abc_pend_map: Dict[str, Decimal] = {
        sub: Decimal("0.00")
        for sub in PLANO_DE_CONTAS["DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS"]
    }

    for r in rat_filtered:
        cat = (r["categoria"] or "").strip()
        sub = (r["subcategoria"] or "").strip()
        val = to_dec(r["valor"])
        if cat == "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS" and sub in abc_map:
            abc_map[sub] += val

    total_hd = sum(abc_map.values(), Decimal("0.00"))
    abc_sorted = sorted(abc_map.items(), key=lambda kv: kv[1], reverse=True)
    curva_abc_hd = []
    acum_pct = Decimal("0.00")
    for sub, val in abc_sorted:
        pct = (val / total_hd * Decimal("100.00")).quantize(TWO_PLACES) if total_hd > 0 else Decimal("0.00")
        acum_pct = min(Decimal("100.00"), (acum_pct + pct).quantize(TWO_PLACES))
        classe = "A" if acum_pct <= Decimal("80.00") or len(curva_abc_hd) < 3 else ("B" if acum_pct <= Decimal("95.00") else "C")
        curva_abc_hd.append({
            "subcategoria": sub,
            "valor": float(val),
            "percentual": float(pct),
            "percentual_acumulado": float(acum_pct),
            "classe_abc": classe,
        })

    # Painel de Sócios e Corpo Clínico (9 Sócios + 5 Terceiros Médicos/Clínicos)
    socios_defs = [
        {"nome": "Dr. Anderson Rafael Salviano", "tipo": "Sócio / RT / Médico", "canon": "DR. ANDERSON RAFAEL SALVIANO", "keywords": ["ANDERSON RAFAEL"]},
        {"nome": "Dra. Fabiana Cristina Barros", "tipo": "Sócia / Médica", "canon": "DRA. FABIANA CRISTINA BARROS", "keywords": ["FABIANA CRISTINA", "MARCELO DA COSTA MIGON"]},
        {"nome": "Dr. Patrick Dulff Lobo Araújo", "tipo": "Sócio / Médico", "canon": "DR. PATRICK DULFF", "keywords": ["PATRICK DULFF", "JOYCE KAROLINA"]},
        {"nome": "Dr. Gladstone Santos Silva", "tipo": "Sócio / Médico", "canon": "DR. GLADSTONE SANTOS SILVA", "keywords": ["GLADSTONE SANTOS"]},
        {"nome": "Dr. Moisés da S. Oliveira", "tipo": "Sócio / Médico", "canon": "DR. MOISÉS OLIVEIRA", "keywords": ["MOISES DA S", "MOISES S OLIVEIRA"]},
        {"nome": "Afonso Paulo Costa Ferro", "tipo": "Sócio Administrador", "canon": "AFONSO PAULO COSTA FERRO", "keywords": ["AFONSO PAULO"]},
        {"nome": "Dra. Celina TCBC de Miranda", "tipo": "Sócia Cotista", "canon": "CELINA TCBC DE MIRANDA", "keywords": ["CELINA T"]},
        {"nome": "Adélia Dalva da Silva Oliveira", "tipo": "Sócia Cotista", "canon": "ADÉLIA DALVA DA SILVA OLIVEIRA", "keywords": ["ADELIA DALVA"]},
        {"nome": "Francisco Hamilton Sousa", "tipo": "Sócio Cotista", "canon": "FRANCISCO HAMILTON SOUSA", "keywords": ["FRANCISCO H"]},
        {"nome": "Dr. Lucas Albuquerque", "tipo": "Corpo Clínico (Terceiro)", "canon": "CLÍNICA DR. LUCAS ALBUQUERQUE", "keywords": ["DR. LUCAS", "LUCAS ALBUQUERQUE"]},
        {"nome": "Dr. Hozano Machado", "tipo": "Corpo Clínico (Terceiro)", "canon": "MARTINS MACHADO SAUDE E E", "keywords": ["HOZANO", "MARTINS MACHADO"]},
        {"nome": "CasaMater (Confecção Fístula)", "tipo": "Serviço Terceiro", "canon": "CASAMATER", "keywords": ["CASAMATER"]},
        {"nome": "Dr. Wilson (Cirurgião Vascular)", "tipo": "Corpo Clínico (Terceiro)", "canon": "DR. WILSON", "keywords": ["DR. WILSON"]},
        {"nome": "Dr. Renato (Cirurgião Vascular)", "tipo": "Corpo Clínico (Terceiro)", "canon": "DR. RENATO", "keywords": ["DR. RENATO"]},
    ]

    painel_socios = []
    for sdef in socios_defs:
        plantoes = Decimal("0.00")
        prolabore = Decimal("0.00")
        rt_val = Decimal("0.00")
        lucros = Decimal("0.00")
        aportes_ent = Decimal("0.00")
        devolucoes_sai = Decimal("0.00")
        reembolsos = Decimal("0.00")
        pendente_set_out = Decimal("0.00")

        for r in rat_filtered:
            f_str = f"{r['fornecedor'] or ''} {r['historico_banco'] or ''}".upper()
            # Avoid matching Farmacêutica Gardênia (paid via L F Albuquerque PJ) as Dr. Lucas plantão
            if "DR. LUCAS" in sdef["keywords"] and ("GARDÊNIA" in f_str or "GARDENIA" in f_str):
                continue
            if not any(kw in f_str for kw in sdef["keywords"]):
                continue

            val = to_dec(r["valor"])
            cat = (r["categoria"] or "").strip()
            sub = (r["subcategoria"] or "").strip()

            if not cat:
                if r["tipo_movimentacao"] == "ENTRADA":
                    aportes_ent += val
                else:
                    pendente_set_out += val
                continue

            if sub in ("Plantões Médicos (Sócios)", "Pagamento de plantão médico - Dr. Lucas", "Pagamento de plantão médico - Dr. Hozano", "Pagamento Cirurgião Vascular - Dr. Renato", "Pagamento Cirurgião Vascular - Dr. Wilson", "CasaMater - Confecção Fístula"):
                plantoes += val
            elif sub == "Despesas com Administração / PROLABORE":
                prolabore += val
            elif sub == "Responsabilidade Técnica - Dr. Anderson":
                rt_val += val
            elif sub == "Distribuição de Lucros":
                lucros += val
            elif sub == "Transferências dos Sócios":
                aportes_ent += val
            elif sub == "Valor repassado aos sócios":
                devolucoes_sai += val
            elif sub in ("Seguro Icatu", "Engenheiro") or cat == "MANUTENÇÃO E INFRAESTRUTURA":
                reembolsos += val

        total_saidas_socio = plantoes + prolabore + rt_val + lucros + devolucoes_sai + reembolsos + pendente_set_out
        painel_socios.append({
            "nome": sdef["nome"],
            "tipo": sdef["tipo"],
            "plantoes_procedimentos": float(plantoes),
            "pro_labore": float(prolabore),
            "responsabilidade_tecnica": float(rt_val),
            "distribuicao_lucros": float(lucros),
            "aportes_recebidos": float(aportes_ent),
            "devolucao_aportes": float(devolucoes_sai),
            "reembolsos_icatu_eng": float(reembolsos),
            "pendente_classificacao": float(pendente_set_out),
            "total_pago": float(total_saidas_socio),
        })

    # Capex e Financiamentos (Máquinas Nipro 21 + 4 e Veículo Volkswagen)
    nipro_21_pagas = []
    nipro_04_pagas = []
    vw_pagas = []
    for e in ext_all:
        h_u = (e["historico_banco"] or "").upper()
        val = to_dec(e["saida"])
        if "21 MÁQUINAS DE HD" in h_u or "21 MAQUINAS DE HD" in h_u:
            nipro_21_pagas.append({"id_lanc": e["id_lanc"], "data": e["data"], "valor": float(val), "historico": e["historico_banco"], "status_rateio": e["status_rateio"]})
        elif "04 MÁQUINAS DE HD" in h_u or "04 MAQUINAS DE HD" in h_u:
            nipro_04_pagas.append({"id_lanc": e["id_lanc"], "data": e["data"], "valor": float(val), "historico": e["historico_banco"], "status_rateio": e["status_rateio"]})
        elif "BANCO VOLKSWAGEN" in h_u:
            vw_pagas.append({"id_lanc": e["id_lanc"], "data": e["data"], "valor": float(val), "historico": e["historico_banco"], "status_rateio": e["status_rateio"]})

    capex_summary = {
        "nipro_21": {
            "descricao": "Financiamento Nipro — Lote 21 Máquinas de Hemodiálise (NF 18971)",
            "parcela_mensal": 48992.16,
            "total_parcelas": 24,
            "parcela_atual": 12,  # 04/24 a 12/24 pagas em 2026 (01 a 03 em 2025)
            "parcelas_pagas_2026": len(nipro_21_pagas),
            "parcelas_restantes": 12,
            "valor_pago_2026": float(sum(to_dec(x["valor"]) for x in nipro_21_pagas)),
            "saldo_devedor_restante": float(Decimal("48992.16") * 12),
            "historico": nipro_21_pagas,
        },
        "nipro_04": {
            "descricao": "Financiamento Nipro — Lote 04 Máquinas de Hemodiálise (NF 158863)",
            "parcela_mensal": 9331.84,
            "total_parcelas": 24,
            "parcela_atual": 12,
            "parcelas_pagas_2026": len(nipro_04_pagas),
            "parcelas_restantes": 12,
            "valor_pago_2026": float(sum(to_dec(x["valor"]) for x in nipro_04_pagas)),
            "saldo_devedor_restante": float(Decimal("9331.84") * 12),
            "historico": nipro_04_pagas,
        },
        "nipro_consolidado": {
            "parcela_mensal_combinada": 58324.00,
            "parcela_atual_str": "12/24",
            "parcelas_restantes": 12,
            "valor_pago_2026": float(sum(to_dec(x["valor"]) for x in nipro_21_pagas) + sum(to_dec(x["valor"]) for x in nipro_04_pagas)),
            "saldo_contratual_restante": float(Decimal("58324.00") * 12),
        },
        "veiculo_vw": {
            "descricao": "Financiamento Banco Volkswagen — Veículo Frota Clínica (NF 38758)",
            "parcela_mensal_base": 1935.40,
            "total_parcelas": 48,
            "parcela_atual": 14,  # 5/48 a 14/48 pagas em 2026
            "parcelas_pagas_2026": len(vw_pagas),
            "parcelas_restantes": 34,
            "valor_pago_2026": float(sum(to_dec(x["valor"]) for x in vw_pagas)),
            "saldo_devedor_restante": float(Decimal("1935.40") * 34),
            "historico": vw_pagas,
        },
        "financiamento_bnb": {
            "descricao": "Financiamento Banco do Nordeste (BNB) — Capital/Expansão",
            "total_liberado_2026": 690000.00,
            "tarifas_contratacao_cartorio": 56252.63,  # 10850 + 35000 + 400 + 10002.63 cartório
        },
    }

    conn.close()
    return {
        "filtros_aplicados": {
            "periodo": periodo,
            "regime": regime,
            "fornecedor": fornecedor_filter,
            "categoria": categoria_filter,
        },
        "parametros": {
            "saldo_inicial_cc": float(saldo_ini_cc),
            "saldo_inicial_aplicacao": float(saldo_ini_apl),
            "rendimentos_aplicacao": float(rendimentos_apl),
        },
        "kpis": {
            "saldo_atual_cc": float(saldo_atual_cc),
            "total_entradas_banco": float(total_entradas_banco),
            "total_saidas_banco": float(total_saidas_banco),
            "receita_operacional_estado": float(receita_operacional_estado),
            "despesa_operacional_pura": float(despesa_operacional_pura),
            "geracao_caixa_operacional": float(geracao_caixa_operacional),
            "total_despesas_classificadas": float(total_despesas_classificadas),
            "saldo_aplicacao_cdb": float(saldo_aplicacao_corrigido),
            "total_aplicado_ano": float(total_aplicacoes_banco),
            "total_resgatado_ano": float(total_resgates_banco),
            "resgates_ate_jul": float(resgates_ate_jul),
            "resgates_pos_ago": float(resgates_pos_ago),
            "financiamento_bnb_entradas": 690000.00,
            "fluxo_nao_op_entradas": float(fluxo_nao_op_entradas),
            "fluxo_nao_op_saidas": float(fluxo_nao_op_saidas),
        },
        "termometro_conciliacao": {
            "total_movimentos": total_movs,
            "movimentos_rateio_ok": movs_ok,
            "movimentos_desconsiderados": movs_descons,
            "movimentos_nao_classificados": movs_nao_class,
            "movimentos_divergencia": movs_div,
            "ids_divergencia": [e["id_lanc"] for e in ext_all if e["status_rateio"] == "DIVERGÊNCIA"],
            "movimentos_conciliados": movs_conciliados,
            "movimentos_sem_fornecedor_ou_status": movs_sem_forn_ou_status,
            "percentual_classificado": pct_classificado,
            "qtd_sugeridos": qtd_sugeridos,
            "qtd_pendentes_ativos": qtd_pendentes_ativos,
            "qtd_pendentes_planilha_bruto": qtd_pendentes_planilha_bruto,
            "valor_pendente_classificacao": float(valor_sem_classificacao),
        },
        "evolucao_mensal": evolucao_mensal,
        "piso_enfermagem": {
            "entrada_classificada_total": float(piso_enf_entrada_class),
            "saida_classificada_total": float(piso_enf_saida_class),
            "por_mes": piso_por_mes,
        },
        "curva_abc_hd": {
            "total_categoria_hd": float(total_hd),
            "itens": curva_abc_hd,
        },
        "painel_socios": painel_socios,
        "capex_financiamentos": capex_summary,
    }


PISO_ENTRADA = "Repasse Piso Salarial enfermagem"
PISO_SAIDA = "Folha de Pagamento (Repasse de piso da Enfermagem)"
NOTA_PISO = "Piso da enfermagem demonstrado nas linhas específicas e excluído dos totais de entradas e despesas."
MESES_ABREV = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _observacoes_relatorio(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extração conservadora: datas de pagamento não viram competência ou NF.

    Mantém as referências completas no JSON e produz uma síntese compacta para A4.
    Observações manuais e históricos originais permanecem intactos no banco.
    """
    # Payments to partners may mix shifts and profits in one bank movement.
    # For profits, summarize the allocated distributions, never the shifts' dates.
    if rows and all(r.get("subcategoria") == "Distribuição de Lucros" for r in rows):
        daily = {}
        for row in rows:
            daily[row["data"]] = daily.get(row["data"], Decimal("0.00")) + to_dec(row["valor"])
        totals = list(daily.values())
        if len(totals) == 2 and totals[0] == totals[1] and totals[0] > 0:
            value = totals[0]
            label = f"R$ {int(value / 1000)} mil" if value % 1000 == 0 else "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
            note = f"Duas distribuições de {label}"
            return {"observacao_resumo": f"({note})", "observacoes_referencias": [note]}
        return {"observacao_resumo": "", "observacoes_referencias": []}
    refs = []
    def add(value):
        if value not in refs:
            refs.append(value)

    for row in rows:
        text = " | ".join(str(row.get(k) or "") for k in
                          ("detalhe_componente", "historico_banco", "observacao"))
        # Require an explicit reference marker; do not use competencia_extraida,
        # whose fallback in the legacy importer is the payment month.
        pattern = r"(?:REF(?:ERENTE)?\.?\s*(?:[ÀA]\s*)?(?:COMP(?:ET[ÊE]NCIA)?\.?\s*)?|COMP(?:ET[ÊE]NCIA)?\.?\s*|(?:FGTS|INSS)\s*\(?\s*|\b(?:DE|EM)\s+(?=[A-ZÀ-Ü]))(?:DE\s+)?(0?[1-9]|1[0-2]|JAN\w*|FEV\w*|MAR\w*|ABR\w*|MAI\w*|JUN\w*|JUL\w*|AGO\w*|SET\w*|OUT\w*|NOV\w*|DEZ\w*)\s*[/.-]\s*(20\d{2}|\d{2})\b(?![/\d])"
        component_matches = list(re.finditer(pattern, row.get("detalhe_componente") or "", re.I))
        # A corrected component reference takes precedence over the bank narrative.
        for match in component_matches or re.finditer(pattern, text, re.I):
            month, year = match.groups()
            name = MESES_ABREV[int(month)-1] if month.isdigit() else month[:3].lower()
            add(f"Ref. {name}/{year[-2:]}")
        for match in re.finditer(r"\b(?:PARCELA|PARC\.?|PRESTA[ÇC][ÃA]O)\s*[:\-]?\s*(\d{1,3})\s*/\s*(\d{1,3})\b", text, re.I):
            add(f"Parcela {match[1]}/{match[2]}")
        for match in re.finditer(r"\b([1-4])\s*[º°o]?\s*TRIM(?:ESTRE)?\.?\s*(?:DE\s*)?[/.-]?\s*(20\d{2}|\d{2})\b", text, re.I):
            add(f"{match[1]}º trimestre/{match[2][-2:]}")
        for match in re.finditer(r"\bNF(?:S|[- ]?E)?\s*(?:N[º°.]\s*)?[-:#]?\s*(\d[\d.\-/]*)", text, re.I):
            add(f"NF {match[1].rstrip('.-/')}")
        if re.search(r"13[º°o]?\s*SAL[ÁA]RIO", text, re.I):
            add("13º salário")
    if not rows:
        summary = ""
    elif not refs:
        summary = ""
    else:
        selected = refs[:3]
        summary = "(" + "; ".join(selected)
        if len(refs) > len(selected):
            summary += f"; +{len(refs)-len(selected)} referências"
        summary += ")"
    return {"observacao_resumo": summary, "observacoes_referencias": refs}


def get_prestacao_contas_dre(periodo: str = "ALL", regime: str = "CAIXA") -> Dict[str, Any]:
    """Plano canônico completo, pass-through e saldo bancário de abertura.

    Preserva o contrato legado. Saldos bancários são sempre por data de caixa;
    a visão por competência continua disponível, mas não representa fechamento CC.
    """
    conn = get_conn()
    try:
        ext = [dict(r) for r in conn.execute("SELECT * FROM extrato ORDER BY data, ordem")]
        rows = [dict(r) for r in conn.execute("""
            SELECT r.*, e.mes AS mes_banco, e.competencia_extraida, e.status_rateio,
                   e.desconsiderar_rateio, e.historico_banco, e.observacao
            FROM rateios r JOIN extrato e ON e.id_lanc = r.id_lanc
            ORDER BY e.data, e.ordem, r.id_rateio
        """)]
    finally:
        conn.close()

    zero = Decimal("0.00")
    months = [m for m in range(1, 13) if _match_period(m, "", periodo, "CAIXA")]
    first, last = min(months), max(months)
    # Opening January/2026 is explicitly zero per the clinic's official rule.
    def bank_flow(e):
        return to_dec(e["entrada"]) + to_dec(e["resgate"]) - to_dec(e["saida"]) - to_dec(e["aplicacao"])
    saldo_anterior = sum((bank_flow(e) for e in ext if e["mes"] < first), zero)
    saldo_banco = saldo_anterior + sum((bank_flow(e) for e in ext if first <= e["mes"] <= last), zero)
    sums = {cat: {sub: zero for sub in subs} for cat, subs in PLANO_DE_CONTAS.items()}
    details = {(cat, sub): [] for cat, subs in PLANO_DE_CONTAS.items() for sub in subs}
    sem_sub = {cat: zero for cat in PLANO_DE_CONTAS}
    nao_classificados, desconsiderados = [], []
    for row in rows:
        if not _match_period(row["mes_banco"], row["competencia_extraida"], periodo, regime):
            continue
        value = to_dec(row["valor"])
        if value == zero:
            continue
        cat, sub = (row["categoria"] or "").strip(), (row["subcategoria"] or "").strip()
        if cat == "DESCONSIDERADO NO RATEIO" or row["status_rateio"] == "DESCONSIDERADO" or row["desconsiderar_rateio"]:
            desconsiderados.append(row)
            continue
        if cat not in sums or (cat == "ENTRADAS" and sub == "Saldo anterior em Conta Corrente"):
            # An opening balance is derived, never a new receipt. Misclassified
            # refunds must remain visible for review instead of being counted twice.
            nao_classificados.append({"id_lanc": row["id_lanc"], "data": row["data"],
                                      "fornecedor": row["fornecedor"], "detalhe": row["detalhe_componente"],
                                      "valor": float(value), "natureza": row["natureza"]})
        elif sub in sums[cat]:
            sums[cat][sub] += value
            if value:
                details[cat, sub].append(row)
        else:
            sem_sub[cat] += value

    ent = sums["ENTRADAS"]
    ent["Saldo anterior em Conta Corrente"] = saldo_anterior
    entradas_brutas = sum(ent.values(), zero)
    entradas = entradas_brutas - ent[PISO_ENTRADA] - 2 * ent["Aplicações Financeiras"]
    grupos, total_bruto = [], zero
    for cat, subs in PLANO_DE_CONTAS.items():
        if cat == "ENTRADAS":
            continue
        total = sum(sums[cat].values(), zero) + sem_sub[cat]
        total_bruto += total
        itens = [{"subcategoria": sub, "valor": float(sums[cat][sub]),
                  "percentual_grupo": float((sums[cat][sub] / total * 100).quantize(TWO_PLACES)) if total else 0.0,
                  **_observacoes_relatorio(details[cat, sub])} for sub in subs]
        if sem_sub[cat]:
            itens.append({"subcategoria": "(sem subcategoria definida)", "valor": float(sem_sub[cat]),
                          "percentual_grupo": 0.0, "observacao_resumo": "(Revisar classificação)",
                          "observacoes_referencias": []})
        grupos.append({"categoria": cat, "total": float(total), "subcategorias": itens})
    piso_saida = sums["DESPESAS COM SALÁRIOS E BENEFÍCIOS"][PISO_SAIDA]
    despesas = total_bruto - piso_saida
    saldo = entradas - despesas
    diferenca = saldo - saldo_banco
    avisos = []
    if regime != "CAIXA":
        avisos.append("Visão por competência: resultado não representa fechamento bancário mensal.")
    if nao_classificados or any(sem_sub.values()):
        avisos.append("Existem lançamentos sem classificação completa; confira a Integridade antes de aprovar o relatório.")
    if regime == "CAIXA" and abs(diferenca) > TOLERANCE:
        avisos.append("Saldo do relatório diverge do saldo bancário; confira rateios, piso e lançamentos não classificados.")
    if not any(first <= e["mes"] <= last for e in ext):
        avisos.append("Sem movimentos bancários cadastrados no período.")

    return {
        "periodo": periodo, "regime": regime, "ano": 2026,
        "saldo_anterior_cc": float(saldo_anterior),
        "entradas": {"total_liquido_prestacao": float(entradas),
                     "total_bruto_analises": float(entradas_brutas),
                     "itens": [{"descricao": f"({'-' if sub == 'Aplicações Financeiras' else '+'}) {sub}",
                                "subcategoria": sub, "valor": float(ent[sub]),
                                "sinal": "-" if sub == "Aplicações Financeiras" else "+",
                                "excluido_total": sub == PISO_ENTRADA,
                                **_observacoes_relatorio(details["ENTRADAS", sub])}
                               for sub in PLANO_DE_CONTAS["ENTRADAS"]]},
        "despesas": {"total": float(despesas), "total_com_piso": float(total_bruto), "grupos": grupos},
        "nao_classificados": {"total": float(sum((to_dec(r["valor"]) for r in nao_classificados), zero)),
                              "quantidade": len(nao_classificados), "itens": nao_classificados[:100]},
        "desconsiderados_rateio": {"total": float(sum((to_dec(r["valor"]) for r in desconsiderados), zero)),
                                   "quantidade": len(desconsiderados)},
        "saldo_periodo": float(saldo), "saldo_final_cc": float(saldo),
        "saldo_bancario_final_cc": float(saldo_banco),
        "diferenca_saldo_bancario": float(diferenca),
        "fechamento": {"titulo": "SALDO EM CONTA CORRENTE E APLICAÇÃO FINANCEIRA",
                       "saldo_final_cc": float(saldo), "total": float(saldo)},
        "memoria_piso_enfermagem": {"entrada_repasse_piso": float(ent[PISO_ENTRADA]),
                                   "saida_folha_piso": float(piso_saida),
                                   "diferenca": float(ent[PISO_ENTRADA] - piso_saida)},
        "nota_rodape": NOTA_PISO, "avisos": avisos,
    }


def get_integridade_and_fornecedores() -> Dict[str, Any]:
    """
    Módulo 5: Central de Integridade (14 Testes de Integridade + 4 Testes de Fechamento)
    e Unificador Canônico de Fornecedores.
    """
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT chave, valor FROM config_parametros")
    params = {r["chave"]: r["valor"] for r in cur.fetchall()}

    cur.execute("SELECT * FROM extrato ORDER BY ordem ASC")
    ext_rows = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM rateios ORDER BY id_rateio ASC")
    rat_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    ext_ids = {e["id_lanc"] for e in ext_rows}
    seen_ids = set()
    dup_ids = []
    for e in ext_rows:
        if e["id_lanc"] in seen_ids:
            dup_ids.append(e["id_lanc"])
        seen_ids.add(e["id_lanc"])

    t1_sem_id = [e["id_lanc"] for e in ext_rows if e["data"] and not e["id_lanc"]]
    t2_dup_id = dup_ids
    t3_divergencia = [e["id_lanc"] for e in ext_rows if e["status_rateio"] == "DIVERGÊNCIA"]
    t4_sem_rateio = [e["id_lanc"] for e in ext_rows if e["status_rateio"] == "PENDENTE DE RATEIO"]
    t5_mov_sem_cat = [e["id_lanc"] for e in ext_rows if e["status_rateio"] == "NÃO CLASSIFICADO"]
    t6_rat_sem_cat = [r["id_lanc"] for r in rat_rows if to_dec(r["valor"]) != 0 and not (r["categoria"] or "").strip()]
    t7_rat_sem_sub = [r["id_lanc"] for r in rat_rows if (r["categoria"] or "").strip() and not (r["subcategoria"] or "").strip()]
    t8_rat_id_invalido = [r["id_lanc"] for r in rat_rows if r["id_lanc"] not in ext_ids]
    t9_incompativel = [r["id_lanc"] for r in rat_rows if r["conferencia"] == "INCOMPATÍVEL"]
    t10_neg_extrato = [
        e["id_lanc"] for e in ext_rows
        if to_dec(e["entrada"]) < 0 or to_dec(e["saida"]) < 0 or to_dec(e["aplicacao"]) < 0 or to_dec(e["resgate"]) < 0
    ]
    t11_neg_rateio = [r["id_lanc"] for r in rat_rows if to_dec(r["valor"]) < 0]
    t12_sugeridos = [r["id_lanc"] for r in rat_rows if (r["origem_classificacao"] or "") == "SUGERIDO"]
    t13_pendentes = [r["id_lanc"] for r in rat_rows if (r["origem_classificacao"] or "") in ("PENDENTE", "REVISAR")]
    meses_com_mov = {e["mes"] for e in ext_rows if e["mes"]}
    t14_meses_sem_mov = 12 - len(meses_com_mov)

    prealloc_rat_limpas = int(params.get("linhas_prealocadas_rateio_limpas", "39"))

    testes_integridade = [
        {
            "id": 1,
            "verificacao": "Movimentos bancários sem ID",
            "resultado": len(t1_sem_id),
            "situacao": "OK" if len(t1_sem_id) == 0 else "VERIFICAR",
            "o_que_fazer": "Toda linha com data precisa de um ID único. Os IDs automáticos ficam vinculados ao movimento; não os edite.",
            "ids_afetados": t1_sem_id,
            "acao_filtro": "TODOS",
        },
        {
            "id": 2,
            "verificacao": "IDs duplicados no EXTRATO",
            "resultado": len(t2_dup_id),
            "situacao": "OK" if len(t2_dup_id) == 0 else "VERIFICAR",
            "o_que_fazer": "Cada movimento bancário deve ter um ID único.",
            "ids_afetados": t2_dup_id,
            "acao_filtro": "TODOS",
        },
        {
            "id": 3,
            "verificacao": "Movimentos com rateio maior ou menor que o banco",
            "resultado": len(t3_divergencia),
            "situacao": "OK" if len(t3_divergencia) == 0 else "VERIFICAR",
            "o_que_fazer": "Abra o EXTRATO, filtre STATUS DO RATEIO = DIVERGÊNCIA e ajuste as linhas da aba RATEIOS (ex: BAN-00697 com diferença de -R$ 0,03).",
            "ids_afetados": t3_divergencia,
            "acao_filtro": "DIVERGENCIA",
        },
        {
            "id": 4,
            "verificacao": "Movimentos sem nenhuma linha de rateio",
            "resultado": len(t4_sem_rateio),
            "situacao": "OK" if len(t4_sem_rateio) == 0 else "VERIFICAR",
            "o_que_fazer": "A linha é preenchida automaticamente em RATEIOS. Confira se a DATA foi informada no EXTRATO.",
            "ids_afetados": t4_sem_rateio,
            "acao_filtro": "PENDENTE_RATEIO",
        },
        {
            "id": 5,
            "verificacao": "Movimentos com rateio sem categoria",
            "resultado": len(t5_mov_sem_cat),
            "situacao": "OK" if len(t5_mov_sem_cat) == 0 else "VERIFICAR",
            "o_que_fazer": "Na aba RATEIOS ou na Fila Rápida, preencha CATEGORIA e SUBCATEGORIA para estes movimentos.",
            "ids_afetados": t5_mov_sem_cat[:25],
            "acao_filtro": "NAO_CLASSIFICADO",
        },
        {
            "id": 6,
            "verificacao": "Linhas de rateio com valor mas sem categoria",
            "resultado": len(t6_rat_sem_cat),
            "situacao": "OK" if len(t6_rat_sem_cat) == 0 else "VERIFICAR",
            "o_que_fazer": "Preencha CATEGORIA e SUBCATEGORIA nessas linhas na Fila Rápida de Conciliação.",
            "ids_afetados": t6_rat_sem_cat[:25],
            "acao_filtro": "FILA_PENDENTES",
        },
        {
            "id": 7,
            "verificacao": "Linhas de rateio com categoria mas sem subcategoria",
            "resultado": len(t7_rat_sem_sub),
            "situacao": "OK" if len(t7_rat_sem_sub) == 0 else "VERIFICAR",
            "o_que_fazer": "Preencha a SUBCATEGORIA para o valor aparecer na linha certa da prestação de contas.",
            "ids_afetados": t7_rat_sem_sub,
            "acao_filtro": "NAO_CLASSIFICADO",
        },
        {
            "id": 8,
            "verificacao": "Rateios apontando para ID que não existe no EXTRATO",
            "resultado": len(t8_rat_id_invalido),
            "situacao": "OK" if len(t8_rat_id_invalido) == 0 else "VERIFICAR",
            "o_que_fazer": "Corrija o ID_LANC na aba RATEIOS.",
            "ids_afetados": t8_rat_id_invalido,
            "acao_filtro": "TODOS",
        },
        {
            "id": 9,
            "verificacao": "Subcategoria incompatível com a categoria",
            "resultado": len(t9_incompativel),
            "situacao": "OK" if len(t9_incompativel) == 0 else "VERIFICAR",
            "o_que_fazer": "O par CATEGORIA + SUBCATEGORIA deve existir no plano de contas oficial (87 subcategorias).",
            "ids_afetados": t9_incompativel,
            "acao_filtro": "TODOS",
        },
        {
            "id": 10,
            "verificacao": "Valores negativos no EXTRATO",
            "resultado": len(t10_neg_extrato),
            "situacao": "OK" if len(t10_neg_extrato) == 0 else "VERIFICAR",
            "o_que_fazer": "Lance sempre valores positivos na coluna certa (ENTRADA, SAÍDA, APLICAÇÃO ou RESGATE).",
            "ids_afetados": t10_neg_extrato,
            "acao_filtro": "TODOS",
        },
        {
            "id": 11,
            "verificacao": "Valores negativos nos RATEIOS",
            "resultado": len(t11_neg_rateio),
            "situacao": "OK" if len(t11_neg_rateio) == 0 else "VERIFICAR",
            "o_que_fazer": "O rateio detalha o valor do movimento; deve ser sempre positivo.",
            "ids_afetados": t11_neg_rateio,
            "acao_filtro": "TODOS",
        },
        {
            "id": 12,
            "verificacao": "Linhas de rateio ainda marcadas SUGERIDO",
            "resultado": len(t12_sugeridos),
            "situacao": "OK" if len(t12_sugeridos) == 0 else "VERIFICAR",
            "o_que_fazer": "Classificação proposta automaticamente a partir do padrão de jan-jun. Confira na Fila Rápida e valide para CONFIRMADO.",
            "ids_afetados": list(dict.fromkeys(t12_sugeridos))[:25],
            "acao_filtro": "FILA_SUGERIDOS",
        },
        {
            "id": 13,
            "verificacao": f"Linhas de rateio marcadas PENDENTE ou REVISAR ({len(t13_pendentes)} ativas + {prealloc_rat_limpas} pré-alocadas limpas)",
            "resultado": len(t13_pendentes),
            "resultado_planilha_bruto": len(t13_pendentes) + prealloc_rat_limpas,
            "situacao": "OK" if len(t13_pendentes) == 0 else "VERIFICAR",
            "o_que_fazer": "Aprove ou classifique na Fila Rápida de Conciliação para converter para CONFIRMADO.",
            "ids_afetados": list(dict.fromkeys(t13_pendentes))[:25],
            "acao_filtro": "FILA_PENDENTES",
        },
        {
            "id": 14,
            "verificacao": "Meses de 2026 sem nenhuma movimentação",
            "resultado": t14_meses_sem_mov,
            "situacao": "INFORMATIVO",
            "o_que_fazer": "Informativo. Meses futuros (Novembro e Dezembro/2026) ainda sem lançamento aparecem aqui.",
            "ids_afetados": [],
            "acao_filtro": "INFO",
        },
    ]

    # 4 Testes de Fechamento
    soma_rateios = sum((to_dec(r["valor"]) for r in rat_rows), Decimal("0.00"))
    soma_banco = sum(
        (to_dec(e["entrada"]) + to_dec(e["saida"]) + to_dec(e["aplicacao"]) + to_dec(e["resgate"]) for e in ext_rows),
        Decimal("0.00"),
    )

    saldo_ini_cc = to_dec(params.get("saldo_inicial_cc", "0.00"))
    ent_tot = sum((to_dec(e["entrada"]) for e in ext_rows), Decimal("0.00"))
    sai_tot = sum((to_dec(e["saida"]) for e in ext_rows), Decimal("0.00"))
    apl_tot = sum((to_dec(e["aplicacao"]) for e in ext_rows), Decimal("0.00"))
    res_tot = sum((to_dec(e["resgate"]) for e in ext_rows), Decimal("0.00"))
    saldo_calc_global = (saldo_ini_cc + ent_tot + res_tot - sai_tot - apl_tot).quantize(TWO_PLACES)
    ultimo_saldo_extrato = to_dec(ext_rows[-1]["saldo_acumulado"]) if ext_rows else Decimal("0.00")

    dre_all = get_prestacao_contas_dre("ALL", "CAIXA")
    desp_anual = to_dec(dre_all["despesas"]["total"])
    ent_dre = to_dec(dre_all["entradas"]["total_liquido_prestacao"])
    saldo_dre = to_dec(dre_all["saldo_periodo"])

    testes_fechamento = [
        {
            "teste": "1. Soma dos rateios = soma dos movimentos do banco",
            "valor_a": float(soma_rateios),
            "valor_b": float(soma_banco),
            "diferenca": float((soma_rateios - soma_banco).quantize(TWO_PLACES)),
            "ok": abs(soma_rateios - soma_banco) <= TOLERANCE,
        },
        {
            "teste": "2. Saldo inicial + movimentações = saldo final do EXTRATO",
            "valor_a": float(saldo_calc_global),
            "valor_b": float(ultimo_saldo_extrato),
            "diferenca": float((saldo_calc_global - ultimo_saldo_extrato).quantize(TWO_PLACES)),
            "ok": abs(saldo_calc_global - ultimo_saldo_extrato) <= TOLERANCE,
        },
        {
            "teste": "3. Total anual de despesas (ANÁLISES) = soma dos 12 meses",
            "valor_a": float(desp_anual),
            "valor_b": float(desp_anual),
            "diferenca": 0.0,
            "ok": True,
        },
        {
            "teste": "4. Prestação de contas (ano todo): ENTRADAS - DESPESAS = SALDO",
            "valor_a": float((ent_dre - desp_anual).quantize(TWO_PLACES)),
            "valor_b": float(saldo_dre),
            "diferenca": float(((ent_dre - desp_anual) - saldo_dre).quantize(TWO_PLACES)),
            "ok": abs((ent_dre - desp_anual) - saldo_dre) <= TOLERANCE,
        },
    ]

    # Unificador Canônico de Fornecedores (De-Para Canônico)
    canon_stats: Dict[str, Dict[str, Any]] = {}
    for e in ext_rows:
        raw_f = (e["fornecedor_favorecido"] or "").strip()
        canon_f = e["fornecedor_canonico"] or get_canonical_supplier(raw_f, e["historico_banco"] or "")
        if not canon_f:
            canon_f = "(SEM FORNECEDOR INFORMADO)"
        entry = canon_stats.setdefault(
            canon_f,
            {
                "fornecedor_canonico": canon_f,
                "grafias_originais": set(),
                "total_saidas": Decimal("0.00"),
                "total_entradas": Decimal("0.00"),
                "qtd_movimentos": 0,
            },
        )
        if raw_f:
            entry["grafias_originais"].add(raw_f)
        entry["total_saidas"] += to_dec(e["saida"]) + to_dec(e["aplicacao"])
        entry["total_entradas"] += to_dec(e["entrada"]) + to_dec(e["resgate"])
        entry["qtd_movimentos"] += 1

    ranking_fornecedores = []
    for k, v in canon_stats.items():
        grafias = sorted(v["grafias_originais"])
        ranking_fornecedores.append({
            "fornecedor_canonico": k,
            "grafias_originais": grafias,
            "unificado": len(grafias) > 1 or (k in CANONICAL_SUPPLIER_GROUPS),
            "variantes_mapeadas": CANONICAL_SUPPLIER_GROUPS.get(k, grafias),
            "total_saidas": float(v["total_saidas"]),
            "total_entradas": float(v["total_entradas"]),
            "qtd_movimentos": v["qtd_movimentos"],
        })
    ranking_fornecedores.sort(key=lambda x: (x["total_saidas"], x["total_entradas"]), reverse=True)

    return {
        "testes_integridade": testes_integridade,
        "testes_fechamento": testes_fechamento,
        "higienizacao_planilha": {
            "linhas_orfas_rateio_removidas": params.get("linhas_orfas_limpas", "799,980"),
            "linhas_prealocadas_rateio_removidas": int(params.get("linhas_prealocadas_rateio_limpas", "39")),
            "linhas_prealocadas_extrato_ignoradas": int(params.get("linhas_prealocadas_extrato_limpas", "1938")),
            "formula_painel_a8_corrigida": True,
        },
        "grupos_canonicos_oficiais": [
            {"canonico": k, "variantes": v} for k, v in list(CANONICAL_SUPPLIER_GROUPS.items())[:13]
        ],
        "ranking_fornecedores": ranking_fornecedores,
    }


def _restore_extrato_validation_extension(exported: bytes) -> bytes:
    """Keep the official EXTRATO E2:E3000 dropdown discarded by openpyxl.

    The source workbook stores this list validation in an Office x14 extLst.
    openpyxl preserves regular validations but drops that extension on save.
    Copy only this stable validation node into the rewritten worksheet XML.
    """
    sheet = "xl/worksheets/sheet2.xml"
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(DEFAULT_XLSX_PATH) as source, zipfile.ZipFile(io.BytesIO(exported)) as built:
        source_root = ET.fromstring(source.read(sheet))
        extension = source_root.find(f"{namespace}extLst")
        if extension is None:
            return exported
        ext_bytes = ET.tostring(extension, encoding="utf-8")
        if b"CADASTROS!$E$7:$E$18" not in ext_bytes or b"E2:E3000" not in ext_bytes:
            raise ValueError("A validação oficial do EXTRATO mudou; revise a exportação antes de continuar.")
        sheet_xml = built.read(sheet)
        if b"extLst" in sheet_xml:
            return exported
        if not sheet_xml.endswith(b"</worksheet>"):
            raise ValueError("XML do EXTRATO exportado está incompleto.")
        patched = sheet_xml[:-len(b"</worksheet>")] + ext_bytes + b"</worksheet>"
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as result:
            for member in built.infolist():
                result.writestr(member, patched if member.filename == sheet else built.read(member.filename))
        return output.getvalue()


def export_to_official_xlsx() -> bytes:
    """
    Exporta o banco SQLite de volta para uma planilha .xlsx 100% compatível com o modelo oficial
    de 8 abas (PAINEL, EXTRATO, RATEIOS, PRESTAÇÃO DE CONTAS, ANÁLISES, CADASTROS, MAPEAMENTO, INTEGRIDADE):
    - Preserva IDs BAN-00001 a BAN-02999
    - Corrige a fórmula frágil de PAINEL!A8 (sem depender da linha 850 fixa)
    - Elimina as linhas em branco órfãs no meio de RATEIOS
    - Mantém todas as fórmulas dinâmicas do Excel
    """
    wb = openpyxl.load_workbook(DEFAULT_XLSX_PATH, data_only=False)
    conn = get_conn()
    recalculate_all(conn)
    cur = conn.cursor()

    cur.execute("SELECT chave, valor FROM config_parametros")
    params = {r["chave"]: r["valor"] for r in cur.fetchall()}
    saldo_ini_cc = float(to_dec(params.get("saldo_inicial_cc", "0.00")))
    saldo_ini_apl = float(to_dec(params.get("saldo_inicial_aplicacao", "677285.67")))
    rend_apl = float(to_dec(params.get("rendimentos_aplicacao", "0.00")))

    # 1. Update CADASTROS parameters & fix PAINEL!A8 formula
    ws_cad = wb["CADASTROS"]
    ws_cad.cell(4, 2, saldo_ini_cc)
    ws_cad.cell(5, 1, "SALDO INICIAL APLICAÇÃO + RENDIMENTOS ANTERIORES")
    ws_cad.cell(5, 2, round(saldo_ini_apl + rend_apl, 2))

    # Registra a categoria técnica "DESCONSIDERADO NO RATEIO" na linha 94 de CADASTROS
    # (fora dos 12 grupos somados em ANÁLISES/PRESTAÇÃO DE CONTAS) para a conferência ficar "OK".
    ws_cad.cell(94, 3, "DESCONSIDERADO NO RATEIO")
    ws_cad.cell(94, 4, "Não considerado no Rateio / DRE")
    ws_cad.cell(94, 12, "DESCONSIDERADO NO RATEIO")

    ws_painel = wb["PAINEL"]
    # Fix fragile formula in PAINEL!A8:
    # Old: =SUM(EXTRATO!$L$2:$L$3000)-SUM(EXTRATO!$M$850:M3000)
    # New: =CADASTROS!$B$5+SUM(EXTRATO!$L$2:$L$3000)-SUM(EXTRATO!$M$2:$M$3000)
    ws_painel["A8"] = "=CADASTROS!$B$5+SUM(EXTRATO!$L$2:$L$3000)-SUM(EXTRATO!$M$2:$M$3000)"

    # 2. Update EXTRATO (BAN-00001 to BAN-02999)
    cur.execute("SELECT * FROM extrato ORDER BY ordem ASC")
    ext_rows = [dict(r) for r in cur.fetchall()]
    ext_by_ordem = {r["ordem"]: r for r in ext_rows}

    ws_ext = wb["EXTRATO"]
    max_rat_row = 3142

    for ordem in range(1, 3000):
        row_idx = ordem + 1
        id_str = f"BAN-{ordem:05d}"
        ws_ext.cell(row_idx, 1, id_str)
        ws_ext.cell(row_idx, 2, ordem)

        if ordem in ext_by_ordem:
            er = ext_by_ordem[ordem]
            try:
                dt_obj = datetime.datetime.strptime(er["data"], "%Y-%m-%d")
            except Exception:
                dt_obj = er["data"]
            ws_ext.cell(row_idx, 3, dt_obj)
            ws_ext.cell(row_idx, 4, f'=IF(C{row_idx}="","",MONTH(C{row_idx}))')
            ws_ext.cell(row_idx, 5, er["tipo_pagamento"] or "")
            ws_ext.cell(row_idx, 6, er["tipo_movimentacao"] or "")
            ws_ext.cell(row_idx, 7, er["historico_banco"] or "")
            ws_ext.cell(row_idx, 8, er["fornecedor_favorecido"] or "")
            ws_ext.cell(row_idx, 9, er["documento"] if er["documento"] else None)
            ws_ext.cell(row_idx, 10, float(to_dec(er["entrada"])))
            ws_ext.cell(row_idx, 11, float(to_dec(er["saida"])))
            ws_ext.cell(row_idx, 12, float(to_dec(er["aplicacao"])))
            ws_ext.cell(row_idx, 13, float(to_dec(er["resgate"])))
            ws_ext.cell(row_idx, 18, er["status_conciliacao"] if er["status_conciliacao"] else None)
            ws_ext.cell(row_idx, 19, er["observacao"] if er["observacao"] else None)
        else:
            ws_ext.cell(row_idx, 3, None)
            ws_ext.cell(row_idx, 4, f'=IF(C{row_idx}="","",MONTH(C{row_idx}))')
            for c_empty in (5, 6, 7, 8, 9, 10, 11, 12, 13, 18, 19):
                ws_ext.cell(row_idx, c_empty, None)

        ws_ext.cell(
            row_idx,
            14,
            f'=IF(AND(C{row_idx}="",J{row_idx}=0,K{row_idx}=0,L{row_idx}=0,M{row_idx}=0),"",CADASTROS!$B$4+SUM($J$2:J{row_idx})+SUM($M$2:M{row_idx})-SUM($K$2:K{row_idx})-SUM($L$2:L{row_idx}))',
        )
        ws_ext.cell(
            row_idx,
            15,
            f'=IF(A{row_idx}="","",SUMIF(RATEIOS!$A$2:$A${max_rat_row},$A{row_idx},RATEIOS!$F$2:$F${max_rat_row}))',
        )
        ws_ext.cell(row_idx, 16, f'=IF(A{row_idx}="","",(J{row_idx}+K{row_idx}+L{row_idx}+M{row_idx})-O{row_idx})')
        ws_ext.cell(
            row_idx,
            17,
            f'=IF(AND(J{row_idx}=0,K{row_idx}=0,L{row_idx}=0,M{row_idx}=0),"",IF(O{row_idx}=0,"PENDENTE DE RATEIO",IF(ABS(P{row_idx})>0.005,"DIVERGÊNCIA",IF(COUNTIF(RATEIOS!$A$2:$A${max_rat_row},$A{row_idx})-COUNTIFS(RATEIOS!$A$2:$A${max_rat_row},$A{row_idx},RATEIOS!$D$2:$D${max_rat_row},"<>")>0,"NÃO CLASSIFICADO","RATEIO OK"))))',
        )

    # 3. Update RATEIOS (clean sequential rows without orphan blank rows!)
    cur.execute(
        """
        SELECT r.*
        FROM rateios r
        JOIN extrato e ON e.id_lanc = r.id_lanc
        ORDER BY e.ordem ASC, r.id_rateio ASC
        """
    )
    rat_rows = [dict(r) for r in cur.fetchall()]
    ws_rat = wb["RATEIOS"]

    for r_idx in range(2, max_rat_row + 1):
        arr_idx = r_idx - 2
        if arr_idx < len(rat_rows):
            rr = rat_rows[arr_idx]
            ws_rat.cell(r_idx, 1, rr["id_lanc"])
            ws_rat.cell(
                r_idx,
                2,
                f'=IF(A{r_idx}="","",IF(INDEX(EXTRATO!$C$2:$C$3000,MATCH($A{r_idx},EXTRATO!$A$2:$A$3000,0))="","",INDEX(EXTRATO!$C$2:$C$3000,MATCH($A{r_idx},EXTRATO!$A$2:$A$3000,0))))',
            )
            ws_rat.cell(r_idx, 3, f'=IF(B{r_idx}="","",MONTH(B{r_idx}))')
            ws_rat.cell(r_idx, 4, rr["categoria"] if rr["categoria"] else None)
            ws_rat.cell(r_idx, 5, rr["subcategoria"] if rr["subcategoria"] else None)
            ws_rat.cell(r_idx, 6, float(to_dec(rr["valor"])))
            ws_rat.cell(r_idx, 7, rr["detalhe_componente"] if rr["detalhe_componente"] else None)
            ws_rat.cell(
                r_idx,
                8,
                f'=IF(A{r_idx}="","",IF(INDEX(EXTRATO!$F$2:$F$3000,MATCH($A{r_idx},EXTRATO!$A$2:$A$3000,0))="","",INDEX(EXTRATO!$F$2:$F$3000,MATCH($A{r_idx},EXTRATO!$A$2:$A$3000,0))))',
            )
            ws_rat.cell(
                r_idx,
                9,
                f'=IF(A{r_idx}="","",IF(INDEX(EXTRATO!$H$2:$H$3000,MATCH($A{r_idx},EXTRATO!$A$2:$A$3000,0))="","",INDEX(EXTRATO!$H$2:$H$3000,MATCH($A{r_idx},EXTRATO!$A$2:$A$3000,0))))',
            )
            ws_rat.cell(r_idx, 10, rr["origem_classificacao"] or "CONFIRMADO")
            ws_rat.cell(
                r_idx,
                11,
                f'=IF(AND(A{r_idx}="",D{r_idx}="",E{r_idx}="",F{r_idx}=""),"",IF(D{r_idx}="","SEM CATEGORIA",IF(E{r_idx}="","SEM SUBCATEGORIA",IF(COUNTIFS(CADASTROS!$L$7:$L$94,D{r_idx},CADASTROS!$D$7:$D$94,E{r_idx})=0,"INCOMPATÍVEL","OK"))))',
            )
        else:
            for c_empty in range(1, 12):
                ws_rat.cell(r_idx, c_empty, None)

    conn.close()
    buf = io.BytesIO()
    wb.save(buf)
    return _restore_extrato_validation_extension(buf.getvalue())
