"""Motor de regras do Edifício Aura.

As regras ficam em config.json. O texto oficial delas (para o site e para os vídeos)
é gerado por regras_texto() e gravado em docs/REGRAS_ATUAIS.md a cada ciclo.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
import shutil
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

PASTA = Path(__file__).resolve().parent
CONFIG = json.loads((PASTA / "config.json").read_text(encoding="utf-8"))
ARQ_ESTADO = PASTA / "dados" / "estado.json"

RE_AURA = re.compile(r"(?<![a-z0-9])aura(?![a-z0-9])\s*#?\s*(\d{1,2})?", re.IGNORECASE)
RE_USUARIO = re.compile(r"^[a-z0-9._]{1,30}$")


# ---------------------------------------------------------------- utilidades
def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def de_iso(txt: str) -> datetime:
    # aceita "2026-11-25T14:00:00+0000" (formato do Instagram) e ISO normal
    txt = txt.replace("Z", "+00:00")
    if re.search(r"[+-]\d{4}$", txt):
        txt = txt[:-2] + ":" + txt[-2:]
    dt = datetime.fromisoformat(txt)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- relógio do aluguel
# O aluguel não corre durante a pausa noturna (horário de Brasília por padrão).
FUSO = timezone(timedelta(hours=CONFIG.get("fuso_horas", -3)))
PAUSA_INI, PAUSA_FIM = CONFIG.get("pausa_noturna", [0, 8])


def _na_pausa(t: datetime) -> bool:
    h = t.astimezone(FUSO).hour
    return PAUSA_INI <= h < PAUSA_FIM if PAUSA_INI < PAUSA_FIM else False


def _proxima_borda(t: datetime) -> datetime:
    """Próximo instante em que a pausa começa ou termina."""
    local = t.astimezone(FUSO)
    dia = local.replace(minute=0, second=0, microsecond=0)
    candidatos = []
    for d in (0, 1):
        for h in (PAUSA_INI, PAUSA_FIM):
            c = (dia.replace(hour=0) + timedelta(days=d, hours=h))
            if c > local:
                candidatos.append(c)
    return min(candidatos).astimezone(timezone.utc)


def avancar(inicio: datetime, horas: float) -> datetime:
    """Soma horas de aluguel a partir de 'inicio', pulando a pausa noturna."""
    if PAUSA_INI >= PAUSA_FIM:
        return inicio + timedelta(hours=horas)
    t, resta = inicio, timedelta(hours=horas)
    while resta > timedelta(0):
        borda = _proxima_borda(t)
        if _na_pausa(t):
            t = borda
            continue
        passo = min(resta, borda - t)
        t += passo
        resta -= passo
    return t


def horas_cobradas(a: datetime, b: datetime) -> float:
    """Quantas horas de aluguel correm entre a e b (descontando a pausa)."""
    if b <= a:
        return 0.0
    if PAUSA_INI >= PAUSA_FIM:
        return (b - a).total_seconds() / 3600
    t, total = a, timedelta(0)
    while t < b:
        borda = min(_proxima_borda(t), b)
        if not _na_pausa(t):
            total += borda - t
        t = borda
    return total.total_seconds() / 3600


def momento_despejo(m: dict) -> datetime:
    """Quando o saldo acaba E a carência (tempo de 'ATRASADO!') também acaba."""
    return avancar(de_iso(m["pago_ate"]), CONFIG.get("carencia_horas", 0))


def mes_de(t: datetime) -> str:
    return t.astimezone(FUSO).strftime("%Y-%m")


def valor_aura(quando: datetime) -> float:
    """Horas pagas por 1 AURA no mês do comentário (reajuste todo dia 1).
    Vale o último reajuste definido até aquele mês."""
    tabela = CONFIG.get("reajustes", {})
    meses = sorted(k for k in tabela if k <= mes_de(quando))
    return tabela[meses[-1]] if meses else CONFIG["horas_por_aura"]


def inicio_do_mes(t: datetime) -> datetime:
    local = t.astimezone(FUSO)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def proximo_mes(t: datetime) -> datetime:
    local = inicio_do_mes(t).astimezone(FUSO)
    ano, mes = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return local.replace(year=ano, month=mes).astimezone(timezone.utc)


def personagem_padrao(usuario: str) -> int:
    return zlib.crc32(usuario.encode()) % CONFIG["personagens"] + 1


def ler_comentario(texto: str):
    """Retorna (tem_aura, numero_personagem_ou_None)."""
    m = RE_AURA.search(texto or "")
    if not m:
        return False, None
    num = int(m.group(1)) if m.group(1) else None
    if num is not None and not 1 <= num <= CONFIG["personagens"]:
        num = None
    return True, num


# região pelo nome da região, pelo estado (nome ou sigla) ou pelo DF/Brasília — divisão oficial do IBGE
_REGIOES_TXT = {
    "N": "norte | acre ac | amapa ap | amazonas am | para pa | rondonia ro | roraima rr | tocantins to",
    "NE": "nordeste ne | alagoas al | bahia ba | ceara ce | maranhao ma | paraiba pb | pernambuco pe | piaui pi"
          " | rio grande do norte rn | sergipe",
    "CO": "centro oeste centrooeste co | goias go | mato grosso mt | mato grosso do sul ms | distrito federal df | brasilia",
    "SE": "sudeste se | espirito santo es | minas gerais minas mg | rio de janeiro rio rj | sao paulo sp",
    "S": "sul | parana pr | rio grande do sul rs | santa catarina sc",
}
# SE = Sudeste (já era assim); Sergipe vale só pelo nome
NOMES_REGIAO = {}
for _cod, _txt in _REGIOES_TXT.items():
    for _grupo in _txt.split("|"):
        _ws = _grupo.split()
        # cada grupo: nome por extenso (pode ter várias palavras) + sigla/apelidos de 1 palavra no fim
        _sig = []
        while len(_ws) > 1 and len(_ws[-1]) == 2:   # siglas ficam no fim do grupo
            _sig.append(_ws.pop())
        if len(_ws) == 1 and len(_ws[0]) == 2:
            _sig, _ws = _ws, []
        _nome = " ".join(_ws)
        for chave in ([_nome] if _nome else []) + _sig:
            NOMES_REGIAO[chave] = _cod
NOMES_REGIAO.update({"minas": "SE", "rio": "SE", "centrooeste": "CO", "brasilia": "CO"})
NOMES_REGIAO.pop("minas gerais minas", None); NOMES_REGIAO["minas gerais"] = "SE"
NOMES_REGIAO.pop("rio de janeiro rio", None); NOMES_REGIAO["rio de janeiro"] = "SE"
NOMES_REGIAO.pop("centro oeste centrooeste", None); NOMES_REGIAO["centro oeste"] = "CO"
# palavras que também são palavras comuns: só valem se NADA de texto vier depois (ex.: "AURA PA" sim, "aura para todos" não)
_CURTAS = {k for k in NOMES_REGIAO if len(k) == 2} | {"para", "rio", "minas"}
_CHAVES = sorted(NOMES_REGIAO, key=len, reverse=True)
_RE_AURA = re.compile(r"(?<![a-z0-9])aura(?![a-z0-9])\s*#?\s*(?:\d{1,2}(?!\d))?\s*(.*)$", re.S)


def _sem_acento(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def ler_regiao(texto: str):
    """'AURA NE', 'aura 7 sul', 'AURA Centro-Oeste', 'AURA BA', 'AURA DF', 'aura são paulo' -> N, NE, CO, SE, S ou None.
    Siglas e palavras comuns (pa, se, rio, para...) só valem se não houver mais texto depois,
    para 'aura se liga...' ou 'aura para todos' não mudarem ninguém."""
    m = _RE_AURA.search(_sem_acento(texto))
    if not m:
        return None
    resto = re.sub(r"[-_/.,!]+", " ", m.group(1)).strip()
    for chave in _CHAVES:
        if resto == chave or (resto.startswith(chave) and not resto[len(chave)].isalpha()):
            depois = resto[len(chave):]
            if chave in _CURTAS and re.search(r"[a-z]", depois):
                return None
            return NOMES_REGIAO[chave]
    return None


# ---------------------------------------------------------------- estado
def estado_vazio() -> dict:
    return {"moradores": {}, "comentarios_vistos": [], "eventos": [], "top1": None}


def carregar(caminho: Path = ARQ_ESTADO) -> dict:
    if not caminho.exists():
        return estado_vazio()
    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar(estado: dict, caminho: Path = ARQ_ESTADO) -> None:
    """Grava de forma segura: escreve num arquivo temporário e só então troca.
    Mantém uma cópia do estado anterior em estado.bak.json."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    estado["comentarios_vistos"] = estado["comentarios_vistos"][-50000:]
    estado["eventos"] = estado["eventos"][-2000:]
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    if caminho.exists():
        shutil.copyfile(caminho, caminho.with_name("estado.bak.json"))
    os.replace(tmp, caminho)


