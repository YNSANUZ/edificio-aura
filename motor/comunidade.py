"""Fases 4, 5 e 6 do Edifício Aura: o que é coletivo e os cargos.

- Nível do bloco: Kitnet → Residencial → Condomínio → Torre de luxo (pelo nº de moradores).
- Melhorias: portaria, elevador, piscina, academia, heliponto (pelos AURAs somados dos moradores do bloco).
- Mutirão da semana: meta de AURAs do bloco nos últimos 7 dias; batendo, o bloco ganha a obra da semana.
- Disputa entre bairros: Nobre × Centro × Vila (AURAs da semana, no Brasil todo).
- Cargos: síndico (1º do bloco no mês) e subsíndico (2º); se o síndico sumir 48h, o sub assume.
  Síndico Geral = Top 1 do Brasil. Zeladores da semana: mais pontual, mais ajudou no mutirão, veterano.
- Missão do dia: tarefa simples feita comentando; vale +Brasas uma vez por dia.
"""
from __future__ import annotations

from datetime import timedelta

import motor as M

NIVEIS = [(0, "Kitnet"), (10, "Residencial"), (20, "Condomínio"), (35, "Torre de luxo")]
MELHORIAS = [("portaria", "🚪", 50), ("elevador", "🛗", 150), ("piscina", "🏊", 300), ("academia", "🏋️", 600), ("heliponto", "🚁", 1000)]
OBRAS = ["pintura nova", "jardim na portaria", "luzes de festa", "mural na fachada", "parquinho"]
LEMAS = ["Aqui a aura não apaga 🔥", "Bloco unido jamais é despejado", "Vizinho bom comenta todo dia",
         "Do térreo à cobertura", "Aqui ninguém fica atrasado", "Aura alta, aluguel em dia",
         "O bloco mais animado do Brasil", "Chegou, comentou, morou"]
MISSOES = [
    ("aura", "Comente AURA em qualquer post hoje"),
    ("boneco", "Comente AURA + o número do seu boneco (ex.: AURA 7)"),
    ("regiao", "Comente AURA + sua região ou estado (ex.: AURA NE)"),
    ("duas", "Comente AURA 2 vezes hoje, com 3h de intervalo"),
    ("cedo", "Comente AURA antes do meio-dia"),
]
BONUS_MISSAO = 20   # Brasas


def cfg(nome, padrao):
    return M.CONFIG.get(nome, padrao)


def nivel_do_bloco(moradores: int) -> dict:
    niveis = cfg("bloco_niveis", NIVEIS)
    i = max(k for k, (minimo, _) in enumerate(niveis) if moradores >= minimo)
    prox = niveis[i + 1][0] if i + 1 < len(niveis) else None
    return {"n": i + 1, "nome": niveis[i][1], "prox": prox}


def semana(agora):
    return agora - timedelta(days=7)


