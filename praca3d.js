/* Praça Aura 3D — mesma ideia da arena do NO TOPO (three.js), no tema do Edifício Aura.
   Os últimos moradores andam sozinhos com o @ na cabeça; tocar num deles abre o apê.
   Quem ENTROU com @ + senha ganha o próprio boneco: toca no chão para andar e manda mensagens rápidas
   (lista pronta, sem texto livre). Por enquanto só quem manda vê o próprio boneco; ao ligar o tempo real
   do banco, todos passam a se ver. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const RAIO = 15.5;                       // raio da praça (onde dá pra andar)
const MAX_MORADORES = 24;
const FRASES = ["👋 Oi!", "🔥 AURA!", "🏠 Bem-vindo, vizinho!", "😂 kkkkk", "❤️", "👑 Bora pro topo!", "🛋️ Olha meu apê!", "🎉 Cheguei!"];
/* paleta (só as cores) inspirada na arte de referência: pôr do sol pêssego/rosado, piso de pedrinha creme,
   ipê amarelo e rosa, luzinhas quentes, prédios de tijolo claro com janelas amarelas */
const COR = { ceuTopo: "#ff8f4a", ceuMeio: "#ffab7a", horizonte: "#ffdcb0", piso: 0xf2d7c4, caminho: "#d9a98c", borda: 0xff7a1a,
              grama: 0x79b84a, madeira: 0x9c4f26, poste: 0x3b2414, luz: 0xffd27a, predioEsc: 0xd88a63, tijolo: "#e9a27a",
              ipeAmarelo: 0xffc83a, ipeRosa: 0xff8fb3, folha: 0x5aa236 };

let estado = null;   // a praça só é montada uma vez; depois só liga/desliga

function textura(canvas) { const t = new THREE.CanvasTexture(canvas); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t; }

function ceuGradiente() {
  const c = document.createElement("canvas"); c.width = 16; c.height = 512;
  const g = c.getContext("2d"), gr = g.createLinearGradient(0, 0, 0, 512);
  gr.addColorStop(0, COR.ceuTopo); gr.addColorStop(.55, COR.ceuMeio); gr.addColorStop(1, COR.horizonte);
  g.fillStyle = gr; g.fillRect(0, 0, 16, 512); return textura(c);
}

function etiqueta(texto, { fundo = "#2b160a", cor = "#ffd23f", tam = 40 } = {}) {
  const c = document.createElement("canvas"), g = c.getContext("2d");
  g.font = `800 ${tam}px "Baloo 2", system-ui, sans-serif`;
  const w = Math.ceil(g.measureText(texto).width) + tam * 1.1, h = Math.ceil(tam * 1.6);
  c.width = w; c.height = h;
  g.font = `800 ${tam}px "Baloo 2", system-ui, sans-serif`;
  g.fillStyle = fundo; g.beginPath(); g.roundRect(0, 0, w, h, h / 2); g.fill();
  g.fillStyle = cor; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(texto, w / 2, h / 2 + 2);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: textura(c), transparent: true, depthTest: false }));
  const alt = .75; s.scale.set(alt * w / h, alt, 1); s.renderOrder = 10; return s;
}

function balao(texto) {
  const c = document.createElement("canvas"), g = c.getContext("2d"), tam = 44;
  g.font = `800 ${tam}px "Baloo 2", system-ui, sans-serif`;
  const w = Math.ceil(g.measureText(texto).width) + 60, h = 92;
  c.width = w; c.height = h + 22;
  g.font = `800 ${tam}px "Baloo 2", system-ui, sans-serif`;
  g.fillStyle = "#fff"; g.strokeStyle = "#2b160a"; g.lineWidth = 6;
  g.beginPath(); g.roundRect(3, 3, w - 6, h - 6, 30); g.fill(); g.stroke();
  g.beginPath(); g.moveTo(w / 2 - 14, h - 4); g.lineTo(w / 2, h + 18); g.lineTo(w / 2 + 14, h - 4); g.fill();
  g.fillStyle = "#2b160a"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(texto, w / 2, h / 2 + 2);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: textura(c), transparent: true, depthTest: false }));
  const alt = 1.15; s.scale.set(alt * c.width / c.height, alt, 1); s.renderOrder = 11; return s;
}

