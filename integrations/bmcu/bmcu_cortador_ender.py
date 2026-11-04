import math
import re


class CortadorEnder:
    def __init__(self, integracao):
        self.integracao = integracao
        self.recolhido = False
        self.incerto = False
        self.ultimo_corte = {}

    def perfil(self):
        macro = self.integracao.printer.lookup_object(
            'gcode_macro _BMCU_ENDER_CORTADOR_AJUSTES', None
        )
        if macro is None:
            return None
        return dict(macro.get_status(self.integracao.reactor.monotonic()))

    def preparar(self, calibracao=False):
        perfil = self.perfil()
        if perfil is None or not perfil.get('habilitado') and not calibracao:
            return None
        perfil.setdefault('soltar_servo_recolhido', 0)
        if any(
            perfil.get(chave) not in (0, 1)
            for chave in (
                'habilitado', 'calibrado', 'posicionamento_paralelo',
                'soltar_servo_recolhido',
            )
        ):
            raise RuntimeError('As opcoes do cortador devem ser 0 ou 1.')
        if not calibracao and not perfil.get('calibrado'):
            raise RuntimeError(
                'Calibre o cortador antes de habilitar as trocas.'
            )
        if self.incerto:
            raise RuntimeError(
                'Cortador em posicao incerta; afaste o cabecote e confirme '
                'o recolhimento pelo comando CORTADOR_SERVO.'
            )
        for chave in (
            'angulo_recolhido',
            'angulo_acionado',
            'x_aproximacao',
            'x_corte',
            'y_corte',
            'z_minimo',
            'alivio_z',
            'curso_maximo_mm',
            'deslocamento_f',
            'corte_f',
            'espera_servo_ms',
            'velocidade_recuo_f',
            'velocidade_avanco_f',
            'velocidade_purga_f',
        ):
            try:
                valor = float(perfil[chave])
            except (KeyError, TypeError, ValueError) as erro:
                raise RuntimeError(
                    'Ajuste do cortador invalido: %s.' % chave
                ) from erro
            if not math.isfinite(valor):
                raise RuntimeError('Ajuste do cortador invalido: %s.' % chave)
            perfil[chave] = valor
        for chave in (
            'alivio_z',
            'curso_maximo_mm',
            'deslocamento_f',
            'corte_f',
            'espera_servo_ms',
            'velocidade_recuo_f',
            'velocidade_avanco_f',
            'velocidade_purga_f',
        ):
            if perfil[chave] <= 0:
                raise RuntimeError(
                    'Ajuste do cortador deve ser positivo: %s.' % chave
                )
        curso = abs(perfil['x_corte'] - perfil['x_aproximacao'])
        if not 0 < curso <= perfil['curso_maximo_mm']:
            raise RuntimeError('Configure um curso de corte dentro do limite.')
        servo = self.servo(perfil)
        for chave in ('angulo_recolhido', 'angulo_acionado'):
            if not 0 <= perfil[chave] <= servo.max_angle:
                raise RuntimeError(
                    'Angulo do cortador fora dos limites do servo.'
                )
        if perfil['angulo_recolhido'] == perfil['angulo_acionado']:
            raise RuntimeError('Os angulos do batente devem ser diferentes.')
        extrusora = self.integracao.printer.lookup_object('extruder')
        if (
            max(
                perfil[chave]
                for chave in (
                    'velocidade_recuo_f',
                    'velocidade_avanco_f',
                    'velocidade_purga_f',
                )
            )
            > extrusora.max_e_velocity * 60
        ):
            raise RuntimeError(
                'Velocidade do perfil excede o limite da extrusora.'
            )
        return perfil

    def servo(self, perfil):
        nome = str(perfil.get('servo', ''))
        if not re.fullmatch(r'[A-Za-z0-9_]+', nome):
            raise RuntimeError('Nome do servo do cortador invalido.')
        servo = self.integracao.printer.lookup_object('servo ' + nome, None)
        if servo is None:
            raise RuntimeError(
                'Instale o servo com --cutter-servo-pin antes de testar.'
            )
        return servo

    def validar_movimento(self, perfil):
        cabecote = self.integracao.printer.lookup_object('toolhead')
        estado = cabecote.get_status(self.integracao.reactor.monotonic())
        if not all(eixo in estado['homed_axes'] for eixo in 'xyz'):
            raise RuntimeError(
                'Execute G28 antes de testar ou acionar o cortador.'
            )
        minimo, maximo = estado['axis_minimum'], estado['axis_maximum']
        for eixo, chaves in (
            (0, ('x_aproximacao', 'x_corte')),
            (1, ('y_corte',)),
        ):
            if any(
                not minimo[eixo] <= perfil[chave] <= maximo[eixo]
                for chave in chaves
            ):
                raise RuntimeError(
                    'Posicao de corte fora dos limites da impressora.'
                )
        posicao = list(cabecote.get_position())
        altura = max(posicao[2] + perfil['alivio_z'], perfil['z_minimo'])
        if not minimo[2] <= altura <= maximo[2]:
            raise RuntimeError('Nao ha altura livre para acionar o cortador.')
        return cabecote, posicao, altura

    def posicionar_servo(self, perfil, angulo):
        self.integracao.execute(
            'SET_SERVO SERVO=%s ANGLE=%.6f' % (perfil['servo'], angulo)
        )
        cabecote = self.integracao.printer.lookup_object('toolhead')
        cabecote.dwell(perfil['espera_servo_ms'] / 1000)
        cabecote.wait_moves()

    def posicionar_recolhido(self, perfil):
        self.recolhido = False
        self.incerto = True
        self.posicionar_servo(perfil, float(perfil['angulo_recolhido']))
        if perfil.get('soltar_servo_recolhido') == 1:
            self.integracao.execute(
                'SET_SERVO SERVO=%s WIDTH=0' % perfil['servo']
            )
        self.recolhido = True
        self.incerto = False

    def recolher(self, perfil):
        if self.recolhido:
            return
        cabecote, posicao, altura = self.validar_movimento(perfil)
        sentido = math.copysign(1, perfil['x_corte'] - perfil['x_aproximacao'])
        if (posicao[0] - perfil['x_aproximacao']) * sentido > 0.05:
            raise RuntimeError(
                'Afaste o cabecote do batente antes de recolher o servo.'
            )
        self.posicionar_recolhido(perfil)

    def mover(self, cabecote, coordenadas, velocidade):
        with self.integracao.bmcu.printer_critical_section('cortador_ender'):
            cabecote.manual_move(coordenadas, velocidade / 60)
            cabecote.wait_moves()

    def cortar(self, perfil, verificar, retornar=True):
        cabecote, origem, altura = self.validar_movimento(perfil)
        inicio = self.integracao.reactor.monotonic()
        self.recolher(perfil)
        try:
            verificar()
            self.mover(cabecote, [None, None, altura], 300)
            self.mover(
                cabecote,
                [perfil['x_aproximacao'], perfil['y_corte'], None],
                perfil['deslocamento_f'],
            )
            verificar()
            self.incerto = True
            self.recolhido = False
            self.posicionar_servo(perfil, perfil['angulo_acionado'])
            verificar()
            self.mover(
                cabecote, [perfil['x_corte'], None, None], perfil['corte_f']
            )
            verificar()
            self.mover(
                cabecote,
                [perfil['x_aproximacao'], None, None],
                perfil['corte_f'],
            )
            self.posicionar_recolhido(perfil)
            verificar()
            if retornar:
                self.mover(
                    cabecote,
                    [origem[0], origem[1], None],
                    perfil['deslocamento_f'],
                )
            self.ultimo_corte = {
                'resultado': 'comandos_concluidos',
                'segundos': self.integracao.reactor.monotonic() - inicio,
            }
        except Exception:
            self.ultimo_corte = {
                'resultado': 'interrompido',
                'posicao_incerta': self.incerto,
            }
            raise

    def servo_manual(self, gcmd):
        if gcmd.get_int('CONFIRMAR', 0, minval=0, maxval=1) != 1:
            raise gcmd.error('Confira a folga do batente e use CONFIRMAR=1.')
        estado = (
            self.integracao.printer.lookup_object('print_stats')
            .get_status(self.integracao.reactor.monotonic())
            .get('state')
        )
        recuperacao = bool(
            self.incerto
            and getattr(self.integracao, 'pending_tool_change', None)
        )
        if (
            estado == 'printing'
            or estado in ('paused', 'pause')
            and not recuperacao
            or (
                self.integracao.bmcu.active_operations
                or self.integracao.manual_operation is not None
            )
        ):
            raise gcmd.error('Finalize a operacao antes de testar o servo.')
        perfil = self.perfil()
        if perfil is None:
            raise gcmd.error('Instale bmcu-cortador.cfg antes de testar.')
        servo = self.servo(perfil)
        angulo = float(gcmd.get('ANGULO'))
        if not math.isfinite(angulo) or not 0 <= angulo <= servo.max_angle:
            raise gcmd.error('Angulo fora dos limites do servo.')
        espera = float(perfil.get('espera_servo_ms', 500))
        if not math.isfinite(espera) or espera <= 0:
            raise gcmd.error('Espera do servo invalida.')
        perfil['espera_servo_ms'] = espera
        if math.isclose(
            angulo, float(perfil['angulo_recolhido']), abs_tol=0.01
        ):
            self.posicionar_recolhido(perfil)
        else:
            self.posicionar_servo(perfil, angulo)
            self.recolhido = False
        gcmd.respond_info(
            'Servo comandado a %.1f graus; confira a posicao fisica.' % angulo
        )

    def testar(self, gcmd):
        if gcmd.get_int('CONFIRMAR', 0, minval=0, maxval=1) != 1:
            raise gcmd.error('Confira o percurso livre e use CONFIRMAR=1.')
        dispositivo, destino, carregado = self.integracao.manual_context()
        if carregado is not None:
            raise gcmd.error('Retire o filamento antes do teste mecanico.')
        perfil = self.preparar(calibracao=True)
        if perfil is None:
            raise gcmd.error('Instale o perfil do cortador antes de testar.')
        sessao = dispositivo.status['session_id']

        def verificar():
            self.integracao.check_manual_operation()
            dispositivo.refresh()
            if dispositivo.status[
                'session_id'
            ] != sessao or self.integracao.sensor(destino):
                raise RuntimeError(
                    'A BMCU reiniciou ou o caminho deixou de estar livre.'
                )

        self.integracao.manual_operation = 'TESTE_CORTADOR'
        try:
            origem = list(
                self.integracao.printer.lookup_object(
                    'toolhead'
                ).get_position()
            )
            self.cortar(perfil, verificar)
            self.mover(
                self.integracao.printer.lookup_object('toolhead'),
                [None, None, origem[2]],
                300,
            )
        finally:
            self.integracao.manual_operation = None
        gcmd.respond_info(
            'Teste concluido; confira o corte e o recolhimento '
            'antes de calibrado=1.'
        )