def evento(estado: dict, tipo: str, quando: datetime, **dados) -> None:
    estado["eventos"].append({"tipo": tipo, "quando": iso(quando), **dados})


# ---------------------------------------------------------------- regras
def regiao_automatica(estado: dict, usuario: str) -> str:
    """Região de quem não escolheu: a que tem menos moradores (empate: espalha pelo @)."""
    regs = list(CONFIG.get("regioes", {}) or ["SE"])
    conta = {r: 0 for r in regs}
    for u, m in estado["moradores"].items():
        if u != usuario and m.get("status") != "despejado" and m.get("regiao") in conta:
            conta[m["regiao"]] += 1
    menor = min(conta.values())
    empatadas = [r for r in regs if conta[r] == menor]
    return empatadas[zlib.crc32(usuario.encode()) % len(empatadas)]


def garantir_regioes(estado: dict) -> None:
    """Moradores antigos sem região (da época da Capital Aura) ganham uma região automática."""
    for u, m in sorted(estado["moradores"].items(), key=lambda x: x[1].get("entrou_em", "")):
        if not m.get("regiao"):
            m["regiao"] = regiao_automatica(estado, u)
            m["regiao_auto"] = True


def processar_comentario(estado: dict, cid: str, usuario: str, texto: str, quando: datetime) -> str:
    """Aplica um comentário. Retorna o que aconteceu (para log/testes)."""
    vistos = estado.setdefault("_vistos_set", set(estado["comentarios_vistos"]))
    if cid in vistos:
        return "repetido"
    vistos.add(cid)
    estado["comentarios_vistos"].append(cid)

    usuario = (usuario or "").strip().lstrip("@").lower()
    if not RE_USUARIO.match(usuario):
        return "usuario_invalido"
    tem_aura, num = ler_comentario(texto)
    if not tem_aura:
        return "sem_aura"

    m = estado["moradores"].get(usuario)
    novo = m is None
    if m is not None:   # guarda o último comentário AURA (a DM com a senha responde a ele, até 7 dias depois)
        m["ultimo_cid"], m["ultimo_cid_em"] = cid, iso(quando)
    if novo:
        m = {
            "personagem": num or personagem_padrao(usuario),
            "pago_ate": iso(quando),
            "auras": [],
            "status": "ativo",
            "entrou_em": iso(quando),
            "ultimo_aura": None,
            "ultimo_cid": cid,
            "ultimo_cid_em": iso(quando),
        }
        estado["moradores"][usuario] = m
    reg = ler_regiao(texto)
    if reg and reg != m.get("regiao"):
        if not novo:
            evento(estado, "mudou_regiao", quando, usuario=usuario, regiao=reg)
        m["regiao"] = reg
        m.pop("regiao_auto", None)
    elif not m.get("regiao"):
        m["regiao"] = regiao_automatica(estado, usuario)   # quem não escolhe entra na região mais vazia
        m["regiao_auto"] = True
    if not novo and num:
        if num != m["personagem"]:
            evento(estado, "trocou_personagem", quando, usuario=usuario, personagem=num)
        m["personagem"] = num

    # limite de 1 AURA contado por intervalo
    if m["ultimo_aura"]:
        desde = quando - de_iso(m["ultimo_aura"])
        if desde < timedelta(minutes=CONFIG["intervalo_minimo_entre_auras_min"]) and not novo:
            return "personagem" if num else "cedo_demais"

    voltou = m["status"] == "despejado"
    base = max(de_iso(m["pago_ate"]), quando)
    horas = valor_aura(quando) if not novo else CONFIG["saldo_inicial_horas"]
    teto = avancar(quando, CONFIG["saldo_maximo_horas"])
    m["pago_ate"] = iso(min(avancar(base, horas), teto))
    m["auras"].append(iso(quando))
    m["auras"] = m["auras"][-500:]
    m["ultimo_aura"] = iso(quando)
    m["total_auras"] = m.get("total_auras", len(m["auras"]) - 1) + 1   # nunca é cortado (dá Brasas e móveis)
    m["status"] = "ativo"
    import comunidade
    if comunidade.conferir_missao(m, texto, quando):     # missão do dia (+Brasas, 1x por dia)
        evento(estado, "missao", quando, usuario=usuario)

    if novo:
        evento(estado, "novo_morador", quando, usuario=usuario)
        if CONFIG.get("despejo_so_quando_lota"):
            abrir_vaga(estado, usuario, quando)
        return "novo"
    if voltou:
        evento(estado, "voltou", quando, usuario=usuario)
        return "voltou"
    return "pagou"