function painel(linhas, { w = 1024, h = 680, fundo = "#2b160a", destaque = "#ffd23f", img = null } = {}) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d");
  const gr = g.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, "#ff7a1a"); gr.addColorStop(1, fundo);
  g.fillStyle = gr; g.fillRect(0, 0, w, h);
  g.strokeStyle = destaque; g.lineWidth = 14; g.strokeRect(7, 7, w - 14, h - 14);
  g.textAlign = "center"; g.fillStyle = "#fff";
  let y = 110;
  linhas.forEach(([txt, tam, cor]) => { g.font = `800 ${tam}px "Baloo 2", system-ui, sans-serif`; g.fillStyle = cor || "#fff"; g.fillText(txt, w / 2, y); y += tam * 1.25; });
  const t = textura(c);
  if (img) img.then((im) => { if (!im) return; const a = Math.min(300 / im.height, 1); g.drawImage(im, w / 2 - im.width * a / 2, h - 330, im.width * a, im.height * a); t.needsUpdate = true; });
  return t;
}

const carregarImg = (src) => new Promise((ok) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => ok(null); i.src = src; });
const texCache = new Map();
function texBoneco(p) {
  if (!texCache.has(p)) { const t = new THREE.TextureLoader().load(`img/corpo${p}.png`); t.colorSpace = THREE.SRGBColorSpace; texCache.set(p, t); }
  return texCache.get(p);
}

function hash(s) { let h = 2166136261; for (const ch of s) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967295; }

function pontoAleatorio(r = RAIO - 2) { const a = Math.random() * Math.PI * 2, d = 3.5 + Math.random() * (r - 3.5); return new THREE.Vector3(Math.sin(a) * d, 0, Math.cos(a) * d); }

/* ---------- pessoas (bonecos 2D em pé, sempre de frente para a câmera) ---------- */
export const fmtNum = (n) => n >= 1e6 ? (n / 1e6).toFixed(1).replace(".0", "").replace(".", ",") + " mi" : n >= 1e3 ? (n / 1e3).toFixed(1).replace(".0", "").replace(".", ",") + " mil" : String(n);

function criarPessoa(cena, { u = null, p = 1, figurante = false, v = 0 }) {
  const g = new THREE.Group();
  const mat = new THREE.SpriteMaterial({ map: texBoneco(p), transparent: true, alphaTest: .2 });
  const corpo = new THREE.Sprite(mat); corpo.center.set(.5, 0);
  const alt = 2.5; corpo.scale.set(alt * .62, alt, 1);
  mat.map.image && mat.map.image.width && corpo.scale.set(alt * mat.map.image.width / mat.map.image.height, alt, 1);
  mat.map.onUpdate = () => { const im = mat.map.image; if (im && im.width) corpo.scale.set(alt * im.width / im.height, alt, 1); };
  g.add(corpo);
  const sombra = new THREE.Mesh(new THREE.CircleGeometry(.55, 20), new THREE.MeshBasicMaterial({ color: 0x5a2d0c, transparent: true, opacity: .28 }));
  sombra.rotation.x = -Math.PI / 2; sombra.position.y = .02; g.add(sombra);
  let tag = null;
  if (u) { tag = etiqueta("@" + u + (v ? "  👁 " + fmtNum(v) : "")); tag.position.y = alt + .45; g.add(tag); }
  g.position.copy(pontoAleatorio());
  cena.add(g);
  const fase = hash(u || String(Math.random())) * 10;
  return { g, corpo, tag, u, p, figurante, alvo: pontoAleatorio(), parado: Math.random() * 3, fase, vel: .9 + hash((u || "") + "v") * .7, balao: null, balaoAte: 0, alt, esq: false };
}

