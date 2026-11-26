"""Senha do quarto de cada morador + envio das Brasas/presentes para o banco (Supabase).

A senha NUNCA é guardada em lugar nenhum: ela é calculada na hora a partir do @ e de um segredo
(AURA_SEGREDO, que fica só no motor/.env e nos segredos do GitHub). Assim o motor consegue mandar a
mesma senha de novo por DM quando precisar, e o estado público do prédio não revela nada.
No banco vai só a senha embaralhada (sal + sha256).

Variáveis (motor/.env ou ambiente):
  AURA_SEGREDO          texto longo e aleatório (não mude depois: mudaria a senha de todo mundo)
  SUPABASE_URL          https://xxxx.supabase.co
  SUPABASE_SERVICE_KEY  chave "service_role" (secreta)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request

import motor as M



def _env(nome: str) -> str:
    v = os.environ.get(nome)
    if v:
        return v
    try:
        import coletor_instagram as IG
        return IG.ler_env().get(nome, "")
    except Exception:
        return ""


def senha_de(usuario: str, segredo: str | None = None) -> str:
    """Senha fixa do quarto: 6 números (ex.: 482139). Fácil de digitar no celular."""
    segredo = segredo or _env("AURA_SEGREDO")
    if not segredo:
        raise RuntimeError("Falta AURA_SEGREDO")
    h = hmac.new(segredo.encode(), ("quarto:" + usuario.lower()).encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(h[:8], 'big') % 1_000_000:06d}"


def limpar(senha: str) -> str:
    """Só os números (a pessoa pode digitar com espaço ou traço)."""
    return "".join(ch for ch in senha if ch.isdigit())


def embaralhar(usuario: str, senha: str, segredo: str | None = None) -> tuple[str, str]:
    """(sal, hash) do jeito que o banco confere: sha256(sal + só os números da senha)."""
    segredo = segredo or _env("AURA_SEGREDO")
    sal = hmac.new(segredo.encode(), ("sal:" + usuario.lower()).encode(), hashlib.sha256).hexdigest()[:16]
    return sal, hashlib.sha256((sal + limpar(senha)).encode()).hexdigest()


def linhas(estado: dict, segredo: str | None = None) -> list[dict]:
    """Uma linha por morador (inclusive despejados: o quarto deles volta junto)."""
    cfg = M.CONFIG.get("brasas_por_aura", 10)
    out = []
    for u, m in estado.get("moradores", {}).items():
        tot = m.get("total_auras", 0)
        sal, h = embaralhar(u, senha_de(u, segredo), segredo)
        import comunidade
        out.append({"u": u, "sal": sal, "senha_hash": h, "brasas_ganhas": comunidade.brasas(m),
                    "sindico_de": estado.get("cargos", {}).get(u),
                    "presentes": {k: v for k, v in M.moveis_de(tot).items() if v}})
    return out


def sincronizar(estado: dict) -> str:
    """Manda para o banco só quem mudou desde a última vez (marca em estado['banco'])."""
    url, chave, seg = _env("SUPABASE_URL"), _env("SUPABASE_SERVICE_KEY"), _env("AURA_SEGREDO")
    if not (url and chave and seg):
        return "banco ainda não configurado (pulei)"
    marcas = estado.setdefault("banco", {})
    novas = []
    for ln in linhas(estado, seg):
        assinatura = f"{ln['brasas_ganhas']}|{json.dumps(ln['presentes'], sort_keys=True)}|{ln['senha_hash'][:8]}|{ln['sindico_de']}"
        if marcas.get(ln["u"]) != assinatura:
            novas.append((ln, assinatura))
    if not novas:
        return "banco em dia"
    for i in range(0, len(novas), 500):
        lote = novas[i:i + 500]
        req = urllib.request.Request(
            url.rstrip("/") + "/rest/v1/moradores?on_conflict=u", method="POST",
            data=json.dumps([ln for ln, _ in lote]).encode(),
            headers={"apikey": chave, "Authorization": "Bearer " + chave, "Content-Type": "application/json",
                     "Prefer": "resolution=merge-duplicates,return=minimal"})
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status >= 300:
                raise RuntimeError(f"banco respondeu {r.status}")
        for ln, a in lote:
            marcas[ln["u"]] = a
    return f"banco: {len(novas)} morador(es) atualizado(s)"


def curtidas_novas(estado: dict) -> list[dict]:
    """Curtidas pagas dos últimos 2 dias (o motor ignora as que já contou)."""
    url, chave = _env("SUPABASE_URL"), _env("SUPABASE_SERVICE_KEY")
    if not (url and chave):
        return []
    from datetime import timedelta
    desde = M.iso(M.agora_utc() - timedelta(days=2))
    q = ("/rest/v1/curtidas?select=dono,visitante,dia,quando,paga&paga=is.true&order=quando.asc&limit=10000"
         "&quando=gte." + urllib.parse.quote(desde))
    req = urllib.request.Request(url.rstrip("/") + q, headers={"apikey": chave, "Authorization": "Bearer " + chave})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def visualizacoes() -> dict:
    """{@: visualizações} de todos os quartos (para o 👁 no nome). Sem banco: vazio."""
    url, chave = _env("SUPABASE_URL"), _env("SUPABASE_SERVICE_KEY")
    if not (url and chave):
        return {}
    req = urllib.request.Request(url.rstrip("/") + "/rest/v1/stats_quarto?select=u,views&views=gt.0&limit=200000",
                                 headers={"apikey": chave, "Authorization": "Bearer " + chave})
    with urllib.request.urlopen(req, timeout=30) as r:
        return {x["u"]: x["views"] for x in json.loads(r.read().decode())}


def apagar_no_banco(usuario: str) -> None:
    """Pedido de exclusão de dados: tira o morador de todas as tabelas do banco."""
    url, chave = _env("SUPABASE_URL"), _env("SUPABASE_SERVICE_KEY")
    if not (url and chave):
        return
    u = urllib.parse.quote(usuario)
    for tabela, filtro in [("moradores", f"u=eq.{u}"), ("quartos", f"u=eq.{u}"), ("stats_quarto", f"u=eq.{u}"),
                           ("curtidas", f"or=(dono.eq.{u},visitante.eq.{u})"), ("visitas", f"or=(dono.eq.{u},visitante.eq.{u})"),
                           ("lemas", f"por=eq.{u}")]:
        req = urllib.request.Request(f"{url.rstrip('/')}/rest/v1/{tabela}?{filtro}", method="DELETE",
                                     headers={"apikey": chave, "Authorization": "Bearer " + chave})
        urllib.request.urlopen(req, timeout=30).read()