def creditar_curtidas(estado: dict, curtidas: list[dict], agora: datetime) -> int:
    """Curtidas de visitantes no quarto (vindas do banco) pagam horas de aluguel do dono.
    Cada curtida conta 1 vez (chave dono|visitante|dia); o banco já marca paga=false acima do limite do dia."""
    horas = CONFIG.get("horas_por_curtida", 0)
    if not horas:
        return 0
    vistas = estado.setdefault("curtidas_vistas", [])
    ja = set(vistas)
    n = 0
    for c in curtidas:
        chave = f"{c.get('dono')}|{c.get('visitante')}|{c.get('dia')}"
        if chave in ja or not c.get("paga", True):
            continue
        ja.add(chave); vistas.append(chave)
        m = estado["moradores"].get(str(c.get("dono", "")).lower())
        if not m or m.get("status") == "despejado":
            continue
        quando = min(de_iso(c["quando"]), agora) if c.get("quando") else agora
        base = max(de_iso(m["pago_ate"]), quando)
        teto = avancar(quando, CONFIG["saldo_maximo_horas"])
        m["pago_ate"] = iso(min(avancar(base, horas), teto))
        m["curtidas"] = m.get("curtidas", 0) + 1
        n += 1
    estado["curtidas_vistas"] = vistas[-20000:]
    return n