function falar(pessoa, texto, agora, seg = 4) {
  if (pessoa.balao) { pessoa.g.remove(pessoa.balao); pessoa.balao.material.map.dispose(); pessoa.balao.material.dispose(); }
  pessoa.balao = balao(texto); pessoa.balao.position.y = pessoa.alt + (pessoa.tag ? 1.35 : .9); pessoa.g.add(pessoa.balao);
  pessoa.balaoAte = agora + seg;
}

/* ---------- cenário no tema Aura ---------- */
function montarCenario(cena) {
  cena.background = ceuGradiente();
  cena.fog = new THREE.Fog(0xffd0a8, 45, 110);
  cena.add(new THREE.HemisphereLight(0xfff1d6, 0xb5652a, 2.4));
  const sol = new THREE.DirectionalLight(0xffd9a0, 2.2); sol.position.set(-14, 22, 12); cena.add(sol);

  const grama = new THREE.Mesh(new THREE.CircleGeometry(90, 64), new THREE.MeshStandardMaterial({ color: COR.grama, roughness: 1 }));
  grama.rotation.x = -Math.PI / 2; grama.position.y = -.05; cena.add(grama);
  // piso de pedrinha (mosaico) creme com caminhos em espiral mais escuros
  const pc = document.createElement("canvas"); pc.width = pc.height = 1024; const pg = pc.getContext("2d");
  pg.fillStyle = "#f2d7c4"; pg.fillRect(0, 0, 1024, 1024);
  for (let i = 0; i < 9000; i++) { pg.fillStyle = Math.random() < .5 ? "#ecc9b3" : "#f7e3d3"; pg.fillRect(Math.random() * 1024, Math.random() * 1024, 7, 7); }
  pg.strokeStyle = COR.caminho; pg.lineWidth = 26; pg.lineCap = "round";
  for (let k = 0; k < 3; k++) { pg.beginPath(); for (let a = 0; a < Math.PI * 4.2; a += .05) { const r = 90 + a * 30 + k * 60;
    const x = 512 + Math.cos(a + k * 2.1) * r, y = 512 + Math.sin(a + k * 2.1) * r; a ? pg.lineTo(x, y) : pg.moveTo(x, y); } pg.stroke(); }
  const piso = new THREE.Mesh(new THREE.CylinderGeometry(RAIO + 1.5, RAIO + 1.8, .3, 72),
    [new THREE.MeshStandardMaterial({ color: 0xe2b79c }), new THREE.MeshStandardMaterial({ map: textura(pc), roughness: .95 }), new THREE.MeshStandardMaterial({ color: 0xe2b79c })]);
  piso.position.y = -.15; cena.add(piso);
  const borda = new THREE.Mesh(new THREE.TorusGeometry(RAIO + 1.6, .14, 8, 96), new THREE.MeshBasicMaterial({ color: COR.borda }));
  borda.rotation.x = Math.PI / 2; borda.position.y = .02; cena.add(borda);

  // bancos, postes e árvores em volta
  const madeira = new THREE.MeshStandardMaterial({ color: COR.madeira, roughness: .8 });
  const ferro = new THREE.MeshStandardMaterial({ color: COR.poste, roughness: .6 });
  const lampada = new THREE.MeshStandardMaterial({ color: COR.luz, emissive: 0xffa53a, emissiveIntensity: 2.2 });
  const copas = [COR.ipeAmarelo, COR.folha, COR.ipeRosa].map((c) => new THREE.MeshStandardMaterial({ color: c, roughness: 1 }));
  const tronco = new THREE.MeshStandardMaterial({ color: 0x7a4a24 });
  const lampadas = [];
  for (let i = 0; i < 12; i++) {
    const a = i / 12 * Math.PI * 2 + .26, x = Math.sin(a), z = Math.cos(a);
    if (z < -.6) continue;                       // fundo fica livre para o prédio
    if (i % 2 === 0) {
      const banco = new THREE.Group(); banco.position.set(x * (RAIO + .6), 0, z * (RAIO + .6)); banco.rotation.y = a + Math.PI;
      const ass = new THREE.Mesh(new THREE.BoxGeometry(2.2, .16, .6), madeira); ass.position.y = .55;
      const enc = new THREE.Mesh(new THREE.BoxGeometry(2.2, .5, .12), madeira); enc.position.set(0, .9, .26);
      [-.9, .9].forEach((px) => { const pe = new THREE.Mesh(new THREE.BoxGeometry(.12, .55, .5), ferro); pe.position.set(px, .27, 0); banco.add(pe); });
      banco.add(ass, enc); cena.add(banco);
    } else {
      const poste = new THREE.Group(); poste.position.set(x * (RAIO + .9), 0, z * (RAIO + .9));
      const haste = new THREE.Mesh(new THREE.CylinderGeometry(.09, .12, 3.6, 8), ferro); haste.position.y = 1.8;
      const bulbo = new THREE.Mesh(new THREE.SphereGeometry(.32, 16, 12), lampada); bulbo.position.y = 3.75;
      poste.add(haste, bulbo); cena.add(poste); lampadas.push(new THREE.Vector3(x * (RAIO + .9), 3.75, z * (RAIO + .9)));
    }
    const arv = new THREE.Group(); arv.position.set(x * (RAIO + 4.5), 0, z * (RAIO + 4.5));
    const tr = new THREE.Mesh(new THREE.CylinderGeometry(.25, .35, 1.6, 8), tronco); tr.position.y = .8;
    const copa = new THREE.Mesh(new THREE.SphereGeometry(1.7, 12, 10), copas[i % 3]); copa.position.y = 2.7; copa.scale.y = 1.1;
    arv.add(tr, copa); cena.add(arv);
  }
  // cordão de luzinhas ligando os postes
  const bolinha = new THREE.SphereGeometry(.09, 8, 6), matLuz = new THREE.MeshBasicMaterial({ color: 0xffe39a });
  lampadas.sort((a, b) => Math.atan2(a.x, a.z) - Math.atan2(b.x, b.z));
  for (let i = 0; i < lampadas.length - 1; i++) { const a = lampadas[i], b = lampadas[i + 1];
    for (let k = 1; k < 14; k++) { const f = k / 14, pt = a.clone().lerp(b, f); pt.y -= Math.sin(f * Math.PI) * .9;
      const m = new THREE.Mesh(bolinha, matLuz); m.position.copy(pt); cena.add(m); } }
  [[-6, -6], [6, -6]].forEach(([x, z]) => { const l = new THREE.PointLight(0xffc06b, 22, 16); l.position.set(x, 3.5, z + 10); cena.add(l); });

  // Edifício Aura ao fundo, com janelas acesas
  const jc = document.createElement("canvas"); jc.width = 256; jc.height = 512; const jg = jc.getContext("2d");
  jg.fillStyle = COR.tijolo; jg.fillRect(0, 0, 256, 512);
  for (let r = 0; r < 14; r++) for (let k = 0; k < 6; k++) {
    jg.fillStyle = Math.random() < .6 ? "#ffd86b" : "#8a4a2a"; jg.fillRect(14 + k * 40, 30 + r * 34, 28, 22);
    jg.fillStyle = "#c9734d"; jg.fillRect(10 + k * 40, 52 + r * 34, 36, 4);
  }
  const fachada = new THREE.MeshStandardMaterial({ map: textura(jc), emissive: 0xffb050, emissiveIntensity: .35, emissiveMap: textura(jc) });
  const corpoPredio = new THREE.MeshStandardMaterial({ color: COR.predioEsc });
  [[-16, 15, 9], [0, 19, 12], [16, 14, 8]].forEach(([x, h, w], i) => {
    const t = new THREE.Mesh(new THREE.BoxGeometry(w, h, 7), [corpoPredio, corpoPredio, corpoPredio, corpoPredio, fachada, corpoPredio]);
    t.position.set(x, h / 2, -RAIO - 16 - (i === 1 ? 3 : 0)); cena.add(t);
  });
  const placa = etiqueta("🔥 EDIFÍCIO AURA", { tam: 64 }); placa.position.set(0, 21, -RAIO - 18); placa.scale.multiplyScalar(3.4); cena.add(placa);
  return { borda };
}

