"""Coletor de comentários do Instagram — SOMENTE LEITURA.

Usa a API oficial (Instagram API com login do Instagram, conta Profissional/Criador).
Nunca posta, nunca responde, nunca segue ninguém: só lê os comentários dos SEUS posts.

O token fica no arquivo motor/.env (nunca mande esse arquivo para ninguém):
    IG_TOKEN=seu_token_longo
    IG_USER_ID=me
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path

import motor as M

PASTA = Path(__file__).resolve().parent
ARQ_ENV = PASTA / ".env"
ARQ_CACHE = PASTA / "dados" / "cache_posts.json"
CFG = M.CONFIG["instagram"]


class ErroInstagram(Exception):
    pass


def ler_env() -> dict:
    if not ARQ_ENV.exists():
        return {}
    env = {}
    for linha in ARQ_ENV.read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.strip().startswith("#"):
            k, v = linha.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def eh_token_facebook(token: str) -> bool:
    """Token do Instagram começa com IG; os do Facebook/login unificado começam com EA (EAA, EAB...)."""
    return not token.startswith("IG")


def destino(env: dict) -> tuple[str, str]:
    """A Meta entrega 2 tipos de token: o do login do Instagram (começa com IG, usa graph.instagram.com)
    e o do login unificado / usuário do sistema (começa com EAA, usa graph.facebook.com + id da conta)."""
    token, user = env.get("IG_TOKEN", ""), env.get("IG_USER_ID", "me")
    if eh_token_facebook(token):
        return CFG.get("graph_facebook", "https://graph.facebook.com/v21.0"), (user if user != "me" else CFG["ig_user_id"])
    return CFG["api_base"], user


def configurado() -> bool:
    t = ler_env().get("IG_TOKEN", "")
    return bool(t) and not t.startswith("cole_")


def _get(url: str, params: dict | None, token: str) -> dict:
    if params is not None:
        url = url + "?" + urllib.parse.urlencode({**params, "access_token": token})
    req = urllib.request.Request(url, headers={"User-Agent": "edificio-aura/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            dados = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise ErroInstagram(f"Instagram respondeu erro {e.code}: {msg or e.reason}") from None
    except urllib.error.URLError as e:
        raise ErroInstagram(f"Sem conexão com o Instagram: {e.reason}") from None
    time.sleep(CFG["pausa_entre_chamadas_seg"])
    return dados


def _paginas(url: str, params: dict, token: str):
    dados = _get(url, params, token)
    while True:
        yield from dados.get("data", [])
        prox = dados.get("paging", {}).get("next")
        if not prox:
            return
        dados = _get(prox, None, token)  # o link "next" já traz o token


def coletar(agora=None) -> list[dict]:
    """Retorna os comentários dos posts recentes. Pula posts sem comentários novos."""
    env = ler_env()
    token = env.get("IG_TOKEN")
    if not token:
        raise ErroInstagram("Falta o IG_TOKEN no arquivo motor/.env (veja COMO_LIGAR.md).")
    base, user = destino(env)
    agora = agora or M.agora_utc()
    limite = agora - timedelta(days=CFG["posts_dos_ultimos_dias"])
    cache = json.loads(ARQ_CACHE.read_text(encoding="utf-8")) if ARQ_CACHE.exists() else {}

    comentarios, posts_lidos = [], 0
    for post in _paginas(f"{base}/{user}/media", {"fields": "id,timestamp,comments_count", "limit": 25}, token):
        if M.de_iso(post["timestamp"]) < limite or posts_lidos >= CFG["max_posts"]:
            break
        posts_lidos += 1
        n = post.get("comments_count", 0)
        if n == 0 or cache.get(post["id"]) == n:
            continue
        for c in _paginas(f"{base}/{post['id']}/comments", {"fields": "id,text,username,timestamp", "limit": 50}, token):
            comentarios.append(c)
        cache[post["id"]] = n

    ARQ_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ARQ_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return comentarios


def renovar_token() -> None:
    """Tokens longos duram 60 dias. Renove a cada mês (o rodar.py faz isso sozinho)."""
    env = ler_env()
    token = env.get("IG_TOKEN")
    if not token:
        raise ErroInstagram("Falta o IG_TOKEN no .env")
    if eh_token_facebook(token):
        return  # token de usuário do sistema não expira
    novo = _get("https://graph.instagram.com/refresh_access_token",
                {"grant_type": "ig_refresh_token"}, token)
    if "access_token" not in novo:
        raise ErroInstagram("Não consegui renovar o token.")
    env["IG_TOKEN"] = novo["access_token"]
    env["IG_TOKEN_RENOVADO_EM"] = M.iso(M.agora_utc())
    ARQ_ENV.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")


def verificar() -> list[str]:
    """Confere se o token funciona e se dá para ler comentários. Não mostra o token."""
    env = ler_env()
    token = env.get("IG_TOKEN")
    if not token or token.startswith("cole_"):
        raise ErroInstagram("O arquivo motor/.env ainda está sem o token (IG_TOKEN).")
    base, user = destino(env)
    campos = "id,username,media_count" if eh_token_facebook(token) else "user_id,username,account_type,media_count"
    perfil = _get(f"{base}/{user}", {"fields": campos}, token)
    msgs = [f"✅ Conectado como @{perfil.get('username')} (conta {perfil.get('account_type', 'profissional')}, "
            f"{perfil.get('media_count', '?')} posts)"]
    posts = _get(f"{base}/{user}/media", {"fields": "id,timestamp,comments_count", "limit": 5}, token).get("data", [])
    if not posts:
        msgs.append("⚠️ Nenhum post encontrado para testar a leitura de comentários.")
        return msgs
    com = next((p for p in posts if p.get("comments_count")), posts[0])
    lidos = _get(f"{base}/{com['id']}/comments", {"fields": "id,text,username,timestamp", "limit": 5}, token).get("data", [])
    msgs.append(f"✅ Leitura de comentários funcionando ({len(lidos)} comentário(s) lido(s) no post de teste)")
    if lidos and "username" not in lidos[0]:
        msgs.append("⚠️ Os comentários vieram sem o @ de quem comentou: falta a permissão instagram_business_manage_comments.")
    if not env.get("IG_TOKEN_RENOVADO_EM"):
        env["IG_TOKEN_RENOVADO_EM"] = M.iso(M.agora_utc())
        ARQ_ENV.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    return msgs