def na_fila(m: dict, agora: datetime) -> bool:
    """Passou do crédito E da tolerância: perde o apê para o próximo vizinho novo."""
    return m["status"] == "ativo" and momento_despejo(m) <= agora


def abrir_vaga(estado: dict, novo: str, agora: datetime) -> str | None:
    """Chegou vizinho novo: sai o atrasado mais antigo (de preferência da mesma região). Retorna quem saiu."""
    fila = [(u, m) for u, m in estado["moradores"].items() if u != novo and na_fila(m, agora)]
    if not fila:
        return None
    reg = estado["moradores"][novo].get("regiao")
    mesma = [x for x in fila if x[1].get("regiao") == reg]
    u, m = min(mesma or fila, key=lambda x: momento_despejo(x[1]))
    m["status"] = "despejado"
    m["despejado_em"] = iso(agora)
    evento(estado, "despejo", agora, usuario=u, motivo="chegou vizinho novo", entrou=novo)
    return u


def atualizar(estado: dict, agora: datetime) -> list[str]:
    """Despeja quem ficou sem saldo e recalcula o top 1. Retorna os despejados.
    Com "despejo_so_quando_lota", ninguém sai só pelo tempo: quem passou da tolerância fica "na fila"
    e só perde o apê quando chega um vizinho novo (ver abrir_vaga)."""
    despejados = []
    for u, m in estado["moradores"].items():
        if CONFIG.get("despejo_so_quando_lota"):
            break
        if m["status"] == "ativo" and momento_despejo(m) <= agora:
            m["status"] = "despejado"
            m["despejado_em"] = iso(agora)
            evento(estado, "despejo", agora, usuario=u)
            despejados.append(u)
    rk = ranking(estado, agora)
    top = rk[0][0] if rk else None
    if top != estado.get("top1"):
        if top:
            evento(estado, "novo_top1", agora, usuario=top)
        estado["top1"] = top
    return despejados


def auras_recentes(m: dict, agora: datetime) -> int:
    if CONFIG.get("ranking") == "mes":
        limite = inicio_do_mes(agora)  # ranking recomeça todo dia 1
    else:
        limite = agora - timedelta(days=CONFIG["ranking_janela_dias"])
    return sum(1 for a in m["auras"] if de_iso(a) >= limite)


