"""Publica a pasta site/ no GitHub Pages (domínio nexo.yt).

Usa uma cópia local do repositório em edificio_aura/.deploy. Só envia quando algo mudou de verdade
(morador novo, AURA, despejo...), e no máximo a cada 6 horas manda uma atualização "de rotina"
para o relógio do aluguel não ficar velho. Nunca envia o motor/.env nem o estado interno.

    python publicar.py            # publica a PÁGINA (index.html, imagens) — use depois de mexer no site
    python publicar.py --dados    # publica só os dados do prédio (é o que o motor faz sozinho)
    python publicar.py --forcar   # publica mesmo sem mudança

Quando o motor roda no GitHub (Actions), AURA_DEPLOY aponta para a cópia do site já baixada lá.
"""
from __future__ import annotations

import hashlib
import os
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

PASTA = Path(__file__).resolve().parent
SITE = PASTA.parent / "site"
DEPLOY = Path(os.environ.get("AURA_DEPLOY") or PASTA.parent / ".deploy")
ARQ_DADOS = ("dados.js", "dados.json")
REPO = "https://github.com/YNSANUZ/edificio-aura.git"
DOMINIO = "nexo.yt"
ROTINA_SEG = 6 * 3600
# campos que mudam sozinhos a cada ciclo (tempo passando) e não justificam publicar
VOLATEIS = {"atualizado_em", "horas", "proximo_despejo", "alerta", "atrasado", "regras", "proximo_reajuste"}


def _git(*args: str, checar: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(DEPLOY), *args], capture_output=True, text=True, encoding="utf-8")
    if checar and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def _impressao(dados: dict) -> str:
    """Resumo dos dados sem os campos que só mudam com o tempo."""
    def limpa(x):
        if isinstance(x, dict):
            return {k: limpa(v) for k, v in x.items() if k not in VOLATEIS}
        if isinstance(x, list):
            return [limpa(v) for v in x]
        return x
    return hashlib.sha1(json.dumps(limpa(dados), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def preparar() -> None:
    if not (DEPLOY / ".git").exists():
        DEPLOY.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", REPO, str(DEPLOY)], check=True, capture_output=True)
    _git("pull", "--rebase", "--quiet", checar=False)


def copiar_site(modo: str) -> None:
    for item in SITE.iterdir():
        if (modo == "dados") != (item.name in ARQ_DADOS):
            continue  # "dados": só dados.js/json; "site": tudo menos os dados (quem manda nos dados é o motor)
        alvo = DEPLOY / item.name
        if item.is_dir():
            shutil.copytree(item, alvo, dirs_exist_ok=True)
        else:
            shutil.copy2(item, alvo)
    (DEPLOY / "CNAME").write_text(DOMINIO + "\n", encoding="utf-8")
    (DEPLOY / ".nojekyll").write_text("", encoding="utf-8")


def publicar(forcar: bool = False, modo: str = "dados") -> str:
    preparar()
    marca = PASTA / "dados" / "ultima_publicacao.json"
    antes = json.loads(marca.read_text(encoding="utf-8")) if marca.exists() else {}
    dados = json.loads((SITE / "dados.json").read_text(encoding="utf-8"))
    imp = _impressao(dados)
    rotina = time.time() - antes.get("quando", 0) > ROTINA_SEG
    copiar_site(modo)
    _git("add", "-A")
    mudados = {linha[3:].strip() for linha in _git("status", "--porcelain").splitlines() if linha.strip()}
    tem_mudanca_arquivo = bool(mudados)
    so_dados = tem_mudanca_arquivo and mudados <= {"dados.js", "dados.json"}
    if modo == "dados" and not forcar and so_dados and imp == antes.get("impressao") and not rotina:
        _git("reset", "--quiet", checar=False)
        _git("checkout", "--", "dados.js", "dados.json", checar=False)
        return "nada novo para publicar"
    if not tem_mudanca_arquivo:
        return "site já está igual ao publicado"
    msg = (f"Atualiza o prédio: {dados.get('total_moradores', 0)} moradores" if modo == "dados"
           else "Atualiza a página do Edifício Aura")
    _git("commit", "-m", msg)
    _git("push", "--quiet", "origin", "HEAD")
    if modo == "dados":
        marca.write_text(json.dumps({"quando": time.time(), "impressao": imp}), encoding="utf-8")
    return f"publicado ({msg})"


if __name__ == "__main__":
    print(publicar("--forcar" in sys.argv, "dados" if "--dados" in sys.argv else "site"))
