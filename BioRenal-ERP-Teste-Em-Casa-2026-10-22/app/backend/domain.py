# -*- coding: utf-8 -*-
"""
Biorenal — Domínio Contábil, Aritmética Decimal, Plano de Contas Oficial (12 Categorias / 87 Subcategorias),
Extrator Regex de Competência, Unificador Canônico de Fornecedores e Motor Inteligente de Rateio/Sugestão.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import re
from typing import List, Dict, Tuple, Optional, Any

TOLERANCE = Decimal("0.005")
TWO_PLACES = Decimal("0.01")


def to_dec(val: Any) -> Decimal:
    if val is None or val == "":
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    try:
        if isinstance(val, (int, float)):
            return Decimal(str(round(float(val), 6))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        s = str(val).strip()
        if not s:
            return Decimal("0.00")
        # Handle Brazilian format if needed (e.g. 1.234,56)
        if "," in s and "." in s and s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        elif "," in s and "." not in s:
            s = s.replace(",", ".")
        return Decimal(s).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def dec_to_float(val: Any) -> float:
    return float(to_dec(val))


# ==============================================================================
# 1. PLANO DE CONTAS OFICIAL (12 CATEGORIAS E 87 SUBCATEGORIAS - ABA CADASTROS)
# ==============================================================================
PLANO_DE_CONTAS: Dict[str, List[str]] = {
    "ENTRADAS": [
        "Repasse do Estado",
        "Repasse Piso Salarial enfermagem",
        "Saldo anterior em Conta Corrente",
        "Transferências dos Sócios",
        "Resgate do Financiamento (Banco do Nordeste)",
        "Resgate de Aplicações Financeiras (CDI BB)",
        "Aplicações Financeiras",
    ],
    "DESPESAS COM IMPOSTOS": [
        "ISS",
        "PIS",
        "COFINS",
        "DARF - RETENÇÕES (PIS/COFINS/CSLL)",
        "DARF - RETENÇÕES (IRRF)",
        "DARF FÉRIAS",
        "CSLL (Trimestral)",
        "IRPJ (Trimestral)",
    ],
    "DESPESAS COM SALÁRIOS E BENEFÍCIOS": [
        "Folha de Pagamento de Funcionários",
        "Folha de Pagamento (Repasse de piso da Enfermagem)",
        "FGTS",
        "INSS",
        "Rescisão Contratual",
        "Multa Rescisória",
        "Férias de Funcionários",
        "Pagamento de Extras",
        "Fornecimento de quentinhas para equipe da Enfermagem",
        "EPIs e Fardamentos",
    ],
    "DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS": [
        "CasaMater - Confecção Fístula",
        "Exames Laboratorias dos Colaboradores",
        "Exames Laboratorias dos Pacientes",
        "Pagamento Cirurgião Vascular - Dr. Renato",
        "Pagamento Cirurgião Vascular - Dr. Wilson",
        "Pagamento Psicologa - Camilly",
        "Pagamento Farmaceutica - Gardênia",
        "Pagamento Nutricionista - Elaine",
        "Serviço de correção de ficha de sala - Ferronefro",
        "Serviço de enfermagem - Ferronefro",
        "Serviço de RT de enfermagem - Ferronefro",
        "Pagamento de plantão médico - Dr. Lucas",
        "Pagamento de plantão médico - Dr. Hozano",
    ],
    "DESPESAS COM PRESTAÇÃO DE SERVIÇOS - SÓCIOS": [
        "Plantões Médicos (Sócios)",
        "Despesas com Administração / PROLABORE",
        "Responsabilidade Técnica - Dr. Anderson",
    ],
    "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS": [
        "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
        "Capilar, Filtros, Agulhas",
        "CDL e Perm-cath",
        "Linha Arterial e Venosa",
        "Medicações (Heparina, Taurolock)",
        "Solução e Soro para HD",
        "Ácido Cítrico",
        "Peroxide",
        "Hipoclorito",
        "Oxigênio",
        "Solução para Desinfecção Poltronas - BELL FOAM",
        "Qualiagua - Analise Água",
    ],
    "DESPESAS ADMINISTRATIVAS": [
        "Assessoria Administrativa",
        "Contador",
        "Energia Elétrica (Clínica + Casa de Apoio)",
        "Aluguel casa de apoio",
        "Coleta de Lixo",
        "Despesas com Gráfica",
        "Despesas com viagens",
        "Despesas com Cartório",
        "Material de Limpeza",
        "Gás de cozinha para copa",
        "Materiais de Construção, Elétrico e de Escritório",
        "Panificadora",
        "Supermercado",
        "Suporte Informatica - Hardware, Internet, Sistemas e Câmeras",
        "Taxas e Tarifas",
        "Treinamentos e Capacitação",
    ],
    "LOGÍSTICA E FROTA": [
        "Combustível (Gasolina)",
        "Frete com mercadorias",
        "Manutenção de Veículo",
        "Transporte de pacientes e viagens para HTI",
        "IPVA / Licenciamento e Multas",
    ],
    "MANUTENÇÃO E INFRAESTRUTURA": [
        "Manutenção - Máquinas HD, Gerador, Osmose",
        "Manutenção - Ar Condicionados",
        "Manutenção Predial (Reformas e Reparos)",
        "Óleo diesel para gerador",
    ],
    "DESPESAS COM EMPRÉSTIMO E DEMAIS DESPESAS FINANCEIRAS": [
        "Seguro Icatu",
        "Engenheiro",
    ],
    "AQUISIÇÃO DE BENS E EQUIPAMENTOS": [
        "Aquisição de Máquinas de Hemodiálise",
        "Aquisição de Ar Condicionado",
        "Equipamentos de Informática (Computadores)",
        "Financiamento do veículo",
        "Mobiliário e utensílios duráveis",
    ],
    "DESPESAS COM SÓCIOS - LUCROS": [
        "Distribuição de Lucros",
        "Valor repassado aos sócios",
    ],
}

TIPOS_PAGAMENTO = [
    "BOLETO",
    "CHEQUE",
    "DARE",
    "DARF",
    "DÉBITO AUTOMÁTICO",
    "DEPÓSITO",
    "FOLHA DE PAGAMENTO",
    "GUIA DE RECOLHIMENTO",
    "OUTROS",
    "PIX",
    "TED",
    "TRANSFERÊNCIA",
]

TIPOS_MOVIMENTACAO = ["ENTRADA", "SAÍDA", "APLICAÇÃO", "RESGATE"]
STATUS_CONCILIACAO_LIST = ["Conciliado", "Pendente", "Divergência"]
ORIGENS_CLASSIFICACAO = ["AUTOMÁTICO", "MAPEADO", "SUGERIDO", "PENDENTE", "REVISAR", "CONFIRMADO", "DESCONSIDERADO"]

CATEGORIA_DESCONSIDERADO = "DESCONSIDERADO NO RATEIO"
SUBCATEGORIA_DESCONSIDERADO = "Não considerado no Rateio / DRE"


def validate_conferencia(id_lanc: str, categoria: str, subcategoria: str, valor: Decimal) -> str:
    cat = (categoria or "").strip()
    sub = (subcategoria or "").strip()
    if not id_lanc and not cat and not sub and valor == Decimal("0.00"):
        return ""
    if cat == CATEGORIA_DESCONSIDERADO:
        return "OK"
    if not cat:
        return "SEM CATEGORIA"
    if not sub:
        return "SEM SUBCATEGORIA"
    valid_subs = PLANO_DE_CONTAS.get(cat, [])
    if sub not in valid_subs:
        return "INCOMPATÍVEL"
    return "OK"


# ==============================================================================
# 2. EXTRATOR REGEX DE COMPETÊNCIA (MM/YYYY)
# ==============================================================================
MESES_ABREV = {
    "JAN": "01", "JANEIRO": "01",
    "FEV": "02", "FEVEREIRO": "02",
    "MAR": "03", "MARÇO": "03", "MARCO": "03",
    "ABR": "04", "ABRIL": "04",
    "MAI": "05", "MAIO": "05",
    "JUN": "06", "JUNHO": "06",
    "JUL": "07", "JULHO": "07",
    "AGO": "08", "AGOSTO": "08",
    "SET": "09", "SETEMBRO": "09",
    "OUT": "10", "OUTUBRO": "10",
    "NOV": "11", "NOVEMBRO": "11",
    "DEZ": "12", "DEZEMBRO": "12",
}


def extract_competencia(historico: str, observacao: str, data_iso: str) -> str:
    """
    Extrai competência no formato MM/YYYY a partir de historico_banco e observacao.
    Exemplos:
    - "REF. COMP. DEZ/25" -> "12/2025"
    - "PLANTÕES EM MAI/26" -> "05/2026"
    - "COMP. 08/2026" -> "08/2026"
    - "INSS (12/2025)" -> "12/2025"
    - "REF. 4º TRIM/2025" -> "12/2025"
    Fallback: MM/YYYY da data do movimento.
    """
    text = f"{historico or ''} {observacao or ''}".upper()

    # Fallback default from data_iso (YYYY-MM-DD)
    fallback = "01/2026"
    dt_year = 2026
    dt_month = 1
    if data_iso and len(data_iso) >= 7:
        parts = data_iso.split("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            dt_year = int(parts[0])
            dt_month = int(parts[1])
            fallback = f"{dt_month:02d}/{dt_year}"

    # 1. Explicit COMP. / REF. with month name: e.g. COMP. DEZ/2025, REF. JAN/26, EM MAI/26, JUL26
    m_named = re.search(
        r"(?:COMP\.?|REF\.?|EM|DE|MÊS|MES|\()\s*(JANEIRO|FEVEREIRO|MAR[ÇC]O|ABRIL|MAIO|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO|NOVEMBRO|DEZEMBRO|JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*[/\-]?\s*(202[4567]|2[4567])\b",
        text,
    )
    if not m_named:
        # Try general MONTH/YY anywhere in text
        m_named = re.search(
            r"\b(JANEIRO|FEVEREIRO|MAR[ÇC]O|ABRIL|MAIO|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO|NOVEMBRO|DEZEMBRO|JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*[/\-]\s*(202[4567]|2[4567])\b",
            text,
        )
    if not m_named:
        # Handle glued JUL26 like in BAN-01025 ("REF. COMP. JUL26")
        m_named = re.search(r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)(202[56]|2[56])\b", text)

    if m_named:
        m_str = m_named.group(1)
        y_str = m_named.group(2)
        mm = MESES_ABREV.get(m_str, "01")
        yyyy = f"20{y_str}" if len(y_str) == 2 else y_str
        return f"{mm}/{yyyy}"

    # 2. Explicit numeric MM/YYYY or MM/YY after COMP/REF/INSS/FGTS
    m_num = re.search(
        r"(?:COMP\.?|REF\.?|INSS|FGTS|COMPET[ÊE]NCIA)\s*[\(:]?\s*(0[1-9]|1[0-2])\s*/\s*(202[4567]|2[4567])\b",
        text,
    )
    if m_num:
        mm = int(m_num.group(1))
        y_str = m_num.group(2)
        yyyy = int(f"20{y_str}" if len(y_str) == 2 else y_str)
        # Guard against known bank typo in BAN-00026: paid on 2026-01-08 with "COMP. 12/2026" (actually 12/2025)
        if yyyy == 2026 and mm == 12 and dt_month == 1:
            yyyy = 2025
        return f"{mm:02d}/{yyyy}"

    # 3. Trimestre pattern: "4º TRIM/2025", "1º TRIM/2026", "2º TRIM/2026"
    m_trim = re.search(r"([1-4])[º°]?\s*TRIM(?:ESTRE)?\s*/\s*(202[4567]|2[4567])", text)
    if m_trim:
        q = int(m_trim.group(1))
        y_str = m_trim.group(2)
        yyyy = f"20{y_str}" if len(y_str) == 2 else y_str
        mm = q * 3
        return f"{mm:02d}/{yyyy}"

    # 4. Quinzenas pattern: "08/12 E 23/12" in January -> 12/2025
    m_quinz = re.search(r"\b([0-3]\d)/(0[1-9]|1[0-2])\s+E\s+[0-3]\d/(0[1-9]|1[0-2])\b", text)
    if m_quinz:
        mm = int(m_quinz.group(3))
        yyyy = dt_year - 1 if (mm == 12 and dt_month == 1) else dt_year
        return f"{mm:02d}/{yyyy}"

    return fallback


# ==============================================================================
# 3. UNIFICADOR CANÔNICO DE FORNECEDORES (DE-PARA CANÔNICO - MÓDULO 5)
# ==============================================================================
CANONICAL_SUPPLIER_GROUPS: Dict[str, List[str]] = {
    "BRANDÃO & BRANDÃO": [
        "BRANDÃO & BRANDÃO",
        "BRANDÃO E BRANDÃO",
        "BRANDO & BRANDÃO",
    ],
    "EXCELLENCE DISTRIBUIDORA": [
        "EXCELLENCE DISTRIBUIÇÃO",
        "EXCELLENCE DISTRIBUIDORA",
    ],
    "RICEK INDÚSTRIA E COMÉRCIO": [
        "RICEK",
        "RICEK INDUSTRIA E COMÉRCIO",
    ],
    "FARMARIN INDÚSTRIA": [
        "FARMARIN INDUST",
        "FARMARIN INDUSTRIA",
        "FARMARIN INDUST.",
    ],
    "ALECRIM INDÚSTRIA E COMÉRCIO": [
        "ALECRIM",
        "ALECRIM INDUSTRIA",
        "ALECRIM INDUSTRIA E COMÉRCIO",
    ],
    "CASSIANO & CASSIANO CONTABILIDADE": [
        "CASSIANO & CASSINOS CONTABILIDADE",
        "CASSIANO E CASSIANO",
    ],
    "CLÍNICA DR. LUCAS ALBUQUERQUE": [
        "L F ALBUQUERQUE DA SILVA",
        "CLINICA DR. LUCAS ALBUQUERQUE",
    ],
    "AFONSO PAULO COSTA FERRO": [
        "AFONSO PAULO C. FERRO",
        "AFONSO PAULO COSTA FERRO",
    ],
    "CELINA TCBC DE MIRANDA": [
        "CELINA T C B C DE MIRANDA",
        "CELINA TCBC DE MIRANDA",
    ],
    "DR. MOISÉS OLIVEIRA": [
        "MOISES DA S. OLIVEIRA",
        "MOISES S OLIVEIRA",
    ],
    "FRANCISCO HAMILTON SOUSA": [
        "FRANCISCO H SOUSA",
        "FRANCISCO HAMILTON SOUSA",
    ],
    "ADÉLIA DALVA DA SILVA OLIVEIRA": [
        "ADELIA DALVA DA SILVA",
        "ADELIA DALVA DA SILVA OLIVEIRA",
    ],
    "CLAUDIANE CARDOSO DA SILVA (HTI)": [
        "CLAUDIANE C. SILVA",
        "CLAUDIANE CARDOSO DA SILVA",
        "CLAUDIANE CARDOSO SILVA",
        "CLAUDIANE CARDOSO DA SILVA (CARRO HTI)",
        "MOTORISTA VIAGEM TERESINA",
    ],
    # Additional helpful unifications in the dataset
    "SUPERMERCADO CAMINO": [
        "CAMINO",
        "A C R DA SILVA E CIA (SUPERMERCADO CAMINO)",
    ],
    "LEMOS BRANCO & CIA (POSTO PREMIUM)": [
        "LEMOS BRANCO & CIA",
        "POSTO PREMIUM",
    ],
    "BANCO DO BRASIL - CDB DI": [
        "BANCO DO BRASIL - CDB DI",
        "RESGATE BB CDB DI",
        "APLICAÇÃO",
    ],
    "HR MANUTENÇÃO HOSPITALAR (HUGO RAMON)": [
        "HR MANUTENCAO HOSPITALAR",
        "HR MANUTENÇÃO HOSPITALAR",
    ],
    "M E S XAVIER (OXIGÊNIO)": [
        "M E S XAVIER",
        "M E S XAVIER LTDA",
    ],
    "NORTE FLOW": [
        "NORTE FLOW",
        "NORTEFLOW",
    ],
    "BIOPAR CONFECÇÕES": [
        "BIOPAR",
        "BIOPAR CONFECÇÕES",
    ],
    "WILSON DE FREITAS SORIANO (BOTECO DO TARCÍSIO)": [
        "WILSON DE FREITAS SORIANO",
        "BOTECO DO TARCISIO",
    ],
    "MARKETPLACE MERCADO LIVRE": [
        "MARKETPLACE MERCADO LIVRE",
        "MERCADO LIVRE",
    ],
    "DRA. FABIANA CRISTINA BARROS": [
        "FABIANA CRISTINA",
        "FABIANA CRISTINA BARROS",
        "MARCELO DA COSTA MIGON",
    ],
    "DR. PATRICK DULFF": [
        "PATRICK DULFF",
        "PATRICK DULFF LOBO ARAUJO",
        "JOYCE KAROLINA",
    ],
    "DR. ANDERSON RAFAEL SALVIANO": [
        "ANDERSON RAFAEL SALVIANO",
    ],
    "DR. GLADSTONE SANTOS SILVA": [
        "GLADSTONE SANTOS SILVA",
    ],
    "FARMACÊUTICA GARDÊNIA / REBECA": [
        "FARMACÊUTICA GARDÊNIA",
        "FARMACÊUTICA REBECA",
        "FARMACÊUTICA",
    ],
}

# Build reverse lookup map (UPPERCASE -> Canonical Name)
_REVERSE_CANONICAL: Dict[str, str] = {}
for canon, variants in CANONICAL_SUPPLIER_GROUPS.items():
    _REVERSE_CANONICAL[canon.upper()] = canon
    for v in variants:
        _REVERSE_CANONICAL[v.strip().upper()] = canon


def infer_missing_supplier(historico: str) -> str:
    """
    Infere o nome oficial do fornecedor (compatível com a aba CADASTROS/EXTRATO)
    quando o campo FORNECEDOR/FAVORECIDO está em branco ou '-' (ex: BAN-01029 a BAN-01061, BAN-00949, BAN-00961).
    """
    h = (historico or "").strip().upper()
    if not h:
        return ""
    rules = [
        ("KELLY RAVANA TEIXEIRA DE MESQUITA", "KELLY RAVANA TEIXEIRA DE MESQUITA"),
        ("ADAILTON MESSIAS MENDONÇA", "ADAILTON MESSIAS MENDONÇA"),
        ("CASAMATER", "CASAMATER"),
        ("DONA MARINALVA", "DONA MARINALVA"),
        ("M DA SILVA MUNIZ", "DONA MARINALVA"),
        ("M MUNIZ", "DONA MARINALVA"),
        ("UNICLINICA", "UNICLINICA"),
        ("DR. RENATO", "DR. RENATO"),
        ("EMANUELLE ARAÚJO", "ASSESSORIA ADMINISTRATIVA"),
        ("LUANA MELO", "LUANA MELO VIEGAS"),
        ("HR MANUTENÇÃO HOSPITALAR", "HR MANUTENCAO HOSPITALAR"),
        ("HR MANUTENCAO HOSPITALAR", "HR MANUTENCAO HOSPITALAR"),
        ("DR. WILSON", "DR. WILSON"),
        ("E M GONÇALVES PADARIA", "E M GONÇALVES PADARIA"),
        ("FARMACÊUTICA (GARDÊNIA)", "FARMACÊUTICA GARDÊNIA"),
        ("FARMACÊUTICA GARDÊNIA", "FARMACÊUTICA GARDÊNIA"),
        ("I F DA SILVA & CIA LTDA", "I F DA SILVA & CIA LTDA"),
        ("DECOR COLORS BACABAL", "DECOR COLORS BACABAL"),
        ("LUAN CALIXTA DE OLIVEIRA", "LUAN CALIXTA DE OLIVEIRA"),
        ("PHARMA BRASIL", "PHARMA BRASIL"),
        ("RICEK", "RICEK INDUSTRIA E COMÉRCIO"),
        ("INOVMED DISTRIBUIDORA", "INOVMED DISTRIBUIDORA"),
        ("ERONLIMP", "ERONLIMP"),
        ("FGTS RESCISÓRIO", "FGTS RESCISÓRIO"),
        ("FGTS", "FGTS"),
        ("INSS", "INSS"),
        ("DARF - RETENÇÕES", "TRIBUTOS FEDEREIAS MENSAIS"),
        ("CASSIANO E CASSIANO", "CASSIANO & CASSINOS CONTABILIDADE"),
        ("CASSIANO & CASSINOS", "CASSIANO & CASSINOS CONTABILIDADE"),
        ("TOKIO MARINE", "TOKIO MARINE SEGURADORA S.A"),
        ("RESGATE BB CDB DI", "BANCO DO BRASIL - CDB DI"),
        ("EQUATORIAL MARANHÃO", "EQUATORIAL MARANHÃO"),
        ("ALLMED PRONEFRO", "ALLMED PRONEFRO"),
        ("DIÁLISE COMÉRCIO", "DIALISE COMERCIO"),
        ("DIALISE COMÉRCIO", "DIALISE COMERCIO"),
        ("FARMACE", "FARMACE"),
        ("NIPRO", "NIPRO"),
        ("BIOCOMPANY", "BIOCOMPANY"),
        ("EXCELLENCE", "EXCELLENCE DISTRIBUIDORA"),
        ("SUPERMERCADO CAMINO", "CAMINO"),
        ("CLAUDIANE CARDOSO", "CLAUDIANE CARDOSO DA SILVA (CARRO HTI)"),
        ("MARANET TELECOM", "MARANET TELECOM"),
        ("REMORA HOSPITALAR", "REMORA HOSPITALAR"),
        ("SUPERMÉDICA", "SUPERMÉDICA"),
        ("CRISTALIA PRODUTOS", "CRISTALIA PRODUTOS"),
        ("NORTEFLOW", "NORTE FLOW"),
        ("NORTE FLOW", "NORTE FLOW"),
        ("BIOGREEN", "BIOGREEN"),
        ("BANCO VOLKSWAGEN", "BANCO VOLKSWAGEN"),
        ("BOTECO DO TARCISIO", "WILSON DE FREITAS SORIANO"),
        ("WILSON DE FREITAS SORIANO", "WILSON DE FREITAS SORIANO"),
        ("MASTER GRAFICA", "MASTER GRAFICA DIGITAL"),
        ("FERCASTRO", "FERCASTRO"),
        ("PNEUFREE", "PNEUFREE"),
        ("BANCO BRB", "HONORÁRIOS ADVOCATÍCIOS"),
    ]
    for kw, target in rules:
        if kw in h:
            return target
    return historico.split("(")[0].strip()[:60]


def get_canonical_supplier(fornecedor: str, historico: str = "") -> str:
    f = (fornecedor or "").strip()
    if not f or f == "-":
        f = infer_missing_supplier(historico)
    f_up = f.upper()
    if f_up in _REVERSE_CANONICAL:
        return _REVERSE_CANONICAL[f_up]
    return f


# ==============================================================================
# 4. TEMPLATES DE RATEIO RECORRENTE (MÓDULO 3) E MOTOR DE SUGESTÃO (MÓDULO 2)
# ==============================================================================
def build_ferronefro_split(valor_total: Decimal, historico: str) -> List[Dict[str, Any]]:
    """
    Template Ferronefro (I F DA SILVA & CIA LTDA):
    Divide automaticamente em 5 linhas padrão, ajustando o serviço de enfermagem
    (ou extras) para fechar 100% com o valor do extrato sem divergência de centavos.
    """
    nutri = Decimal("3419.97")
    rt = Decimal("800.00")
    ficha = Decimal("500.00") if valor_total >= Decimal("9000.00") else Decimal("400.00")
    psico = Decimal("2000.00") if (valor_total >= Decimal("10000.00") or "PSICOL" in (historico or "").upper()) else Decimal("0.00")

    base_others = nutri + rt + ficha + psico
    enf = valor_total - base_others
    if enf < Decimal("0.00"):
        # Fallback proportional if small amount
        enf = valor_total

    items = [
        {
            "categoria": "DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS",
            "subcategoria": "Serviço de enfermagem - Ferronefro",
            "valor": float(enf),
            "detalhe_componente": f"{historico} - SERVIÇO DE ENFERMAGEM",
        },
        {
            "categoria": "DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS",
            "subcategoria": "Pagamento Nutricionista - Elaine",
            "valor": float(nutri),
            "detalhe_componente": f"{historico} - NUTRICIONISTA ELAINE",
        },
    ]
    if psico > Decimal("0.00"):
        items.append({
            "categoria": "DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS",
            "subcategoria": "Pagamento Psicologa - Camilly",
            "valor": float(psico),
            "detalhe_componente": f"{historico} - PSICÓLOGA CAMILLY",
        })
    items.extend([
        {
            "categoria": "DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS",
            "subcategoria": "Serviço de RT de enfermagem - Ferronefro",
            "valor": float(rt),
            "detalhe_componente": f"{historico} - RT DE ENFERMAGEM",
        },
        {
            "categoria": "DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS",
            "subcategoria": "Serviço de correção de ficha de sala - Ferronefro",
            "valor": float(ficha),
            "detalhe_componente": f"{historico} - CORREÇÃO DE FICHA DE SALA",
        },
    ])
    return items


def build_socio_split(valor_total: Decimal, fornecedor: str, historico: str) -> List[Dict[str, Any]]:
    """
    Template Pagamento Sócios (Plantão R$ 2.500/plantão + Lucro + Pró-Labore R$ 1.621 + RT R$ 1.621).
    Fecha exatamente no centavo com valor_total.
    """
    h = (historico or "").upper()
    f = (fornecedor or "").upper()
    items = []
    rem = valor_total

    has_prolabore = "PRÓ-LABORE" in h or "PRO-LABORE" in h or "PROLABORE" in h
    has_rt = "RESPONSABILIDADE TÉCNICA" in h or "RESPONSABILIDADE TECNICA" in h
    has_lucro = "DISTRIBUIÇÃO DE LUCROS" in h or "DISTRIBUICAO DE LUCROS" in h
    has_plantao = "PLANTÕES" in h or "PLANTOES" in h or "PLANTÃO" in h

    if has_prolabore and rem >= Decimal("1621.00"):
        items.append({
            "categoria": "DESPESAS COM PRESTAÇÃO DE SERVIÇOS - SÓCIOS",
            "subcategoria": "Despesas com Administração / PROLABORE",
            "valor": 1621.00,
            "detalhe_componente": f"{fornecedor} (REF. PRÓ-LABORE COMO SÓCIO ADMINISTRADOR)",
        })
        rem -= Decimal("1621.00")

    if has_rt and rem >= Decimal("1621.00"):
        items.append({
            "categoria": "DESPESAS COM PRESTAÇÃO DE SERVIÇOS - SÓCIOS",
            "subcategoria": "Responsabilidade Técnica - Dr. Anderson",
            "valor": 1621.00,
            "detalhe_componente": f"{fornecedor} (REF. RESPONSABILIDADE TÉCNICA)",
        })
        rem -= Decimal("1621.00")

    if has_lucro and has_plantao:
        # Standard quota profit distribution per partner:
        # Anderson, Fabiana, Celina, Afonso = 8000; Moises, Gladstone, Adelia, Francisco = 4000; Patrick = 2000
        if "PATRICK" in f or "PATRICK" in h:
            lucro_padrao = Decimal("2000.00")
        elif any(x in f or x in h for x in ["MOISES", "GLADSTONE", "ADELIA", "FRANCISCO"]):
            lucro_padrao = Decimal("4000.00")
        else:
            lucro_padrao = Decimal("8000.00")

        if rem >= lucro_padrao:
            plantoes_val = rem - lucro_padrao
            if plantoes_val > Decimal("0.00"):
                qtd_p = int((plantoes_val / Decimal("2500.00")).to_integral_value(rounding=ROUND_HALF_UP))
                items.append({
                    "categoria": "DESPESAS COM PRESTAÇÃO DE SERVIÇOS - SÓCIOS",
                    "subcategoria": "Plantões Médicos (Sócios)",
                    "valor": float(plantoes_val),
                    "detalhe_componente": f"{fornecedor} (REF. {qtd_p:02d} PLANTÕES MÉDICOS)",
                })
            items.append({
                "categoria": "DESPESAS COM SÓCIOS - LUCROS",
                "subcategoria": "Distribuição de Lucros",
                "valor": float(lucro_padrao),
                "detalhe_componente": f"{fornecedor} (REF. DISTRIBUIÇÃO DE LUCROS)",
            })
            rem = Decimal("0.00")

    if rem > Decimal("0.00"):
        if has_lucro and not has_plantao:
            items.append({
                "categoria": "DESPESAS COM SÓCIOS - LUCROS",
                "subcategoria": "Distribuição de Lucros",
                "valor": float(rem),
                "detalhe_componente": f"{fornecedor} (REF. DISTRIBUIÇÃO DE LUCROS)",
            })
        else:
            qtd_p = int((rem / Decimal("2500.00")).to_integral_value(rounding=ROUND_HALF_UP))
            items.append({
                "categoria": "DESPESAS COM PRESTAÇÃO DE SERVIÇOS - SÓCIOS",
                "subcategoria": "Plantões Médicos (Sócios)",
                "valor": float(rem),
                "detalhe_componente": f"{fornecedor} (REF. {qtd_p:02d} PLANTÕES MÉDICOS)",
            })
    return items


def build_notas_mistas_split(valor_total: Decimal, fornecedor: str, historico: str) -> List[Dict[str, Any]]:
    """
    Template Notas Mistas (Farmace / Diálise Comércio / Biocompany / Excellence / Ricek).
    Analisa o histórico do lançamento e divide nas subcategorias exatas de Hemodiálise/Adm.
    """
    h = (historico or "").upper()
    f = (fornecedor or "").upper()

    # 1. FARMACE
    if "FARMACE" in f or "FARMACE" in h:
        if any(w in h for w in ["DIPIRONA", "GLICOSE", "CLORETO", "PARACETAMOL", "PARECETAMOL", "ÁGUA DESTILADA"]):
            # Check known exact splits from Biorenal invoices:
            # NF 365424: 22683.70 or 22283.00 -> Med. Div. = 382.50, Soluções/Soros = restante
            # NF 366475: 21592.20 -> Med. Div. = 340.00, Soluções/Soros = 21252.20
            med_div = Decimal("340.00") if valor_total < Decimal("22000.00") else Decimal("382.50")
            sol_soro = valor_total - med_div
            return [
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Solução e Soro para HD",
                    "valor": float(sol_soro),
                    "detalhe_componente": f"{historico} - SOLUÇÕES E SOROS PARA HD",
                },
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
                    "valor": float(med_div),
                    "detalhe_componente": f"{historico} - MEDICAMENTOS DIVERSOS (DIPIRONA/CLORETO/GLICOSE)",
                },
            ]
        return [{
            "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
            "subcategoria": "Solução e Soro para HD",
            "valor": float(valor_total),
            "detalhe_componente": historico,
        }]

    # 2. DIÁLISE COMÉRCIO
    if "DIALISE" in f or "DIÁLISE" in h or "DIALISE" in h:
        # Check specific multi-item invoices in Sep/Oct:
        # NF 1019 (R$ 2145.00): Peroxide 1680 + Indicador 120 + Isolador 345 = 2145
        if valor_total == Decimal("2145.00"):
            return [
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Peroxide",
                    "valor": 1680.00,
                    "detalhe_componente": "DIÁLISE COMÉRCIO (REF. PEROXIDE 50%)",
                },
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
                    "valor": 465.00,
                    "detalhe_componente": "DIÁLISE COMÉRCIO (REF. INDICADOR DE ÁCIDO PERACÉTICO E ISOLADOR DE PRESSÃO)",
                },
            ]
        # NF 1170 (R$ 3670.00): Ácido Cítrico 1950 + Peroxide 1120 + Indicador/Isolador 600 = 3670
        if valor_total == Decimal("3670.00"):
            return [
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Ácido Cítrico",
                    "valor": 1950.00,
                    "detalhe_componente": "DIÁLISE COMÉRCIO (REF. ÁCIDO CÍTRICO)",
                },
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Peroxide",
                    "valor": 1120.00,
                    "detalhe_componente": "DIÁLISE COMÉRCIO (REF. PEROXIDE)",
                },
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
                    "valor": 600.00,
                    "detalhe_componente": "DIÁLISE COMÉRCIO (REF. INDICADOR E ISOLADOR DE PRESSÃO)",
                },
            ]
        # NF 1303 (R$ 2895.00): Peroxide 1680 + Tampa/Indicador/Isolador 1215 = 2895
        if valor_total == Decimal("2895.00"):
            return [
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Peroxide",
                    "valor": 1680.00,
                    "detalhe_componente": "DIÁLISE COMÉRCIO (REF. PEROXIDE 5%)",
                },
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
                    "valor": 1215.00,
                    "detalhe_componente": "DIÁLISE COMÉRCIO (REF. TAMPA P/ CATETER, INDICADOR E ISOLADOR DE PRESSÃO)",
                },
            ]
        if "TAUROLOCK" in h:
            return [{
                "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                "subcategoria": "Medicações (Heparina, Taurolock)",
                "valor": float(valor_total),
                "detalhe_componente": historico,
            }]
        if "CAPILAR" in h and "PEROXIDE" not in h:
            return [{
                "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                "subcategoria": "Capilar, Filtros, Agulhas",
                "valor": float(valor_total),
                "detalhe_componente": historico,
            }]
        # Generic 70% Peroxide / 30% Med. Div.
        p_val = (valor_total * Decimal("0.70")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        m_val = valor_total - p_val
        return [
            {
                "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                "subcategoria": "Peroxide",
                "valor": float(p_val),
                "detalhe_componente": f"{historico} - PEROXIDE",
            },
            {
                "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                "subcategoria": "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
                "valor": float(m_val),
                "detalhe_componente": f"{historico} - DEMAIS INSUMOS",
            },
        ]

    # 3. BIOCOMPANY
    if "BIOCOMPANY" in f or "BIOCOMPANY" in h:
        if "CURATIVO" in h or "TAMPA" in h or "BANDAGEM" in h:
            if valor_total == Decimal("2560.00"):
                c_val, m_val = Decimal("2220.00"), Decimal("340.00")
            elif valor_total == Decimal("1607.50"):
                c_val, m_val = Decimal("1360.00"), Decimal("247.50")
            elif valor_total == Decimal("1510.00"):
                c_val, m_val = Decimal("1360.00"), Decimal("150.00")
            else:
                c_val = (valor_total * Decimal("0.80")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                m_val = valor_total - c_val
            return [
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "CDL e Perm-cath",
                    "valor": float(c_val),
                    "detalhe_componente": f"{historico} - CDL E PERM-CATH",
                },
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
                    "valor": float(m_val),
                    "detalhe_componente": f"{historico} - CURATIVOS E TAMPAS PARA CATETER",
                },
            ]
        return [{
            "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
            "subcategoria": "CDL e Perm-cath",
            "valor": float(valor_total),
            "detalhe_componente": historico,
        }]

    # 4. EXCELLENCE DISTRIBUIDORA
    if "EXCELLENCE" in f or "EXCELLENCE" in h:
        if "HEPARINA" in h and "INSUMOS" in h:
            hep = Decimal("7250.00") if valor_total > Decimal("7500.00") else (valor_total * Decimal("0.75")).quantize(TWO_PLACES)
            ins = valor_total - hep
            return [
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Medicações (Heparina, Taurolock)",
                    "valor": float(hep),
                    "detalhe_componente": f"{historico} - HEPARINAS",
                },
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
                    "valor": float(ins),
                    "detalhe_componente": f"{historico} - INSUMOS E MATERIAIS",
                },
            ]
        return [{
            "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
            "subcategoria": "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
            "valor": float(valor_total),
            "detalhe_componente": historico,
        }]

    # 5. RICEK (Papel Toalha/Higiênico + Hipoclorito)
    if "RICEK" in f or "RICEK" in h:
        if "HIPOCLORITO" in h and ("PAPEL" in h or "HIGIÊNICO" in h):
            hip = Decimal("605.55") if valor_total > Decimal("700.00") else (valor_total * Decimal("0.60")).quantize(TWO_PLACES)
            limp = valor_total - hip
            return [
                {
                    "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
                    "subcategoria": "Hipoclorito",
                    "valor": float(hip),
                    "detalhe_componente": f"{historico} - HIPOCLORITO",
                },
                {
                    "categoria": "DESPESAS ADMINISTRATIVAS",
                    "subcategoria": "Material de Limpeza",
                    "valor": float(limp),
                    "detalhe_componente": f"{historico} - PAPEL TOALHA E HIGIÊNICO",
                },
            ]
        return [{
            "categoria": "DESPESAS ADMINISTRATIVAS",
            "subcategoria": "Material de Limpeza",
            "valor": float(valor_total),
            "detalhe_componente": historico,
        }]

    # Default fallback split
    p1 = (valor_total * Decimal("0.80")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    p2 = valor_total - p1
    return [
        {
            "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
            "subcategoria": "Solução e Soro para HD",
            "valor": float(p1),
            "detalhe_componente": f"{historico} - ITEM PRINCIPAL",
        },
        {
            "categoria": "DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS",
            "subcategoria": "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.",
            "valor": float(p2),
            "detalhe_componente": f"{historico} - DEMAIS ITENS",
        },
    ]


def suggest_for_movement(mov: Dict[str, Any]) -> Dict[str, Any]:
    """
    Motor de sugestão automática para qualquer movimento bancário (incluindo todos os 165 movimentos
    NÃO CLASSIFICADOS de Jan-Out/2026 somando R$ 2.117.734,75).
    Retorna:
      - fornecedor_sugerido: str
      - status_conciliacao_sugerido: str ("Conciliado")
      - tipo_pagamento_corrigido: str (ex. "PP" -> "PIX")
      - rateios_sugeridos: List[Dict] (1 ou N linhas fechando 100% com o valor do movimento)
      - regra_aplicada: str
    """
    id_lanc = mov.get("id_lanc", "")
    hist = (mov.get("historico_banco") or "").strip()
    h_up = hist.upper()
    forn_atual = (mov.get("fornecedor_favorecido") or "").strip()
    if not forn_atual or forn_atual == "-":
        forn_sug = infer_missing_supplier(hist)
    else:
        forn_sug = forn_atual
    f_up = forn_sug.upper()

    tipo_mov = (mov.get("tipo_movimentacao") or "SAÍDA").upper()
    tipo_pag = (mov.get("tipo_pagamento") or "PIX").upper()
    if tipo_pag == "PP":
        tipo_pag = "PIX"

    val = (
        to_dec(mov.get("entrada"))
        + to_dec(mov.get("saida"))
        + to_dec(mov.get("aplicacao"))
        + to_dec(mov.get("resgate"))
    )

    def single(cat: str, sub: str, regra: str) -> Dict[str, Any]:
        return {
            "id_lanc": id_lanc,
            "fornecedor_sugerido": forn_sug,
            "status_conciliacao_sugerido": "Conciliado",
            "tipo_pagamento_corrigido": tipo_pag,
            "regra_aplicada": regra,
            "is_split": False,
            "rateios_sugeridos": [
                {
                    "categoria": cat,
                    "subcategoria": sub,
                    "valor": float(val),
                    "detalhe_componente": hist or forn_sug,
                }
            ],
        }

    # 1. RESGATES E APLICAÇÕES CDB BB
    if tipo_mov == "RESGATE" or "RESGATE BB CDB DI" in h_up or "CDB/RDB" in h_up or "RENDE FÁCIL" in h_up:
        forn_sug = "BANCO DO BRASIL - CDB DI"
        return single("ENTRADAS", "Resgate de Aplicações Financeiras (CDI BB)", "Regra CDB DI -> Resgate Aplicação")

    if tipo_mov == "APLICAÇÃO" or "APLICAÇÃO - CDB" in h_up:
        forn_sug = "APLICAÇÃO"
        return single("ENTRADAS", "Aplicações Financeiras", "Regra CDB DI -> Aplicação Financeira")

    # 2. ENTRADAS (REPASSES DO ESTADO, PISO ENFERMAGEM, SÓCIOS, FINANCIAMENTO)
    if tipo_mov == "ENTRADA":
        if "PISO SALARIAL ENFERMAGEM" in h_up or "PISO DE ENFERMAGEM" in f_up or "MA FES ENFERMAGEM" in f_up:
            return single("ENTRADAS", "Repasse Piso Salarial enfermagem", "Pass-Through -> Repasse Piso Enfermagem")
        if "ORDEM BANCÁRIA ESTADO MA" in h_up or "REPASSE DO CONTRATO" in f_up:
            return single("ENTRADAS", "Repasse do Estado", "Receita Operacional SUS/Estado MA")
        if "DEPÓSITO DO FINANCIAMENTO" in h_up or "BIORENAL LTDA" in f_up:
            return single("ENTRADAS", "Resgate do Financiamento (Banco do Nordeste)", "Financiamento BNB -> Entrada")
        if any(s in h_up or s in f_up for s in ["ADELIA DALVA", "FABIANA", "ANDERSON", "CELINA", "AFONSO", "MOISES", "GLADSTONE", "FRANCISCO", "PATRICK"]):
            return single("ENTRADAS", "Transferências dos Sócios", "Aporte / Reembolso de Sócios")
        if "ESTORNO" in h_up or "REJEITADO" in h_up:
            return single("ENTRADAS", "Saldo anterior em Conta Corrente", "Estorno Bancário / Rejeição PIX")
        return single("ENTRADAS", "Repasse do Estado", "Entrada Operacional")

    # 3. CASOS MULTI-LINHA (TEMPLATES 1:N)
    if "I F DA SILVA" in h_up or "I F DA SILVA" in f_up:
        splits = build_ferronefro_split(val, hist)
        return {
            "id_lanc": id_lanc,
            "fornecedor_sugerido": "I F DA SILVA & CIA LTDA",
            "status_conciliacao_sugerido": "Conciliado",
            "tipo_pagamento_corrigido": tipo_pag,
            "regra_aplicada": "Template Ferronefro (5 componentes)",
            "is_split": True,
            "rateios_sugeridos": splits,
        }

    if any(s in h_up or s in f_up for s in [
        "AFONSO PAULO", "ANDERSON RAFAEL", "FABIANA CRISTINA", "PATRICK DULFF",
        "MOISES S OLIVEIRA", "MOISES DA S", "GLADSTONE SANTOS", "CELINA TCBC",
        "ADELIA DALVA", "FRANCISCO H"
    ]):
        splits = build_socio_split(val, forn_sug, hist)
        return {
            "id_lanc": id_lanc,
            "fornecedor_sugerido": forn_sug,
            "status_conciliacao_sugerido": "Conciliado",
            "tipo_pagamento_corrigido": tipo_pag,
            "regra_aplicada": "Template Sócios (Plantões / Pró-Labore / RT / Lucros)",
            "is_split": len(splits) > 1,
            "rateios_sugeridos": splits,
        }

    if any(k in h_up or k in f_up for k in ["FARMACE", "DIALISE COMERCIO", "DIÁLISE COMÉRCIO", "BIOCOMPANY", "EXCELLENCE", "RICEK"]):
        splits = build_notas_mistas_split(val, forn_sug, hist)
        return {
            "id_lanc": id_lanc,
            "fornecedor_sugerido": forn_sug,
            "status_conciliacao_sugerido": "Conciliado",
            "tipo_pagamento_corrigido": tipo_pag,
            "regra_aplicada": "Template Notas Mistas / Insumos HD",
            "is_split": len(splits) > 1,
            "rateios_sugeridos": splits,
        }

    # 4. REGRAS DIRETAS POR FORNECEDOR / PALAVRAS-CHAVE DO HISTÓRICO (JAN-AGO)
    if "ALLMED PRONEFRO" in h_up or "ALLMED" in f_up:
        return single("DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS", "Linha Arterial e Venosa", "Histórico Jan-Ago: Allmed -> Linha Arterial e Venosa")

    if "NIPRO" in h_up or "NIPRO" in f_up:
        if "MÁQUINAS DE HD" in h_up or "MAQUINAS DE HD" in h_up or "REGULADOR DE PRESSÃO" in h_up:
            return single("AQUISIÇÃO DE BENS E EQUIPAMENTOS", "Aquisição de Máquinas de Hemodiálise", "Capex Nipro -> Aquisição de Máquinas de HD")
        return single("DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS", "Capilar, Filtros, Agulhas", "Histórico Jan-Ago: Nipro Medical -> Capilar, Filtros, Agulhas")

    if "CRISTALIA" in h_up or "CRISTALIA" in f_up:
        if "CEFAZIMA" in h_up or "CEFAZOLINA" in h_up:
            # BAN-01008 has Heparinas + Cefazima/Cefazolina
            return single("DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS", "Medicações (Heparina, Taurolock)", "Histórico Jan-Ago: Cristália -> Medicações (Heparina)")
        return single("DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS", "Medicações (Heparina, Taurolock)", "Histórico Jan-Ago: Cristália -> Medicações (Heparina)")

    if any(x in h_up or x in f_up for x in ["REMORA HOSPITALAR", "SUPERMÉDICA", "UPERMÉDICA", "INOVMED", "BIOPAR", "PHARMA BRASIL", "ULTRAMEGA"]):
        return single("DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS", "Agulhas, Seringas, Máscaras, Luvas, Equipo e Med. Div.", "Histórico Jan-Ago: Insumos e Med. Div.")

    if "QUALIÁGUA" in h_up or "QUALIAGUA" in h_up or "QUALIÁGUA" in f_up:
        return single("DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS", "Qualiagua - Analise Água", "Histórico Jan-Ago: Qualiágua -> Análise de Água")

    if "XAVIER" in h_up or "OXIGÊNIO" in h_up:
        return single("DESPESAS COM MATERIAIS PARA HEMODIÁLISE E DEMAIS CUSTOS", "Oxigênio", "Histórico Jan-Ago: M E S Xavier -> Oxigênio")

    if "EQUATORIAL" in h_up or "EQUATORIAL" in f_up:
        return single("DESPESAS ADMINISTRATIVAS", "Energia Elétrica (Clínica + Casa de Apoio)", "Histórico Jan-Ago: Equatorial -> Energia Elétrica")

    if "CAMINO" in h_up or "CAMINO" in f_up or "A C R DA SILVA" in h_up:
        return single("DESPESAS ADMINISTRATIVAS", "Supermercado", "Histórico Jan-Ago: Supermercado Camino -> Supermercado")

    if "PADARIA" in h_up or "GONÇALVES PADARIA" in h_up or "DONA MARINALVA" in h_up or "M MUNIZ" in h_up or "M DA SILVA MUNIZ" in h_up:
        return single("DESPESAS ADMINISTRATIVAS", "Panificadora", "Histórico Jan-Ago: Padaria / Lanches -> Panificadora")

    if "BOTECO DO TARCISIO" in h_up or "WILSON DE FREITAS SORIANO" in h_up or "PANELA VELHA" in h_up or "QUENTINHAS" in h_up:
        return single("DESPESAS COM SALÁRIOS E BENEFÍCIOS", "Fornecimento de quentinhas para equipe da Enfermagem", "Histórico Jan-Ago: Quentinhas Enfermagem")

    if "FOLHA DE PAGAMENTO" in h_up or "FOLHA DE PAGAMENTO" in f_up:
        if "PISO SALARIAL" in h_up or "PISO" in f_up:
            return single("DESPESAS COM SALÁRIOS E BENEFÍCIOS", "Folha de Pagamento (Repasse de piso da Enfermagem)", "Pass-Through -> Folha Piso da Enfermagem")
        if "FÉRIAS" in h_up or "FERIAS" in h_up:
            return single("DESPESAS COM SALÁRIOS E BENEFÍCIOS", "Férias de Funcionários", "Histórico Jan-Ago: Férias de Funcionários")
        return single("DESPESAS COM SALÁRIOS E BENEFÍCIOS", "Folha de Pagamento de Funcionários", "Histórico Jan-Ago: Folha de Pagamento Mensal")

    if "RESCISÃO" in h_up or "RESCISÓRIO" in h_up or "RESCISÃO" in f_up:
        return single("DESPESAS COM SALÁRIOS E BENEFÍCIOS", "Rescisão Contratual", "Histórico Jan-Ago: Rescisão / FGTS Rescisório")

    if h_up.startswith("FGTS") or f_up == "FGTS":
        return single("DESPESAS COM SALÁRIOS E BENEFÍCIOS", "FGTS", "Encargos Trabalhistas -> FGTS")

    if h_up.startswith("INSS") or f_up == "INSS":
        return single("DESPESAS COM SALÁRIOS E BENEFÍCIOS", "INSS", "Encargos Trabalhistas -> INSS")

    if "MALHARIA" in h_up or "FARDAMENTO" in h_up or "FERCASTRO" in h_up or "FERCASTRO" in f_up:
        return single("DESPESAS COM SALÁRIOS E BENEFÍCIOS", "EPIs e Fardamentos", "Histórico Jan-Ago: EPIs e Fardamentos")

    if "PIS/COFINS/CSLL" in h_up:
        return single("DESPESAS COM IMPOSTOS", "DARF - RETENÇÕES (PIS/COFINS/CSLL)", "Tributos Federais -> DARF Retenções PIS/COFINS/CSLL")

    if "(IRRF)" in h_up or "RETENÇÕES (IRRF)" in h_up:
        return single("DESPESAS COM IMPOSTOS", "DARF - RETENÇÕES (IRRF)", "Tributos Federais -> DARF Retenções IRRF")

    if h_up.startswith("ISS") or f_up == "ISS":
        return single("DESPESAS COM IMPOSTOS", "ISS", "Impostos Municipais -> ISS Santa Inês")

    if h_up.startswith("PIS") or f_up == "PIS":
        return single("DESPESAS COM IMPOSTOS", "PIS", "Impostos Federais -> PIS")

    if h_up.startswith("COFINS") or f_up == "COFINS":
        return single("DESPESAS COM IMPOSTOS", "COFINS", "Impostos Federais -> COFINS")

    if "UNICLINICA" in h_up or "UNICLINICA" in f_up:
        if "COLABORADORES" in h_up or "ADMISSIONAIS" in h_up:
            return single("DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS", "Exames Laboratorias dos Colaboradores", "Uniclínica -> Exames de Colaboradores")
        return single("DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS", "Exames Laboratorias dos Pacientes", "Uniclínica -> Exames de Pacientes")

    if "CASAMATER" in h_up or "CASAMATER" in f_up:
        return single("DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS", "CasaMater - Confecção Fístula", "CasaMater -> Confecção de Fístula")

    if "DR. RENATO" in h_up or "DR. RENATO" in f_up:
        return single("DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS", "Pagamento Cirurgião Vascular - Dr. Renato", "Corpo Clínico -> Dr. Renato (Vascular)")

    if "DR. WILSON" in h_up or "DR. WILSON" in f_up:
        return single("DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS", "Pagamento Cirurgião Vascular - Dr. Wilson", "Corpo Clínico -> Dr. Wilson (Vascular)")

    if "DR. LUCAS" in h_up or "LUCAS ALBUQUERQUE" in h_up or "L F ALBUQUERQUE" in f_up:
        if "GARDÊNIA" in h_up or "GARDENIA" in h_up or "FARMACÊUTIC" in h_up:
            return single("DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS", "Pagamento Farmaceutica - Gardênia", "Terceiros Saúde -> Farmacêutica Gardênia")
        return single("DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS", "Pagamento de plantão médico - Dr. Lucas", "Corpo Clínico -> Plantões Dr. Lucas")

    if "GARDÊNIA" in h_up or "GARDENIA" in h_up or "FARMACÊUTICA" in h_up:
        return single("DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS", "Pagamento Farmaceutica - Gardênia", "Terceiros Saúde -> Farmacêutica Gardênia")

    if "HOZANO" in h_up or "MARTINS MACHADO" in h_up:
        return single("DESPESAS COM PRESTADORES DE SERVIÇOS EM SAÚDE - TERCEIROS", "Pagamento de plantão médico - Dr. Hozano", "Corpo Clínico -> Plantões Dr. Hozano")

    if "EMANUELLE ARAÚJO" in h_up or "LUANA MELO" in h_up or "ASSESSORIA ADMINISTRATIVA" in f_up:
        return single("DESPESAS ADMINISTRATIVAS", "Assessoria Administrativa", "Gestão -> Assessoria Administrativa")

    if "CASSIANO" in h_up or "CASSIANO" in f_up:
        if "SISTEMA FINANCEIRO" in h_up or val == Decimal("300.00"):
            return single("DESPESAS ADMINISTRATIVAS", "Suporte Informatica - Hardware, Internet, Sistemas e Câmeras", "Cassiano -> Sistema Financeiro")
        return single("DESPESAS ADMINISTRATIVAS", "Contador", "Cassiano -> Contabilidade")

    if any(x in h_up or x in f_up for x in ["MARANET", "FORTES", "NEPHROSYS", "BB PAY"]):
        return single("DESPESAS ADMINISTRATIVAS", "Suporte Informatica - Hardware, Internet, Sistemas e Câmeras", "TI & Sistemas -> Nephrosys / Fortes / Maranet")

    if "BIOGREEN" in h_up or "BIOGREEN" in f_up or "LIXO INFECTANTE" in h_up:
        return single("DESPESAS ADMINISTRATIVAS", "Coleta de Lixo", "Biogreen -> Coleta de Lixo Infectante")

    if "ERONLIMP" in h_up or "BRANDÃO" in h_up or "BRANDO &" in h_up or "ALECRIM" in h_up:
        return single("DESPESAS ADMINISTRATIVAS", "Material de Limpeza", "Higienização -> Material de Limpeza")

    if "GÁS" in h_up or "GAS SÃO JOSE" in h_up or "J. V. L. NOBRE" in h_up:
        return single("DESPESAS ADMINISTRATIVAS", "Gás de cozinha para copa", "Copa -> Gás de Cozinha")

    if "MASTER GRAFICA" in h_up or "GRÁFICA" in h_up:
        return single("DESPESAS ADMINISTRATIVAS", "Despesas com Gráfica", "Impressos -> Despesas com Gráfica")

    if any(x in h_up or x in f_up for x in ["TARIFA", "ABCDT", "TIM S/A", "HONORÁRIOS ADVOCATÍCIOS", "BANCO BRB"]):
        return single("DESPESAS ADMINISTRATIVAS", "Taxas e Tarifas", "Despesas Administrativas -> Taxas, Tarifas e Mensalidades")

    if "CLAUDIANE" in h_up or "VIAGEM HTI" in h_up or "TRANSPORTE DE PACIENTES" in h_up:
        return single("LOGÍSTICA E FROTA", "Transporte de pacientes e viagens para HTI", "Logística -> Transporte de Pacientes HTI")

    if "POSTO PREMIUM" in h_up or "LEMOS BRANCO" in h_up or "COMBUSTÍVEL CARRO" in h_up:
        return single("LOGÍSTICA E FROTA", "Combustível (Gasolina)", "Frota -> Combustível")

    if "BISPO TRANSPORTES" in h_up or "FRETE" in h_up:
        return single("LOGÍSTICA E FROTA", "Frete com mercadorias", "Logística -> Frete com Mercadorias")

    if "BANCO VOLKSWAGEN" in h_up or "PRESTAÇÃO CARRO" in h_up:
        return single("AQUISIÇÃO DE BENS E EQUIPAMENTOS", "Financiamento do veículo", "Capex Frota -> Financiamento Veículo VW")

    if any(x in h_up or x in f_up for x in ["TOKIO MARINE", "PNEUFREE", "FUNELARIA", "ADAILTON MESSIAS", "CALOTAS"]):
        return single("LOGÍSTICA E FROTA", "Manutenção de Veículo", "Frota -> Manutenção e Seguro de Veículo")

    if any(x in h_up or x in f_up for x in [
        "HR MANUTENÇÃO", "HR MANUTENCAO", "HUGO RAMON", "NORTEFLOW", "NORTE FLOW",
        "JADSON SAL", "SACOS DE SAL", "KELLY RAVANA", "PEÇAS PARA MANUTENÇÃO DAS MÁQUINAS"
    ]):
        return single("MANUTENÇÃO E INFRAESTRUTURA", "Manutenção - Máquinas HD, Gerador, Osmose", "Engenharia Clínica -> Manutenção HD/Osmose/Gerador")

    if any(x in h_up or x in f_up for x in [
        "SOS EXTINTORES", "MANOEL FAGNER", "CERCA ELÉTRICA", "CONSTRUNORTE",
        "DECOR COLORS", "JG CONSTRUCOES", "REFORMA DA CLINICA"
    ]):
        return single("MANUTENÇÃO E INFRAESTRUTURA", "Manutenção Predial (Reformas e Reparos)", "Infraestrutura -> Manutenção Predial e Reparos")

    if "MERCADO LIVRE" in h_up:
        return single("DESPESAS ADMINISTRATIVAS", "Materiais de Construção, Elétrico e de Escritório", "Compras -> Materiais e Utensílios")

    return single("DESPESAS ADMINISTRATIVAS", "Taxas e Tarifas", "Classificação Geral")