def ranking(estado: dict, agora: datetime) -> list[tuple[str, dict, int]]:
    ativos = [(u, m, auras_recentes(m, agora)) for u, m in estado["moradores"].items() if m["status"] == "ativo"]
    ativos.sort(key=lambda t: (-t[2], -de_iso(t[1]["pago_ate"]).timestamp(), t[1]["entrou_em"], t[0]))
    return ativos


def ranking_semana(estado: dict, agora: datetime) -> list[dict]:
    """Quem mais fez AURA nos últimos 7 dias (só moradores ativos)."""
    desde = agora - timedelta(days=7)
    lista = []
    for u, m in estado["moradores"].items():
        if m["status"] != "ativo":
            continue
        n = sum(1 for a in m["auras"] if de_iso(a) >= desde)
        if n:
            lista.append((n, de_iso(m["pago_ate"]).timestamp(), u, m))
    lista.sort(key=lambda t: (-t[0], -t[1], t[2]))
    return [{"u": u, "p": m["personagem"], "r": m.get("regiao"), "n": n} for n, _, u, m in lista]


# ---------------------------------------------------------------- exportação para o site
def moveis_de(total_auras: int) -> dict:
    """Móveis que chegam sozinhos por marcos de AURAs (nível 0 = ainda não tem)."""
    return {peca: sum(1 for x in marcos if total_auras >= x)
            for peca, marcos in CONFIG.get("moveis_marcos", {}).items()}


def proximo_movel(total_auras: int):
    """O próximo móvel a chegar: (peça, nível, quantos AURAs faltam) ou None."""
    melhor = None
    for peca, marcos in CONFIG.get("moveis_marcos", {}).items():
        for i, x in enumerate(marcos):
            if x > total_auras:
                if melhor is None or x < melhor[3]:
                    melhor = (peca, i + 1, x - total_auras, x)
                break
    return melhor[:3] if melhor else None


def bairro_do_bloco(n: int) -> str:
    """Bloco 1 fica no bairro mais alto da cidade; os blocos novos vão para a Vila."""
    for nome, ate in CONFIG.get("bairros", []):
        if not ate or n <= ate:
            return nome
    return "Vila"


