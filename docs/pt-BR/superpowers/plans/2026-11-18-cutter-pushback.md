# Plano de implementação do pushback do cortador

[English](../../../superpowers/plans/2026-11-18-cutter-pushback.md) | **Português brasileiro**

> Execute localmente, tarefa por tarefa, com desenvolvimento orientado a testes.
> Este plano não autoriza instalação ou movimentos na impressora, commits nem
> alterações de firmware.

**Objetivo:** reposicionar o fragmento cortado com avanço limitado a 10 mm e
retorno, enquanto a BMCU acompanha o direct drive sem acumular folga no tubo.

**Arquitetura:** adicionar a operação ao fluxo existente de retirada com cortador.
Reutilizar o controlador de pressão nativo `MOTION_BEFORE_PULL_BACK`, que acompanha
os dois sentidos do filamento, e as verificações existentes de retirada
incremental, sessão, sensor e buffer. Adicionar verificações simétricas do encoder
somente para o pushback.

**Tecnologias:** Python, G-code do Klipper, BMCU-Klipper 1.1.2 / firmware 1.0.4.

**Especificação:** o desenho abaixo reflete o esclarecimento do usuário e o curso
proposto de 1 cm.

<a id="design"></a>
## Desenho

- Somente um ciclo de corte concluído pode levar ao pushback, após comandar a
  liberação da lâmina e mover para a posição existente de purga.
- Perfis novos solicitam 10 mm a 120 mm/min nos dois sentidos. Perfis existentes
  sem `pushback_mm` mantêm seu comportamento até serem atualizados explicitamente.
  Zero desabilita o pushback; distâncias positivas não podem superar 10 mm.
- Não alterar recuo pré-corte, temperatura, corrente dos motores, alvos nativos
  do buffer nem distâncias de captura, purga ou estacionamento.
- Usar o mesmo modo nativo de assistência por pressão nos dois sentidos: o
  controlador do firmware alimenta ou recolhe conforme o buffer, sem reposição
  para o alvo normal de impressão nem troca artificial do sentido do motor.
- Mover nos incrementos limitados existentes, mantendo uma única referência de
  encoder e comando no avanço, retorno e retirada final. Aguardar antes de um
  incremento que excederia a tolerância existente de 2 mm de diferença.
- Também aguardar o buffer dentro da faixa simétrica de segurança derivada de
  `unload_buffer_limit` (30–70% com o ajuste existente de 70%).
- Parar por diferença excessiva, telemetria inválida, perda de sessão/sensor,
  assistência parada, resfriamento ou tempo esgotado. Nunca repetir nem compensar
  automaticamente um pushback com falha, nem confirmá-lo como estacionado.
- Os testes comprovam comportamento de software, não movimento físico do
  fragmento, ausência de heat creep nem proteção contra toda falha mecânica
  possível no PTFE.

<a id="review-focus"></a>
## Foco da revisão

- Um alimentador travado em qualquer sentido não pode consumir todo o curso
  de 10 mm.
- Excesso de alimentação ou encoder no sentido oposto interrompem antes de
  outro movimento.
- Diferença residual do encoder não é apagada ao inverter ou iniciar a retirada
  final.
- Perfis antigos calibrados não adquirem novos movimentos físicos silenciosamente.
- Testes frios/a seco, cortes com falha, todos os canais e falhas de sensor/sessão
  continuam seguros; retirada e estacionamento normais preservam seus contratos.

<a id="task-1-profile-and-synchronized-pushback"></a>
## Tarefa 1: Perfil e pushback sincronizado

**Arquivos:** `integrations/bmcu/bmcu_cortador_ender.py`,
`integrations/bmcu/bmcu_ender_integration.py`,
`config/ender3-v3-se-validada/bmcu-cortador.cfg`,
`test/bmcu_integracao/test_cutter_pushback.py`,
`test/bmcu_integracao/test_cutter_safety.py`.

- [x] Escrever testes para o avanço e retorno de 10 mm, reutilização do modo
  nativo, alimentador parado no corte, retirada líquida inalterada e preservação
  dos perfis antigos/desabilitados.
- [x] Executar os testes e confirmar falhas pela ausência da funcionalidade.
- [x] Adicionar os ajustes validados `pushback_mm` e `pushback_feedrate`; estender
  o helper de movimento existente com proteção simétrica de acompanhamento
  habilitada explicitamente.
- [x] Adicionar pushback à retirada com cortador, com diagnóstico de progresso
  por sentido e sem redefinir a referência do encoder antes da retirada seguinte.
- [x] Exercitar encoder travado, atrasado ou no sentido errado, limites de buffer,
  cursos interrompidos, reinício do firmware, perda de sensor, resfriamento e
  falhas nos comandos da lâmina.
- [x] Executar testes específicos e depois as duas suítes Python do repositório.

<a id="task-2-instructions-and-final-verification"></a>
## Tarefa 2: Instruções e verificação final

**Arquivos:** `docs/Ender3_V3_SE_Cutter.md`,
`docs/pt-BR/Ender3_V3_SE_Cutter.md`, este plano.

- [x] Documentar valores dos perfis novos, adesão explícita nos perfis preservados,
  acompanhamento bidirecional nativo, interrupção por falha e limites físicos.
- [x] Executar verificações de diff/estilo e revisar a alteração completa.
- [x] Solicitar a revisão final externa obrigatória com Sol e tratar achados
  concretos.
- [x] Relatar validação de software separadamente dos testes físicos não feitos.

<a id="verification-evidence"></a>
## Evidências da verificação

- Referência inicial da integração: 341 testes aprovados.
- Os novos testes de pushback falharam pela ausência da funcionalidade antes
  da implementação.
- Suíte de integração antes da revisão: 359 testes aprovados no WSL Ubuntu 22.04.
- Suíte final da tela: 82 testes aprovados no mesmo ambiente.
- Suítes específicas do cortador: 82 testes aprovados.
- `git diff --check` aprovado. A verificação direta de whitespace no Linux
  identifica caracteres CRLF existentes neste checkout do Windows. O verificador
  completo `bash scripts/check_whitespace.sh` passou numa cópia pública de 2.540
  arquivos com finais LF, incluindo os dois arquivos novos.
- Nenhuma conexão com a impressora, instalação, reinício de serviço ou teste
  físico.
- A revisão externa com Sol apontou um P2: a taxa padrão do pushback inativo era
  comparada incorretamente com limites baixos de extrusora nos perfis preservados.
  A comparação agora inclui essa taxa somente quando o pushback está habilitado.
  Uma regressão reproduziu a falha com distância ausente e zero antes da correção,
  e depois passou. Suíte específica do pushback: 19 testes aprovados.
  Esta correção localizada de compatibilidade não introduz movimento físico novo.
- Verificação completa após a correção: 360 testes de integração e 82 da tela
  aprovados. O verificador de whitespace passou em cópias LF dos oito arquivos
  alterados; `git diff --check` também passou.
