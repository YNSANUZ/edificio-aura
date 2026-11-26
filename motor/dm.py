"""DM de boas-vindas com a senha do quarto (resposta privada ao comentário AURA no Instagram).

Regras da Meta: 1 mensagem por comentário, até 7 dias depois do comentário. Por isso o motor responde
ao último comentário AURA de cada morador que ainda não recebeu a DM.

TRAVA DE SEGURANÇA (motor/config.json -> "dm"):
  "ligado": false          -> não manda nada (padrão)
  "so_teste": true         -> só manda para as contas em "contas_teste" (app da Meta em modo desenvolvimento)
  "contas_teste": ["..."]  -> @ das contas de teste (precisam ter papel de testador no app da Meta)
  "max_por_ciclo": 20      -> no máximo isso por ciclo de 10 min

Token (motor/.env ou segredos do GitHub), um dos dois:
  IG_DM_TOKEN  = token do "Instagram API com login do Instagram" (começa com IG) -> graph.instagram.com
  PAGE_TOKEN   = token da Página do Facebook ligada ao @comenteaura             -> graph.facebook.com
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import timedelta

import motor as M

JANELA = timedelta(days=7) - timedelta(minutes=30)   # margem para não estourar os 7 dias


def _cfg() -> dict:
    return {"ligado": False, "so_teste": True, "contas_teste": [], "max_por_ciclo": 20, **M.CONFIG.get("dm", {})}


def _env(nome: str) -> str:
    import quartos_db
    return quartos_db._env(nome)


def nome_regiao(cod: str | None) -> str:
    return M.CONFIG.get("regioes", {}).get(cod or "", "Brasil Aura")


def texto(usuario: str, m: dict, senha: str) -> str:
    """Mesma mensagem de docs/DM_BOAS_VINDAS.md (cada linha começa com emoji)."""
    c = M.CONFIG
    dias = round(c["saldo_inicial_horas"] / 24)
    horas = round(M.valor_aura(M.agora_utc()))
    linhas = [
        f"🔥 Bem-vindo ao Edifício Aura, @{usuario}!",
        "",
        f"🏠 Você já mora no {nome_regiao(m.get('regiao'))}.",
        f"🔑 Senha do seu quarto: {senha}",
        "📌 Guarde esta mensagem.",
        "",
        "👀 Ver seu apê:",
        "nexo.yt → digite seu @",
        "",
        "🧍 Trocar personagem:",
        "comente AURA + número de 1 a 20 (ex.: AURA 7)",
        "",
        "🛋️ Comprar móveis:",
        "no seu apê toque em \"Entrar\", use a senha e gaste suas Brasas",
        "",
        "🗺️ Mudar de região:",
        "comente AURA + região ou estado (ex.: AURA NE, AURA BA, AURA DF)",
        "",
        "⏳ Aluguel:",
        f"{dias} dias grátis, depois cada AURA paga {horas}h",
        "",
        "📢 Quer divulgar sua marca no dirigível?",
        "Responda esta mensagem com DIRIGÍVEL.",
    ]
    return "\n".join(linhas)


def _post(url: str, token: str, corpo: dict) -> dict:
    req = urllib.request.Request(url, method="POST", data=json.dumps(corpo).encode(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Meta respondeu {e.code}: {e.read().decode()[:300]}")


def enviar(comment_id: str, msg: str) -> dict:
    corpo = {"recipient": {"comment_id": comment_id}, "message": {"text": msg}}
    ig_id = M.CONFIG.get("instagram", {}).get("ig_user_id", "")
    tok = _env("IG_DM_TOKEN")
    if tok:
        return _post("https://graph.instagram.com/v21.0/me/messages", tok, corpo)   # "me" = a conta dona do token
    # login unificado: o próprio token do motor (EAB…, com instagram_manage_messages) manda a resposta privada
    tok = _env("PAGE_TOKEN") or _env("IG_TOKEN")
    if tok:
        return _post(f"https://graph.facebook.com/v21.0/{ig_id}/messages", tok, corpo)
    raise RuntimeError("sem token de mensagens (IG_TOKEN)")


def pendentes(estado: dict, agora) -> list[tuple[str, dict]]:
    """Moradores que ainda não receberam a DM e têm um comentário AURA de menos de 7 dias."""
    cfg = _cfg()
    enviadas = estado.get("dm_enviadas", {})
    teste = {u.lower().lstrip("@") for u in cfg["contas_teste"]}
    out = []
    for u, m in estado["moradores"].items():
        if u in enviadas or not m.get("ultimo_cid") or m.get("status") == "despejado":
            continue
        if agora - M.de_iso(m["ultimo_cid_em"]) > JANELA:
            continue
        if cfg["so_teste"] and u not in teste:
            continue
        out.append((u, m))
    out.sort(key=lambda x: x[1]["ultimo_cid_em"])
    return out[: cfg["max_por_ciclo"]]


def enviar_pendentes(estado: dict, agora, enviar_fn=None) -> str:
    cfg = _cfg()
    if not cfg["ligado"]:
        return ""
    import quartos_db
    enviar_fn = enviar_fn or enviar
    seg = _env("AURA_SEGREDO")
    if not seg:
        return "DM: falta AURA_SEGREDO"
    enviadas = estado.setdefault("dm_enviadas", {})
    ok, erros = 0, []
    for u, m in pendentes(estado, agora):
        try:
            enviar_fn(m["ultimo_cid"], texto(u, m, quartos_db.senha_de(u, seg)))
            enviadas[u] = M.iso(agora)
            ok += 1
        except Exception as e:
            erros.append(f"@{u}: {str(e)[:160]}")
            if "sem token" in str(e):
                break
    msg = f"DM: {ok} senha(s) enviada(s)" if ok else ""
    if erros:
        msg += (" | " if msg else "DM: ") + "; ".join(erros[:3])
    return msg