def exportar(estado: dict, agora: datetime, pasta_site: Path, views: dict | None = None) -> dict:
    import comunidade
    views = views or {}   # visualizações de cada quarto (vêm do banco; aparecem como 👁 no nome)
    rk = ranking(estado, agora)
    alerta = CONFIG["alerta_quando_faltar_horas"]
    teto = CONFIG["saldo_maximo_horas"]

    def ficha(u, m, n):
        pago = de_iso(m["pago_ate"])
        horas = horas_cobradas(agora, pago)
        tot = m.get("total_auras", len(m["auras"]))
        prox = proximo_movel(tot)
        return {"u": u, "p": m["personagem"], "r": m.get("regiao"), "auras": n, **({"v": views[u]} if views.get(u) else {}),
                "horas": round(horas, 2),
                "alerta": horas <= alerta,
                "atrasado": pago <= agora,
                **({"fila": True} if CONFIG.get("despejo_so_quando_lota") and momento_despejo(m) <= agora else {}),
                "tot": tot, "br": comunidade.brasas(m),
                **({"missao": True} if m.get("missao_dia") == comunidade.dia_local(agora).isoformat() else {}),
                "mv": moveis_de(tot), "prox": list(prox) if prox else None,
                "desde": m["entrou_em"][:10]}

    vip = ficha(*rk[0]) if rk else None
    por_bloco = CONFIG["andares_por_bloco"] * CONFIG["aptos_por_andar"]

    bairro_de_u, cargos = {}, {}

    def montar_cidade(nome, lista, cod=""):
        """Cada região é uma cidade: o 1º do ranking da região mora na cobertura, o resto enche os blocos."""
        resto = lista[1:]
        n_blocos = max(1, -(-len(resto) // por_bloco))
        blocos = []
        for b in range(n_blocos):
            fatia = resto[b * por_bloco:(b + 1) * por_bloco]
            aptos = [ficha(*t) for t in fatia] + [None] * (por_bloco - len(fatia))
            info = comunidade.info_bloco(fatia, agora, b + 1)
            for t in fatia:
                bairro_de_u[t[0]] = bairro_do_bloco(b + 1)
            if info["sindico"]:
                cargos[info["sindico"]] = f"{cod}-{b + 1}"
            blocos.append({"numero": b + 1, "bairro": bairro_do_bloco(b + 1), "aptos": aptos, "info": info})
        return {"nome": nome, "vip": ficha(*lista[0]) if lista else None, "total_moradores": len(lista),
                "total_blocos": n_blocos if lista else 0, "blocos": blocos}

    cidades = {}
    for cod, nome in CONFIG.get("regioes", {}).items():
        cidades[cod] = montar_cidade(nome, [t for t in rk if t[1].get("regiao") == cod], cod)
    n_blocos = max(1, sum(c["total_blocos"] for c in cidades.values()))

    # com despejo só quando lota, o relógio mostra quando o próximo morador entra na fila (quem já está na fila não conta)
    proximo = min((momento_despejo(m) for _, m, _ in rk if momento_despejo(m) > agora), default=None)
    recentes = agora - timedelta(hours=1)
    pagaram = sorted({e["usuario"] for e in estado["eventos"]
                      if e["tipo"] in ("pagou", "novo_morador", "voltou") and de_iso(e["quando"]) >= recentes})
    pagaram += sorted({u for u, m in estado["moradores"].items()
                       if m["ultimo_aura"] and de_iso(m["ultimo_aura"]) >= recentes} - set(pagaram))
    limite_praca = agora - timedelta(days=CONFIG.get("pracinha_dias", 30))
    pracinha = sorted(
        ({"u": u, "p": m["personagem"], "quando": m["despejado_em"]}
         for u, m in estado["moradores"].items()
         if m["status"] == "despejado" and de_iso(m["despejado_em"]) >= limite_praca),
        key=lambda d: d["quando"], reverse=True)
    despejados = pracinha[:20]

    # Praça: quem chegou nas últimas 24h + quem está "ativo agora" (comentou AURA nas últimas 3h).
    # Quando o banco tiver tempo real, o site soma quem está ONLINE de verdade.
    novos_desde, ativos_desde = agora - timedelta(hours=24), agora - timedelta(hours=3)
    praca = []
    for u, m in estado["moradores"].items():
        if m["status"] == "despejado":
            continue
        novo = de_iso(m["entrou_em"]) >= novos_desde
        ativo = bool(m["ultimo_aura"]) and de_iso(m["ultimo_aura"]) >= ativos_desde
        if novo or ativo:
            praca.append({"u": u, "p": m["personagem"], "r": m.get("regiao"), "novo": novo, **({"v": views[u]} if views.get(u) else {}),
                          "t": max(m["entrou_em"], m["ultimo_aura"] or "")})
    praca.sort(key=lambda x: x["t"], reverse=True)
    praca = [{k: v for k, v in x.items() if k != "t"} for x in praca[:40]]
    estado["cargos"] = cargos

    niveis = CONFIG.get("regiao_niveis", [1, 10, 50])
    regioes = {}
    for cod, nome in CONFIG.get("regioes", {}).items():
        gente = [(u, n) for u, m, n in rk if m.get("regiao") == cod]
        regioes[cod] = {"nome": nome, "moradores": len(gente), "auras_mes": sum(n for _, n in gente),
                                 "nivel": sum(1 for x in niveis if len(gente) >= x) + 1}
    campea = max(regioes, key=lambda k: regioes[k]["auras_mes"], default=None)
    if campea and not regioes[campea]["auras_mes"]:
        campea = None

    dados = {
        "atualizado_em": iso(agora),
        "regioes": regioes,
        "regiao_campea": campea,
        "proximo_despejo": iso(proximo) if proximo else None,
        "despejo_so_quando_lota": bool(CONFIG.get("despejo_so_quando_lota")),
        "na_fila": sum(1 for _, m, _ in rk if momento_despejo(m) <= agora),
        "total_moradores": len(rk),
        "total_blocos": n_blocos,
        "cidades": cidades,
        "saldo_maximo_horas": CONFIG.get("barra_cheia_horas", teto),
        "regras_dias_gratis": round(CONFIG["saldo_inicial_horas"] / 24),
        "praca": praca,
        "disputa_bairros": comunidade.disputa_bairros(estado, agora, bairro_de_u),
        "zeladores": comunidade.zeladores(estado, agora),
        "missao_hoje": dict(zip(("tipo", "texto"), comunidade.missao_de(comunidade.dia_local(agora))),
                            bonus=comunidade.cfg("bonus_missao", comunidade.BONUS_MISSAO)),
        "sindico_geral": rk[0][0] if rk else None,
        "vip": vip,
        "ranking": [{"u": u, "p": m["personagem"], "r": m.get("regiao"), "n": n} for u, m, n in rk[:100]],
        "ranking_semana": ranking_semana(estado, agora)[:100],
        "pagaram_ultima_hora": pagaram[:50],
        "despejados_recentes": despejados,
        "pracinha": pracinha[:200],
        "total_pracinha": len(pracinha),
        "valor_aura": valor_aura(agora),
        "proximo_reajuste": iso(proximo_mes(agora)),
        "regras": regras_texto(agora),
    }
    pasta_site.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(dados, ensure_ascii=False)
    (pasta_site / "dados.json").write_text(txt, encoding="utf-8")
    (pasta_site / "dados.js").write_text("window.DADOS=" + txt + ";\n", encoding="utf-8")
    return dados


# ---------------------------------------------------------------- texto oficial das regras
def _tempo(h: float) -> str:
    if h >= 24 and h % 24 == 0:
        d = int(h // 24)
        return f"{d} dia" + ("s" if d > 1 else "")
    return f"{h:g}h"


def regras_texto(agora: datetime | None = None) -> list[str]:
    """As regras em linguagem simples, montadas a partir do config.json.
    É o mesmo texto do site e do documento usado nos vídeos."""
    agora = agora or agora_utc()
    c = CONFIG
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]
    mes = meses[agora.astimezone(FUSO).month - 1]
    intervalo = c["intervalo_minimo_entre_auras_min"] / 60
    r = [
        "Comente AURA em qualquer post do @comenteaura e vire morador do Edifício Aura.",
        f"Inquilino novo tem {_tempo(c['saldo_inicial_horas'])} grátis antes de começar a pagar aluguel.",
        f"O aluguel é pago comentando AURA: em {mes}, cada AURA paga {_tempo(valor_aura(agora))} de aluguel.",
        f"Vale 1 AURA a cada {intervalo:g} hora{'s' if intervalo != 1 else ''} por pessoa. Comentar mais vezes nesse tempo não paga a mais.",
        f"Escreva AURA + um número de 1 a {c['personagens']} (ex.: AURA 7) para escolher seu personagem. Pode trocar quando quiser.",
        f"O aluguel gasta 1 dia por dia. Dá pra guardar até {_tempo(c['saldo_maximo_horas'])} de aluguel pago.",
        f"Faltando menos de {_tempo(c['alerta_quando_faltar_horas'])}, sua janela mostra VENCENDO.",
        (f"Acabou o crédito? Você fica ATRASADO, mas continua morando. Depois de {_tempo(c['carencia_horas'])} atrasado, entra na fila do despejo: "
         "só perde o apê quando chegar um vizinho novo e o prédio estiver cheio." if c.get("despejo_so_quando_lota") else
         f"Acabou o crédito? Você ainda tem {_tempo(c['carencia_horas'])} de tolerância como ATRASADO antes do despejo."),
        f"Despejado vai para a Pracinha e fica lá por até {c.get('pracinha_dias', 30)} dias. Comentou AURA, volta pro prédio na hora.",
        "Ranking do mês: quem faz mais AURAs no mês mora mais alto. O 1º lugar ganha a Cobertura VIP e o outdoor.",
        "Todo dia 1 tem reajuste: o valor do AURA pode mudar e o ranking recomeça. O crédito que você já tem não muda.",
        f"Cada bloco tem {c['andares_por_bloco'] * c['aptos_por_andar']} apartamentos. Lotou, nasce um bloco novo.",
    ]
    if c.get("moveis_marcos"):
        r.append(f"Seu apê começa vazio. Cada AURA também dá {c.get('brasas_por_aura', 10)} Brasas 🔥 e, conforme você "
                 "comenta, chegam móveis e decoração (cama, tapete, sofá, planta, luminária, cortina, quadro). Se for despejado, seus móveis vão no caminhão e voltam com você.")
    if c.get("regioes"):
        r.append("Escolha sua região do Brasil Aura comentando AURA + a região ou o seu estado (ex.: AURA NE, AURA SUL, "
                 "AURA BAHIA, AURA SP, AURA DF). Quem não escolher entra sozinho na região com menos moradores e pode trocar quando quiser. A região com mais AURAs no mês ganha a chama.")
    r.append("Cada bloco sobe de nível com mais moradores (Kitnet, Residencial, Condomínio, Torre de luxo) e libera melhorias "
             "(portaria, elevador, piscina, academia, heliponto) com os AURAs de todos os vizinhos. Toda semana tem mutirão: "
             "batendo a meta de AURAs do bloco, sai a obra da semana.")
    r.append("O 1º do bloco no mês é o síndico e o 2º é o subsíndico (se o síndico sumir 48h, o sub assume); o síndico escolhe o "
             "lema do bloco numa lista pronta. O Top 1 do Brasil é o Síndico Geral. Toda semana saem os zeladores: mais pontual, "
             "quem mais ajudou no mutirão e o morador veterano.")
    r.append(f"Todo dia tem uma missão simples, feita comentando AURA: cumprindo, você ganha {c.get('bonus_missao', 20)} Brasas a mais (1 vez por dia).")
    if c.get("horas_por_curtida") and c.get("banco_ligado"):   # só aparece quando a lojinha/senha estiver no ar
        r.append(f"Quem entra com @ e senha pode visitar quartos e curtir: cada curtida no seu quarto paga "
                 f"{_tempo(c['horas_por_curtida'])} de aluguel (até {_tempo(c['horas_por_curtida'] * c.get('curtidas_pagas_max_dia', 18))} por dia), "
                 f"e quem curte ganha {c.get('brasas_por_visita', 1)} Brasa por curtida (até {c.get('visitas_brasas_max_dia', 10)} por dia). "
                 "Vale 1 curtida por quarto por dia.")
    b = c.get("bairros")
    if b and len(b) >= 3:
        r.append(f"A Cidade Aura tem bairros: os blocos 1 a {b[0][1]} ficam no {b[0][0]}, lá no alto, "
                 f"os blocos até o {b[1][1]} no {b[1][0]} e os seguintes na {b[2][0]}. "
                 "Quanto mais AURA, mais perto do alto você mora.")
    return r


def gravar_regras_md(destino: Path, agora: datetime | None = None) -> None:
    agora = agora or agora_utc()
    linhas = ["# Edifício Aura — regras atuais", "",
              f"_Gerado automaticamente a partir de motor/config.json em "
              f"{agora.astimezone(FUSO).strftime('%d/%m/%Y %H:%M')} (horário de Brasília)._",
              "_Use este texto nos vídeos explicativos: ele é igual ao que aparece no site._", ""]
    linhas += [f"{i}. {t}" for i, t in enumerate(regras_texto(agora), 1)]
    tabela = CONFIG.get("reajustes", {})
    if tabela:
        linhas += ["", "## Tabela de reajustes (horas por AURA)", "", "| Mês | Cada AURA paga |", "|---|---|"]
        linhas += [f"| {k} | {_tempo(v)} |" for k, v in sorted(tabela.items())]
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def apagar_pedidos(estado: dict) -> list[str]:
    """Exclusão de dados (privacidade): quem está em config "apagar_usuarios" sai do jogo.
    Os comentários antigos já lidos não voltam; se comentar AURA de novo, entra como morador novo."""
    feitos = []
    for u in [x.lower().lstrip("@") for x in CONFIG.get("apagar_usuarios", [])]:
        if u in estado["moradores"]:
            del estado["moradores"][u]
            feitos.append(u)
        for k in ("dm_enviadas", "banco", "cargos"):
            estado.get(k, {}).pop(u, None)
        estado["eventos"] = [e for e in estado["eventos"] if e.get("usuario") != u]
    return feitos


def aplicar_lote(estado: dict, comentarios: list[dict], agora: datetime) -> dict:
    """Processa comentários em ordem de horário e despeja quem venceu no meio do caminho."""
    contagem: dict[str, int] = {}
    garantir_regioes(estado)
    for c in sorted(comentarios, key=lambda c: c["timestamp"]):
        quando = de_iso(c["timestamp"])
        atualizar(estado, quando)
        r = processar_comentario(estado, str(c["id"]), c.get("username", ""), c.get("text", ""), quando)
        contagem[r] = contagem.get(r, 0) + 1
    atualizar(estado, agora)
    estado.pop("_vistos_set", None)
    return contagem