function montarTelao(cena, D) {
  const g = new THREE.Group(); g.position.set(0, 0, -3.2); cena.add(g);
  const ferro = new THREE.MeshStandardMaterial({ color: 0x3a1e0c, roughness: .5, metalness: .4 });
  [-4.7, 4.7].forEach((x) => { const p = new THREE.Mesh(new THREE.BoxGeometry(.4, 7.6, .4), ferro); p.position.set(x, 3.8, 0); g.add(p); });
  const moldura = new THREE.Mesh(new THREE.BoxGeometry(9.6, 6.2, .5), ferro); moldura.position.y = 4.6; g.add(moldura);
  const matTela = new THREE.MeshBasicMaterial({ map: null });
  const tela = new THREE.Mesh(new THREE.PlaneGeometry(9, 5.6), matTela); tela.position.set(0, 4.6, .27); g.add(tela);
  const tras = new THREE.Mesh(new THREE.PlaneGeometry(9, 5.6), matTela); tras.position.set(0, 4.6, -.27); tras.rotation.y = Math.PI; g.add(tras);
  const chama = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.TextureLoader().load("img/chama_campea.png"), transparent: true }));
  chama.material.map.colorSpace = THREE.SRGBColorSpace; chama.scale.set(2, 2, 1); chama.position.set(0, 8.6, 0); g.add(chama);
  const posters = [-1, 1].map((lado) => {
    const m = new THREE.MeshBasicMaterial({ map: null });
    const pg = new THREE.Group(); pg.position.set(lado * 8, 0, -2); pg.rotation.y = lado * -.25; cena.add(pg);
    const haste = new THREE.Mesh(new THREE.BoxGeometry(.25, 3, .25), ferro); haste.position.y = 1.5; pg.add(haste);
    const face = new THREE.Mesh(new THREE.PlaneGeometry(3, 3.8), m); face.position.y = 4.4; pg.add(face);
    return m;
  });
  const atualizar = (D) => {
    const rk = (D && D.ranking) || [];
    const top = rk[0];
    matTela.map && matTela.map.dispose();
    matTela.map = painel(top ? [["👑 TOP 1 DO MÊS", 64, "#ffd23f"], ["@" + top.u, 92], [top.n + " AURAs", 58, "#ffe3a3"]]
                             : [["👑 TOP 1 DO MÊS", 64, "#ffd23f"], ["vaga livre!", 92], ["comente AURA e seja o 1º", 46, "#ffe3a3"]],
                         { img: top ? carregarImg(`img/corpo${top.p}.png`) : null });
    matTela.needsUpdate = true;
    posters.forEach((m, i) => { const x = rk[i + 1]; m.map && m.map.dispose();
      m.map = painel(x ? [["#" + (i + 2), 120, "#ffd23f"], ["@" + x.u, 46], [x.n + " AURAs", 40, "#ffe3a3"]] : [["#" + (i + 2), 120, "#ffd23f"], ["vaga", 56]],
                     { w: 512, h: 650, img: x ? carregarImg(`img/corpo${x.p}.png`) : null }); m.needsUpdate = true; });
  };
  atualizar(D);
  return { atualizar, chama };
}

