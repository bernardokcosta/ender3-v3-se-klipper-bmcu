import configparser
import unittest

from jinja2 import Environment

from test_integracao import Gcmd, ROOT, installer
from test_manual_controls import ManualBench

COMANDO = 'BMCU_ENDER_POSICIONAR_PURGA'


class AquecimentoTests(unittest.TestCase):
    def test_inicio_aguarda_temperatura_final_sobre_a_purga(self):
        pasta = ROOT / 'config/ender3-v3-se-validada'
        casos = (
            ('impressao.cfg', 'ENDER_INICIAR_IMPRESSAO'),
            ('bmcu-multicor-ender.cfg', 'ENDER_INICIAR_MULTICOR'),
        )
        ambiente = Environment(
            block_start_string='{%',
            block_end_string='%}',
            variable_start_string='{',
            variable_end_string='}',
        )
        for arquivo, macro in casos:
            with self.subTest(macro=macro):
                parser = configparser.RawConfigParser()
                parser.read(pasta / arquivo)
                texto = ambiente.from_string(
                    parser['gcode_macro ' + macro]['gcode']
                ).render(
                    params={
                        'TEMP_MESA': 80,
                        'TEMP_BICO': 230,
                        'FERRAMENTA': 3,
                    },
                    printer={'bmcu': {'loaded_tools': {'bmcu0:2': 3}}},
                )
                bancada = ManualBench(loaded=2)
                bancada.extruder.max_e_dist = 50
                bancada.temperature = 150
                bancada.obj.purge_x = -5
                bancada.obj.purge_y = 125
                posicionou = aqueceu = False
                for linha in texto.splitlines():
                    linha = linha.strip()
                    if linha == COMANDO:
                        bancada.obj.posicionar_para_aquecimento(Gcmd())
                        posicionou = True
                    elif linha.startswith('M109 S230'):
                        self.assertTrue(posicionou)
                        self.assertEqual([-5, 125], bancada.position[:2])
                        self.assertTrue(bancada.commands[-1].endswith('M400'))
                        self.assertEqual(0, bancada.e)
                        bancada.temperature = 230
                        aqueceu = True
                    elif linha.startswith('M104 S'):
                        self.assertLessEqual(float(linha.split('S')[1]), 150)
                    else:
                        bancada.execute(linha)
                self.assertTrue(aqueceu)
                if macro == 'ENDER_INICIAR_IMPRESSAO':
                    self.assertEqual([5.6, 20], bancada.position[:2])

    def test_posicionamento_frio_nao_libera_extrusao_nem_muda_alvo(self):
        bancada = ManualBench()
        bancada.obj.posicionar_para_aquecimento(Gcmd())
        self.assertEqual([-6, 123], bancada.position[:2])
        self.assertEqual(0, bancada.e)
        self.assertEqual(0, bancada.target)
        with self.assertRaisesRegex(RuntimeError, 'Heat the nozzle'):
            bancada.obj.position_head()

    def test_operacao_ativa_ou_sem_homing_nao_posiciona(self):
        for motivo in ('ocupada', 'sem_homing'):
            bancada = ManualBench()
            if motivo == 'ocupada':
                bancada.bmcu.active_operations = {'bmcu0': {}}
            else:
                bancada.homed_axes = ''
            with self.assertRaises(RuntimeError):
                bancada.obj.posicionar_para_aquecimento(Gcmd())
            self.assertEqual([], bancada.commands)

    def test_migracao_multicor_preserva_ajustes_e_outros_macros(self):
        antigo = installer.CONFIGURATION.replace('  ' + COMANDO + '\n', '')
        antigo = antigo.replace('purga_mm: 35', 'purga_mm: 29')
        extra = '\n[gcode_macro PERSONALIZADO]\ngcode:\n  M117 Teste\n'
        atualizado = installer.corrigir_aquecimento_inicio(
            antigo + extra, 'ENDER_INICIAR_MULTICOR'
        )
        self.assertIn('purga_mm: 29', atualizado)
        self.assertTrue(atualizado.endswith(extra))
        self.assertIn('  ' + COMANDO + '\n  M109 S{nozzle_temp}', atualizado)
        self.assertEqual(
            atualizado,
            installer.corrigir_aquecimento_inicio(
                atualizado, 'ENDER_INICIAR_MULTICOR'
            ),
        )

    def test_migracao_monocor_preserva_linha_de_preparacao(self):
        atual = (
            ROOT / 'config/ender3-v3-se-validada/impressao.cfg'
        ).read_text()
        antigo = atual.replace('  ' + COMANDO + '\n', '').replace(
            '  M109 S{nozzle_temp}\n  G1 X5 Y20 F6000\n',
            '  G1 X5 Y20 F6000\n  M109 S{nozzle_temp}\n',
        )
        atualizado = installer.corrigir_aquecimento_inicio(
            antigo, 'ENDER_INICIAR_IMPRESSAO', monocor=True
        )
        self.assertEqual(atual, atualizado)
        self.assertEqual(
            atualizado,
            installer.corrigir_aquecimento_inicio(
                atualizado, 'ENDER_INICIAR_IMPRESSAO', monocor=True
            ),
        )

    def test_inicio_desconhecido_exige_revisao_sem_alterar_texto(self):
        for linha in ('M109 S{outra_temperatura}', 'G1 X8 Y22 F6000'):
            antigo = (
                '[gcode_macro ENDER_INICIAR_IMPRESSAO]\ngcode:\n'
                '  G1 X5 Y20 F6000\n  M109 S{nozzle_temp}\n'
            )
            if linha.startswith('M109'):
                antigo = antigo.replace('M109 S{nozzle_temp}', linha)
            else:
                antigo = antigo.replace('G1 X5 Y20 F6000', linha)
            with self.assertRaisesRegex(RuntimeError, 'Revise manualmente'):
                installer.corrigir_aquecimento_inicio(
                    antigo, 'ENDER_INICIAR_IMPRESSAO', monocor=True
                )


if __name__ == '__main__':
    unittest.main()
