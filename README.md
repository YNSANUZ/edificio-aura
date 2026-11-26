# Ramo `motor` do Edifício Aura

Aqui ficam o motor de regras e a memória do prédio (`motor/dados/estado.json`).
Uma rotina do GitHub Actions (`.github/workflows/motor.yml`, no ramo `main`) roda a cada ~10 minutos:
lê os comentários do @comenteaura (só leitura), aplica as regras, guarda o estado aqui e publica
`dados.js` no ramo `main`, que é o site https://nexo.yt.

O token do Instagram fica SÓ no segredo `IG_TOKEN` do repositório — nunca em arquivo.