/* quem anda na praça: SÓ quem chegou nas últimas 24h ou está ativo agora (lista "praca" que o motor manda).
   Quando o banco tiver tempo real, entra também quem está online de verdade. */
function escolherGente(D) {
  return ((D && D.praca) || []).slice(0, MAX_MORADORES);
}

export function abrir(host, ctx) {
  if (estado) { estado.ligar(); estado.sincronizar(ctx.D()); return estado; }
  const cena = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, host.clientWidth / host.clientHeight, .1, 300);
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, innerWidth < 700 ? 1.25 : 1.5));
  renderer.setSize(host.clientWidth, host.clientHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  host.appendChild(renderer.domElement);
  const enquadrar = () => { const asp = host.clientWidth / host.clientHeight; camera.aspect = asp; camera.fov = asp < .8 ? 64 : 50; camera.updateProjectionMatrix(); };
  const celular = host.clientWidth / host.clientHeight < .8;
  camera.position.set(0, celular ? 10 : 13, celular ? 21 : 26); enquadrar();
  const controles = new OrbitControls(camera, renderer.domElement);
  controles.target.set(0, 2.2, celular ? 3 : 1); controles.enablePan = false; controles.enableDamping = true;
  controles.minDistance = 9; controles.maxDistance = 44; controles.minPolarAngle = .45; controles.maxPolarAngle = 1.32;
  controles.autoRotate = true; controles.autoRotateSpeed = .35;
  controles.addEventListener("start", () => { controles.autoRotate = false; });

  const { borda } = montarCenario(cena);
  const telao = montarTelao(cena, ctx.D());

  let pessoas = [];
  const sincronizar = (D) => {
    const gente = escolherGente(D), nomes = new Set(gente.map((m) => m.u));
    pessoas = pessoas.filter((p) => { const fica = p.figurante ? false : nomes.has(p.u) || p.eu; if (!fica) cena.remove(p.g); return fica; });
    for (const m of gente) if (!pessoas.some((p) => p.u === m.u && !p.eu)) pessoas.push(criarPessoa(cena, { u: m.u, p: m.p || 1, v: m.v || 0 }));
    const faltam = Math.max(0, 3 - pessoas.filter((p) => !p.eu).length);   // praça vazia: 3 passantes sem @
    for (let i = 0; i < faltam; i++) pessoas.push(criarPessoa(cena, { p: 1 + Math.floor(Math.random() * 20), figurante: true }));
    telao.atualizar(D);
  };
  sincronizar(ctx.D());

  /* o meu boneco (só quem entrou com @ + senha) */
  let eu = null;
  const anel = new THREE.Mesh(new THREE.RingGeometry(.7, .9, 32), new THREE.MeshBasicMaterial({ color: 0xffd23f, side: THREE.DoubleSide, transparent: true }));
  anel.rotation.x = -Math.PI / 2; anel.visible = false; cena.add(anel);
  const alvoMarca = new THREE.Mesh(new THREE.RingGeometry(.25, .4, 24), new THREE.MeshBasicMaterial({ color: 0xff7a1a, side: THREE.DoubleSide, transparent: true }));
  alvoMarca.rotation.x = -Math.PI / 2; alvoMarca.visible = false; cena.add(alvoMarca);
  const entrarComo = (u, p) => {
    if (eu) { cena.remove(eu.g); pessoas = pessoas.filter((x) => x !== eu); }
    const outro = pessoas.find((x) => x.u === u); if (outro) { cena.remove(outro.g); pessoas = pessoas.filter((x) => x !== outro); }
    eu = criarPessoa(cena, { u, p }); eu.eu = true; eu.g.position.set(0, 0, RAIO - 3); eu.alvo = eu.g.position.clone(); eu.vel = 3.6;
    pessoas.push(eu); anel.visible = true; falar(eu, "🎉 Cheguei!", relogio.elapsedTime);
  };
  const sair = () => { if (!eu) return; cena.remove(eu.g); pessoas = pessoas.filter((x) => x !== eu); eu = null; anel.visible = false; alvoMarca.visible = false; };

  /* toque: num boneco abre o apê; no chão, anda (se for o meu) */
  const ray = new THREE.Raycaster(), ponteiro = new THREE.Vector2(), chao = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  let ini = null;
  renderer.domElement.addEventListener("pointerdown", (e) => { ini = { x: e.clientX, y: e.clientY }; });
  renderer.domElement.addEventListener("pointerup", (e) => {
    if (!ini || Math.hypot(e.clientX - ini.x, e.clientY - ini.y) > 8) return;
    const r = renderer.domElement.getBoundingClientRect();
    ponteiro.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
    ray.setFromCamera(ponteiro, camera);
    const alvos = pessoas.filter((p) => p.u && !p.eu).map((p) => p.corpo);
    const hit = ray.intersectObjects(alvos, false)[0];
    if (hit) { const p = pessoas.find((x) => x.corpo === hit.object); if (p) { ctx.abrirApe(p.u); return; } }
    if (eu) {
      const ponto = new THREE.Vector3(); if (!ray.ray.intersectPlane(chao, ponto)) return;
      if (ponto.length() > RAIO - .5) ponto.setLength(RAIO - .5);
      eu.alvo.copy(ponto); eu.parado = 0; alvoMarca.position.set(ponto.x, .03, ponto.z); alvoMarca.visible = true;
    }
  });

  const relogio = new THREE.Clock();
  let rodando = true, frame = 0, proxConversa = 3;
  const v = new THREE.Vector3(), tela = new THREE.Vector3();
  const animar = () => {
    if (!rodando) return;
    frame = requestAnimationFrame(animar);
    const dt = Math.min(relogio.getDelta(), .05), t = relogio.elapsedTime;
    for (const p of pessoas) {
      v.subVectors(p.alvo, p.g.position); v.y = 0;
      const dist = v.length();
      if (dist > .08 && p.parado <= 0) {
        v.setLength(Math.min(dist, p.vel * dt)); p.g.position.add(v);
        // vira o desenho pro lado em que está andando (na tela)
        tela.copy(p.alvo).project(camera); const xAlvo = tela.x; tela.copy(p.g.position).project(camera);
        if (Math.abs(xAlvo - tela.x) > .002) p.esq = xAlvo < tela.x;
        const passo = Math.abs(Math.sin(t * 9 * p.vel + p.fase));
        p.corpo.position.y = passo * .12; p.corpo.material.rotation = Math.sin(t * 9 * p.vel + p.fase) * .06;
      } else {
        p.corpo.position.y = 0; p.corpo.material.rotation = Math.sin(t * 1.6 + p.fase) * .025;   // "respira" parado
        if (!p.eu) { p.parado -= dt; if (p.parado <= -1 && Math.random() < dt * .6) { p.alvo = pontoAleatorio(); p.parado = 0; } else if (p.parado <= 0 && dist <= .08) p.parado = 1.5 + Math.random() * 5; }
        else if (dist <= .08) alvoMarca.visible = false;
      }
      const sx = Math.abs(p.corpo.scale.x); p.corpo.scale.x = p.esq ? -sx : sx;
      if (p.balao && t > p.balaoAte) { p.g.remove(p.balao); p.balao.material.map.dispose(); p.balao.material.dispose(); p.balao = null; }
    }
    if (t > proxConversa) {           // de vez em quando alguém solta um balão (frases prontas)
      const outros = pessoas.filter((p) => !p.eu && !p.balao);
      if (outros.length) falar(outros[Math.floor(Math.random() * outros.length)], FRASES[Math.floor(Math.random() * FRASES.length)], t, 3.2);
      proxConversa = t + 2.5 + Math.random() * 4;
    }
    if (eu) { anel.position.set(eu.g.position.x, .03, eu.g.position.z); anel.material.opacity = .65 + Math.sin(t * 3.2) * .3; }
    borda.material.color.setHSL(.07, 1, .5 + Math.sin(t * 2) * .06);
    telao.chama.scale.set(2 + Math.sin(t * 6) * .12, 2 + Math.sin(t * 5) * .18, 1);
    controles.update(); renderer.render(cena, camera);
  };
  animar();
  const redimensionar = () => { if (!host.clientWidth) return; enquadrar(); renderer.setSize(host.clientWidth, host.clientHeight); };
  addEventListener("resize", redimensionar);

  estado = {
    ligar() { if (!rodando) { rodando = true; relogio.getDelta(); redimensionar(); animar(); } },
    desligar() { rodando = false; cancelAnimationFrame(frame); },
    sincronizar, entrarComo, sair,
    falar(texto) { if (eu) falar(eu, texto, relogio.elapsedTime); },
    get eu() { return eu; },
    FRASES,
  };
  return estado;
}
