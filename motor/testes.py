"""Testes das regras do Edifício Aura. Rode: python testes.py"""
import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import motor as M

T0 = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
H = M.CONFIG["horas_por_aura"]


def c(i, u, txt, minutos):
    return {"id": f"c{i}", "username": u, "text": txt, "timestamp": M.iso(T0 + timedelta(minutes=minutos))}


class Regras(unittest.TestCase):
    def setUp(self):
        self.e = M.estado_vazio()

    def test_le_aura_e_numero(self):
        self.assertEqual(M.ler_comentario("AURA 7"), (True, 7))
        self.assertEqual(M.ler_comentario("aura!!! 🔥"), (True, None))
        self.assertEqual(M.ler_comentario("muita Aura#12 aqui"), (True, 12))
        self.assertEqual(M.ler_comentario("AURA 99"), (True, None))
        self.assertEqual(M.ler_comentario("restaurante"), (False, None))
        self.assertEqual(M.ler_comentario("auramaxx"), (False, None))

    def test_novo_morador_ganha_saldo_inicial(self):
        M.aplicar_lote(self.e, [c(1, "Nina_Pudim", "AURA 10", 0)], T0)
        m = self.e["moradores"]["nina_pudim"]
        self.assertEqual(m["personagem"], 10)
        self.assertEqual(M.de_iso(m["pago_ate"]), M.avancar(T0, M.CONFIG["saldo_inicial_horas"]))
        self.assertAlmostEqual(M.horas_cobradas(T0, M.de_iso(m["pago_ate"])), M.CONFIG["saldo_inicial_horas"])

    def test_comentario_repetido_nao_conta_duas_vezes(self):
        lote = [c(1, "ana", "AURA", 0)]
        M.aplicar_lote(self.e, lote, T0)
        r = M.aplicar_lote(self.e, lote, T0)
        self.assertEqual(r, {"repetido": 1})

    def test_limite_de_um_aura_por_intervalo(self):
        intervalo = M.CONFIG["intervalo_minimo_entre_auras_min"]
        M.aplicar_lote(self.e, [c(1, "ana", "AURA", 0), c(2, "ana", "AURA", 5), c(3, "ana", "AURA", 10)], T0)
        self.assertEqual(len(self.e["moradores"]["ana"]["auras"]), 1)
        M.aplicar_lote(self.e, [c(4, "ana", "AURA", intervalo + 1)], T0)
        self.assertEqual(len(self.e["moradores"]["ana"]["auras"]), 2)

    def test_troca_de_personagem_funciona_mesmo_no_intervalo(self):
        M.aplicar_lote(self.e, [c(1, "ana", "AURA 3", 0), c(2, "ana", "AURA 15", 2)], T0)
        self.assertEqual(self.e["moradores"]["ana"]["personagem"], 15)

    def test_saldo_tem_teto(self):
        passo = M.CONFIG["intervalo_minimo_entre_auras_min"] + 1
        lote = [c(i, "ana", "AURA", i * passo) for i in range(400)]
        fim = T0 + timedelta(minutes=399 * passo)
        M.aplicar_lote(self.e, lote, fim)
        pago = M.de_iso(self.e["moradores"]["ana"]["pago_ate"])
        self.assertLessEqual(M.horas_cobradas(fim, pago), M.CONFIG["saldo_maximo_horas"] + 0.01)

    def test_despejo_e_volta(self):
        M.aplicar_lote(self.e, [c(1, "ze_do_pastel", "AURA 3", 0)], T0)
        m = self.e["moradores"]["ze_do_pastel"]
        fim_saldo = M.de_iso(m["pago_ate"])
        # durante a carência ainda mora lá (aparece ATRASADO)
        self.assertEqual(M.atualizar(self.e, fim_saldo + timedelta(minutes=1)), [])
        depois = M.momento_despejo(m) + timedelta(minutes=1)
        self.assertEqual(M.atualizar(self.e, depois), ["ze_do_pastel"])
        self.assertEqual(self.e["moradores"]["ze_do_pastel"]["status"], "despejado")
        minutos = int((depois - T0).total_seconds() // 60) + 5
        r = M.aplicar_lote(self.e, [c(2, "ze_do_pastel", "aura", minutos)], depois + timedelta(minutes=5))
        self.assertEqual(r, {"voltou": 1})
        self.assertEqual(self.e["moradores"]["ze_do_pastel"]["status"], "ativo")

    def test_ranking_premia_quem_comenta_mais(self):
        lote = [c(1, "ana", "AURA", 0), c(2, "bia", "AURA", 0)]
        passo = M.CONFIG["intervalo_minimo_entre_auras_min"] + 1
        lote += [c(10 + i, "bia", "AURA", passo * (i + 1)) for i in range(3)]
        agora = T0 + timedelta(minutes=passo * 4)
        M.aplicar_lote(self.e, lote, agora)
        self.assertEqual(M.ranking(self.e, agora)[0][0], "bia")
        self.assertEqual(self.e["top1"], "bia")

    def test_ranking_recomeca_no_mes_novo(self):
        passo = M.CONFIG["intervalo_minimo_entre_auras_min"] + 1
        antigo = [c(i, "veterano", "AURA", i * passo) for i in range(30)]  # novembro
        dez = M.proximo_mes(T0)
        inicio_novato = int((dez - T0).total_seconds() // 60) + 60
        novato = [c(100 + i, "novato", "AURA", inicio_novato + i * passo) for i in range(5)]
        manter = [c(200, "veterano", "AURA", inicio_novato)]
        agora = T0 + timedelta(minutes=inicio_novato + 5 * passo)
        M.aplicar_lote(self.e, antigo + manter + novato, agora)
        self.assertEqual(M.ranking(self.e, agora)[0][0], "novato")

    def test_blocos_crescem_sozinhos(self):
        por_bloco = M.CONFIG["andares_por_bloco"] * M.CONFIG["aptos_por_andar"]
        n = por_bloco * 2 + 2  # 1 vai pra cobertura, sobram 2 blocos cheios + 1 morador
        lote = [c(i, f"user{i}", "AURA", 0) for i in range(n)]
        with tempfile.TemporaryDirectory() as d:
            M.aplicar_lote(self.e, lote, T0)
            dados = M.exportar(self.e, T0, Path(d))
            self.assertEqual(dados["total_blocos"], 3)
            self.assertEqual(dados["total_moradores"], n)
            self.assertTrue((Path(d) / "dados.js").exists())

    def test_aluguel_nao_corre_de_madrugada(self):
        fuso = M.FUSO
        if M.PAUSA_INI >= M.PAUSA_FIM:
            self.skipTest("sem pausa noturna")
        onze_da_noite = datetime(2026, 11, 25, 23, 0, tzinfo=fuso)
        fim = M.avancar(onze_da_noite, 2)  # 1h até meia-noite + 1h depois das 8h
        self.assertEqual(fim.astimezone(fuso).hour, M.PAUSA_FIM + 1)
        self.assertAlmostEqual(M.horas_cobradas(onze_da_noite, fim), 2)
        madrugada = datetime(2026, 11, 26, 3, 0, tzinfo=fuso)
        self.assertEqual(M.horas_cobradas(madrugada, madrugada + timedelta(hours=4)), 0)

    def test_reajuste_vale_so_para_novos_comentarios(self):
        tabela = M.CONFIG.setdefault("reajustes", {})
        antigo = dict(tabela)
        try:
            tabela.clear(); tabela.update({"2026-11": 12, "2026-12": 6})
            self.assertEqual(M.valor_aura(T0), 12)
            self.assertEqual(M.valor_aura(M.proximo_mes(T0) + timedelta(hours=1)), 6)
            self.assertEqual(M.valor_aura(M.proximo_mes(M.proximo_mes(T0))), 6)  # mantém o último
        finally:
            tabela.clear(); tabela.update(antigo)

    def test_despejado_vai_para_pracinha(self):
        M.aplicar_lote(self.e, [c(1, "ze_do_pastel", "AURA", 0)], T0)
        depois = M.momento_despejo(self.e["moradores"]["ze_do_pastel"]) + timedelta(minutes=1)
        M.atualizar(self.e, depois)
        with tempfile.TemporaryDirectory() as d:
            dados = M.exportar(self.e, depois, Path(d))
        self.assertEqual([p["u"] for p in dados["pracinha"]], ["ze_do_pastel"])
        self.assertEqual(dados["total_moradores"], 0)

    def test_inquilino_novo_tem_10_dias(self):
        M.aplicar_lote(self.e, [c(1, "ana", "AURA", 0)], T0)
        self.assertEqual(M.atualizar(self.e, T0 + timedelta(days=10)), [])
        self.assertEqual(M.atualizar(self.e, T0 + timedelta(days=12)), [])  # tolerância
        self.assertEqual(M.atualizar(self.e, T0 + timedelta(days=13, minutes=1)), ["ana"])

    def test_usuario_estranho_e_ignorado(self):
        r = M.aplicar_lote(self.e, [c(1, "<script>", "AURA", 0)], T0)
        self.assertEqual(r, {"usuario_invalido": 1})

    def test_salvar_e_carregar(self):
        M.aplicar_lote(self.e, [c(1, "ana", "AURA", 0)], T0)
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "estado.json"
            M.salvar(self.e, arq)
            M.salvar(self.e, arq)
            self.assertTrue((Path(d) / "estado.bak.json").exists())
            self.assertIn("ana", M.carregar(arq)["moradores"])

    def test_escolhe_e_troca_de_regiao(self):
        self.assertEqual(M.ler_regiao("aura 7 sul"), "S")
        self.assertEqual(M.ler_regiao("AURA Centro-Oeste"), "CO")
        self.assertIsNone(M.ler_regiao("aura se liga nesse video muito bom"))
        M.aplicar_lote(self.e, [c(1, "ana", "AURA NE", 0), c(2, "bia", "AURA", 0), c(3, "ana", "aura sul", 1)], T0 + timedelta(hours=2))
        self.assertEqual(self.e["moradores"]["ana"]["regiao"], "S")
        self.assertIsNone(self.e["moradores"]["bia"].get("regiao"))
        with tempfile.TemporaryDirectory() as d:
            dados = M.exportar(self.e, T0 + timedelta(hours=2), Path(d))
        self.assertEqual(dados["regioes"]["S"]["moradores"], 1)
        self.assertEqual(dados["regioes"]["CAP"]["moradores"], 1)
        self.assertEqual(dados["regiao_campea"], "S")
        self.assertEqual(dados["cidades"]["S"]["vip"]["u"], "ana")      # cada região é uma cidade
        self.assertEqual(dados["cidades"]["CAP"]["vip"]["u"], "bia")
        self.assertEqual(dados["cidades"]["N"]["total_moradores"], 0)

    def test_moveis_chegam_por_marcos(self):
        self.assertTrue(all(v == 0 for v in M.moveis_de(0).values()))
        self.assertEqual(M.moveis_de(1)["cama"], 1)
        self.assertEqual({k: M.moveis_de(20)[k] for k in ("cama", "tapete", "sofa")}, {"cama": 2, "tapete": 2, "sofa": 2})
        self.assertEqual(M.proximo_movel(1), ("planta", 1, 1))
        coms = [c(i, "ana", "AURA", i * 200) for i in range(4)]    # 4 AURAs, 1 a cada 3h20
        M.aplicar_lote(self.e, coms, T0 + timedelta(hours=14))
        self.assertEqual(self.e["moradores"]["ana"]["total_auras"], 4)
        with tempfile.TemporaryDirectory() as d:
            f = M.exportar(self.e, T0 + timedelta(hours=14), Path(d))["cidades"]["CAP"]["vip"]
        self.assertEqual((f["tot"], f["br"], f["mv"]["tapete"]), (4, 40, 1))

    def test_ranking_da_semana(self):
        coms = [c(i, "ana", "AURA", i * 200) for i in range(3)] + [c(10, "bia", "AURA", 0)]
        M.aplicar_lote(self.e, coms, T0 + timedelta(hours=12))
        sem = M.ranking_semana(self.e, T0 + timedelta(hours=12))
        self.assertEqual([(x["u"], x["n"]) for x in sem], [("ana", 3), ("bia", 1)])
        self.assertEqual(M.ranking_semana(self.e, T0 + timedelta(days=9)), [])   # passou a semana, zera

    def test_senha_do_quarto(self):
        import hashlib, quartos_db as Q
        s1, s2 = Q.senha_de("Ana", "segredo-teste"), Q.senha_de("ana", "segredo-teste")
        self.assertEqual(s1, s2)                                  # @ com maiúscula dá a mesma senha
        self.assertRegex(s1, r"^\d{6}$")
        self.assertNotEqual(s1, Q.senha_de("bia", "segredo-teste"))
        self.assertNotEqual(s1, Q.senha_de("ana", "outro-segredo"))
        sal, h = Q.embaralhar("ana", " " + s1[:3] + " " + s1[3:] + " ", "segredo-teste")   # aceita espaço no meio
        self.assertEqual(h, hashlib.sha256((sal + s1).encode()).hexdigest())
        M.aplicar_lote(self.e, [c(i, "ana", "AURA", i * 200) for i in range(4)], T0 + timedelta(hours=14))
        (ln,) = Q.linhas(self.e, "segredo-teste")
        self.assertEqual((ln["u"], ln["brasas_ganhas"], ln["presentes"]["tapete"]), ("ana", 40, 1))
        self.assertNotIn(s1, json.dumps(self.e))                  # a senha nunca vai pro estado público


if __name__ == "__main__":
    unittest.main(verbosity=1)