def chave_semana(agora) -> int:
    return int(agora.timestamp() // (7 * 86400))


def info_bloco(fatia: list, agora, numero: int) -> dict:
    """fatia = [(u, m, auras_mes), ...] dos moradores do bloco, já na ordem do ranking."""
    desde = semana(agora)
    total = sum(m.get("total_auras", 0) for _, m, _ in fatia)
    sem = {u: sum(1 for a in m["auras"] if M.de_iso(a) >= desde) for u, m, _ in fatia}
    meta = max(cfg("mutirao_meta_min", 20), cfg("mutirao_por_morador", 10) * len(fatia))
    feito = sum(sem.values())
    obra = OBRAS[(chave_semana(agora) + numero) % len(OBRAS)]
    melhorias = [{"id": i, "e": e, "falta": max(0, x - total)} for i, e, x in cfg("melhorias", MELHORIAS)]
    # cargos: 1º e 2º do bloco no mês; síndico sumido 48h -> sub assume
    sind = sub = None
    if fatia:
        sind = fatia[0][0]
        sub = fatia[1][0] if len(fatia) > 1 else None
        sumiu = lambda m: not m.get("ultimo_aura") or agora - M.de_iso(m["ultimo_aura"]) > timedelta(hours=48)
        if sub and sumiu(fatia[0][1]) and not sumiu(fatia[1][1]):   # só troca se o sub estiver presente
            sind, sub = sub, sind
    return {"nivel": nivel_do_bloco(len(fatia)), "auras_total": total,
            "melhorias": melhorias,
            "mutirao": {"obra": obra, "meta": meta, "feito": min(feito, meta), "ok": feito >= meta},
            "sindico": sind, "sub": sub}


def disputa_bairros(estado: dict, agora, bairro_de_u: dict) -> dict:
    desde = semana(agora)
    placar = {"Bairro Nobre": 0, "Centro": 0, "Vila": 0}
    for u, b in bairro_de_u.items():
        m = estado["moradores"].get(u)
        if m and b in placar:
            placar[b] += sum(1 for a in m["auras"] if M.de_iso(a) >= desde)
    lider = max(placar, key=placar.get) if any(placar.values()) else None
    return {"placar": placar, "lider": lider}


def zeladores(estado: dict, agora) -> list[dict]:
    desde = semana(agora)
    ativos = [(u, m) for u, m in estado["moradores"].items() if m["status"] == "ativo"]
    out = []
    if not ativos:
        return out
    dias = {u: len({M.de_iso(a).astimezone(M.FUSO).date() for a in m["auras"] if M.de_iso(a) >= desde}) for u, m in ativos}
    sem = {u: sum(1 for a in m["auras"] if M.de_iso(a) >= desde) for u, m in ativos}
    u = max(dias, key=lambda k: (dias[k], sem[k]))
    if dias[u]:
        out.append({"titulo": "Mais pontual", "e": "⏰", "u": u, "p": estado["moradores"][u]["personagem"], "txt": f"comentou em {dias[u]} dias"})
    u = max(sem, key=sem.get)
    if sem[u]:
        out.append({"titulo": "Mais ajudou no mutirão", "e": "🧱", "u": u, "p": estado["moradores"][u]["personagem"], "txt": f"{sem[u]} AURAs na semana"})
    u = min(ativos, key=lambda x: x[1]["entrou_em"])[0]
    out.append({"titulo": "Morador veterano", "e": "🏅", "u": u, "p": estado["moradores"][u]["personagem"],
                "txt": "mora desde " + estado["moradores"][u]["entrou_em"][8:10] + "/" + estado["moradores"][u]["entrou_em"][5:7]})
    return out


# ---------------------------------------------------------------- missão do dia
def dia_local(t):
    return t.astimezone(M.FUSO).date()


def missao_de(dia) -> tuple[str, str]:
    return cfg("missoes", MISSOES)[dia.toordinal() % len(cfg("missoes", MISSOES))]


def cumpriu(tipo: str, m: dict, dia, texto: str, quando) -> bool:
    """Confere a missão no momento do comentário (texto = comentário AURA que acabou de chegar)."""
    auras_hoje = [M.de_iso(a) for a in m["auras"] if dia_local(M.de_iso(a)) == dia]
    _, num = M.ler_comentario(texto)
    if tipo == "aura":
        return bool(auras_hoje)
    if tipo == "boneco":
        return num is not None and num == m.get("personagem")
    if tipo == "regiao":
        return M.ler_regiao(texto) is not None
    if tipo == "duas":
        return len(auras_hoje) >= 2
    if tipo == "cedo":
        return quando.astimezone(M.FUSO).hour < 12
    return False


def conferir_missao(m: dict, texto: str, quando) -> bool:
    """Chamado a cada comentário AURA. Dá o bônus 1 vez por dia. Retorna True se acabou de cumprir."""
    dia = dia_local(quando)
    if m.get("missao_dia") == dia.isoformat():
        return False
    tipo, _ = missao_de(dia)
    if cumpriu(tipo, m, dia, texto, quando):
        m["missao_dia"] = dia.isoformat()
        m["brasas_bonus"] = m.get("brasas_bonus", 0) + cfg("bonus_missao", BONUS_MISSAO)
        return True
    return False


def brasas(m: dict) -> int:
    return m.get("total_auras", 0) * cfg("brasas_por_aura", 10) + m.get("brasas_bonus", 0)
