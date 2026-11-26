"""Roda o ciclo do Edifício Aura: coleta -> aplica regras -> despeja -> atualiza o site.

Exemplos:
    python rodar.py --simular 120     # TESTE com 120 seguidores falsos (não toca no Instagram)
    python rodar.py --verificar       # testa se o token do Instagram funciona
    python rodar.py --uma-vez         # 1 ciclo de verdade lendo o Instagram
    python rodar.py --sempre 10       # fica rodando, 1 ciclo a cada 10 minutos
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import timedelta
from pathlib import Path

import motor as M
import coletor_instagram as IG

PASTA = Path(__file__).resolve().parent
SITE = PASTA.parent / "site"
REGRAS_MD = PASTA.parent / "docs" / "REGRAS_ATUAIS.md"
ARQ_SIMULACAO = PASTA / "dados" / "estado_simulacao.json"
LOG = PASTA / "dados" / "log.txt"


def log(msg: str) -> None:
    linha = f"[{M.agora_utc().astimezone().strftime('%d/%m %H:%M:%S')}] {msg}"
    print(linha)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


def ciclo_real() -> None:
    agora = M.agora_utc()
    estado = M.carregar()
    env = IG.ler_env()
    renovado = env.get("IG_TOKEN_RENOVADO_EM")
    if renovado and agora - M.de_iso(renovado) > timedelta(days=30):
        IG.renovar_token()
        log("Token do Instagram renovado.")
    try:
        comentarios = IG.coletar(agora)
    except IG.ErroInstagram as e:
        # se a coleta falhar, NÃO mexe em ninguém: nem despeja, para não punir por erro nosso
        log(f"ERRO na coleta, ciclo cancelado sem mudanças: {e}")
        return
    resumo = M.aplicar_lote(estado, comentarios, agora)
    try:  # Brasas e móveis de presente vão para o banco da lojinha (se já estiver configurado)
        import quartos_db
        n_curt = M.creditar_curtidas(estado, quartos_db.curtidas_novas(estado), agora)
        if n_curt:
            log(f"{n_curt} curtida(s) em quartos viraram aluguel")
        msg_banco = quartos_db.sincronizar(estado)
        if "pulei" not in msg_banco and "em dia" not in msg_banco:
            log(msg_banco)
    except Exception as e:  # banco fora do ar não pode parar o prédio
        log(f"Banco da lojinha: não consegui atualizar agora ({str(e)[:150]})")
    try:  # DM com a senha do quarto (só se "dm.ligado" no config; trava de teste por padrão)
        import dm
        msg_dm = dm.enviar_pendentes(estado, agora)
        if msg_dm:
            log(msg_dm)
    except Exception as e:
        log(f"DM: não consegui enviar agora ({str(e)[:150]})")
    M.salvar(estado)
    try:
        import quartos_db
        views = quartos_db.visualizacoes()
    except Exception as e:
        views = {}
        log(f"Banco: não consegui ler as visualizações ({str(e)[:120]})")
    dados = M.exportar(estado, agora, SITE, views)
    M.gravar_regras_md(REGRAS_MD, agora)
    log(f"{len(comentarios)} comentários lidos {resumo} | {dados['total_moradores']} moradores, "
        f"{dados['total_blocos']} blocos, top1 = {dados['vip']['u'] if dados['vip'] else '-'}")
    if os.environ.get("AURA_SEM_PUBLICAR"):
        return  # no GitHub Actions quem publica é a própria rotina
    try:
        import publicar
        log("Site nexo.yt: " + publicar.publicar(modo="dados"))
    except Exception as e:  # publicar falhar não pode parar o motor
        log(f"Site nexo.yt: não consegui publicar agora ({str(e)[:150]})")


NOMES_A = ["luna", "pedro", "nina", "caio", "bia", "theo", "rafa", "mari", "gui", "duda", "leo", "sofi",
           "kaka", "juh", "lari", "beto", "ana", "tom", "manu", "iza", "joao", "lele", "vovo", "tio", "ze"]
NOMES_B = ["aura", "flux", "vibes", "games", "art", "fit", "pudim", "beat", "zen", "oficial", "_br", ".tv",
           "_07", "sk8", "music", "makes", "do_pastel", "luz", "spark", "mood"]


def simular(n: int) -> None:
    """Gera 3 semanas de comentários falsos para ver o prédio enchendo. Usa um estado separado."""
    random.seed(42)
    agora = M.agora_utc()
    inicio = agora - timedelta(days=21)
    usuarios = list(dict.fromkeys(f"{random.choice(NOMES_A)}{random.choice(NOMES_B)}" for _ in range(n * 3)))[:n]
    comentarios, i = [], 0
    for u in usuarios:
        ritmo = random.choice([0.1, 0.3, 1, 2, 4])  # AURAs por dia
        chegada = inicio + timedelta(hours=random.uniform(0, 20 * 24))
        t = chegada
        while t < agora:
            txt = random.choice(["AURA", "aura 🔥", "AURA!!", f"AURA {random.randint(1, 20)}", "muita aura"])
            if t == chegada:
                txt = f"AURA {random.randint(1, 20)}"
                reg = random.choices(["NE", "SUL", "SUDESTE", "NORTE", "CO", ""], [22, 12, 30, 8, 10, 18])[0]
                if reg:
                    txt += " " + reg
            comentarios.append({"id": f"sim{i}", "username": u, "text": txt, "timestamp": M.iso(t)})
            i += 1
            t += timedelta(hours=random.expovariate(ritmo / 24))
        if random.random() < 0.3:  # alguns comentários sem AURA
            comentarios.append({"id": f"sim{i}", "username": u, "text": "que legal kkk", "timestamp": M.iso(chegada)})
            i += 1
    estado = M.estado_vazio()
    resumo = M.aplicar_lote(estado, comentarios, agora)
    M.salvar(estado, ARQ_SIMULACAO)
    dados = M.exportar(estado, agora, SITE)
    M.gravar_regras_md(REGRAS_MD, agora)
    despejos = sum(1 for e in estado["eventos"] if e["tipo"] == "despejo")
    print(f"SIMULAÇÃO: {len(usuarios)} pessoas, {len(comentarios)} comentários {resumo}")
    print(f"  -> {dados['total_moradores']} moradores ativos em {dados['total_blocos']} blocos, "
          f"{despejos} despejos em 3 semanas, {dados['total_pracinha']} na Pracinha, top1 = @{dados['vip']['u'] if dados['vip'] else '-'}")
    print(f"  -> site atualizado: {SITE / 'index.html'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Edifício Aura")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--verificar", action="store_true", help="testa a conexão com o Instagram")
    g.add_argument("--simular", type=int, metavar="N", help="teste com N seguidores falsos")
    g.add_argument("--uma-vez", action="store_true", help="um ciclo lendo o Instagram")
    g.add_argument("--sempre", type=int, metavar="MIN", help="repetir a cada MIN minutos")
    a = ap.parse_args()
    if a.simular:
        simular(a.simular)
        return
    if a.verificar:
        try:
            for m in IG.verificar():
                print(m)
            print("Tudo certo! Próximo passo: python rodar.py --uma-vez")
        except IG.ErroInstagram as e:
            print(f"❌ {e}")
            sys.exit(1)
        return
    if not IG.configurado():
        sys.exit("Instagram ainda não configurado: crie motor/.env com IG_TOKEN (veja COMO_LIGAR.md).")
    if a.uma_vez:
        ciclo_real()
        return
    minutos = max(5, a.sempre)  # nunca mais rápido que 5 min, para respeitar o limite da API
    log(f"Rodando sem parar, a cada {minutos} min. Feche a janela para parar.")
    while True:
        ciclo_real()
        time.sleep(minutos * 60)


if __name__ == "__main__":
    main()
