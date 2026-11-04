# Cortador opcional com servo na Orange Pi

[English: guia completo e referências](Ender3_V3_SE_Cutter.md)

Usamos o [cortador de matarsaed para Ender 3 V3 SE/KE](https://www.printables.com/model/1243521-filament-cutter-for-ender-3-v3-seke), com os [comentários de montagem](https://www.printables.com/model/1243521-filament-cutter-for-ender-3-v3-seke/comments), e uma adaptação do [suporte de servo de jmillerfo](https://www.printables.com/model/1097275-voron-24r2-filametrix-filament-cutter-gantry-servo). Os arquivos CAD e suas licenças continuam nas páginas dos autores.

O servo posiciona o batente; quem pressiona a alavanca é o movimento X do cabeçote. Este perfil exige corte **abaixo das engrenagens da extrusora**. A sobra dentro do hotend será empurrada e purgada pelo próximo filamento. Um cortador acima das engrenagens, deixando uma sobra solta sem tração, exige outra sequência.

## Ligação proposta na Orange Pi Zero 3

| Fio do SG90 | Ligação |
| --- | --- |
| Sinal, normalmente laranja/amarelo | Pino físico 15, PC8, após conferir a disponibilidade |
| GND, normalmente marrom/preto | GND da fonte do servo e GND da Orange Pi, por exemplo pino físico 6 |
| Alimentação, normalmente vermelho | Fonte regulada externa de 5 V, com capacidade para os picos do servo |

Use SG90 posicional, não de rotação contínua. O GPIO fornece sinal de 3,3 V, não alimentação para o motor. Recomenda-se fonte regulada com capacidade de pelo menos 2 A para um SG90. Una os GNDs, mantenha a alimentação da Orange Pi e não injete a fonte externa nos pinos de 5 V da placa. Não ligue o servo em 24 V. O encaixe do SG90 não comprova a durabilidade de suas engrenagens no mecanismo originalmente projetado para MG90S.

O sensor de entrada usa PC15/pino 16 na configuração validada. A UART5 da BMCU deve permanecer intacta. O servo proposto usa PWM por software da MCU Linux; não habilite overlays de PWM nos pinos da UART5. Confira estabilidade do servo com a câmera e a carga normal da Orange Pi antes de confiar em trocas automáticas.

Confira o endereço e se o GPIO está livre:

```sh
sudo gpiodetect
sudo gpioinfo
```

O endereço proposto para PC8 no layout observado é `host:gpiochip1/gpio72`, mas o índice do gpiochip depende do kernel. Pino físico 15 não significa GPIO15. Consulte o pinout e a orientação de GPIO no guia em inglês.

O PC9 (pino físico 7) está ligado à interrupção do controlador de alimentação AXP313A no [device tree da Zero 3 no Linux](https://github.com/torvalds/linux/blob/v6.18/arch/arm64/boot/dts/allwinner/sun50i-h618-orangepi-zero3.dts). Não o use como saída do servo nem desative a interrupção do PMIC para liberá-lo. Ausência de consumidor no `gpioinfo` não comprova disponibilidade como saída: também existem reservas de interrupção e multiplexação. O instalador rejeita o offset 73 quando identifica a Orange Pi Zero 3. A indicação anterior do PC9 estava incorreta.

Se a instalação falhou no PC9, mantenha a configuração restaurada. Desligue as alimentações antes de mover somente o sinal do servo para PC8, mantendo os 5 V e o GND comum. Após ligar e o Klipper ficar pronto, repita a instalação com o endereço conferido do PC8. Se a MCU Linux continuar em shutdown após a restauração, execute `FIRMWARE_RESTART` com a configuração restaurada antes de tentar novamente. Teste o servo somente após a instalação concluir.

## Atualização e calibração

Cancele a impressão, retire manualmente qualquer filamento preso e confirme os canais estacionados/vazios antes da atualização. Faça backup. Após conferir o GPIO:

```sh
cd "$HOME/klipper" &&
git pull --ff-only origin master &&
sudo python3 scripts/ender3-v3-se/install_multicolor.py \
  --cutter-servo-pin host:gpiochip1/gpio72
```

Substitua o endereço se o mapeamento for diferente. A alteração é no host; não exige novo `.bin` da impressora. O instalador faz backup, preserva calibrações e restaura os arquivos anteriores se a inicialização falhar. Sem o argumento do servo, instala o perfil opcional e o reset sem reservar GPIO.

O arquivo `bmcu-cortador.cfg` começa com `habilitado=0` e `calibrado=0`. As coordenadas inválidas de propósito devem ser substituídas por medições. O servo não recebe um ângulo automaticamente ao iniciar.

1. Com o cabeçote fisicamente afastado do batente, use `CORTADOR_SERVO ANGULO=<angulo_seguro> CONFIRMAR=1` para encontrar as posições recolhida e acionada. Se não souber a direção, comece com o braço sem carga mecânica.
2. Edite os ângulos, `variable_x_aproximacao`, `variable_x_corte`, `variable_y_corte` e a folga Z em `bmcu-cortador.cfg`. Meça o curso completo na sua montagem. As coordenadas de purga não são coordenadas de corte. Confira interferências com câmera, ventoinha, hub e mesa sem aumentar limites para esconder colisões.
3. Reinicie o Klipper, comande o ângulo recolhido e faça homing. Com hotend/caminho compartilhado livres e canais estacionados, execute `TESTAR_CORTADOR CONFIRMAR=1`. O teste é mecânico, sem aquecer ou extrudar. Confira corte completo, retorno da mola e recolhimento.
4. Depois do teste, configure `variable_calibrado: 1` e `variable_habilitado: 1` e reinicie. **Após cada reinício**, confira a folga e comande novamente o ângulo recolhido com `CORTADOR_SERVO ... CONFIRMAR=1` antes de `G28` ou carregar/retirar filamento.
5. Faça carga e retirada a quente, confira a ponta cortada e o fluxo no bico, depois repita um teste curto de quatro cores. Não há sensor de posição da lâmina, confirmação de corte ou captura depois das engrenagens: comandos concluídos não comprovam sucesso físico.

Se estiver habilitado sem calibração, sem servo, fora dos limites ou com posição incerta, o sistema interrompe a operação. Ele não volta silenciosamente à formação de ponta. Desabilitado, mantém o fluxo anterior.

Se o servo tremer enquanto mantém o batente recolhido, teste com o cabeçote longe e parado: comande o ângulo recolhido, espere o braço parar e envie `SET_SERVO SERVO=bmcu_cortador WIDTH=0`. Só use `variable_soltar_servo_recolhido: 1` em `[gcode_macro _BMCU_ENDER_CORTADOR_AJUSTES]` se o batente continuar fora de todo o percurso do cabeçote sem o torque do servo, mesmo com vibração. Acrescente a linha se ela não existir e repita o teste mecânico. O PWM fica ligado desde o acionamento até o cabeçote se afastar e o batente recolher; os 5 V continuam ligados. Sem esse ajuste, o servo mantém o PWM na posição recolhida.

Quando houver trecho livre entre o acionamento e a alavanca, registre o primeiro toque em `variable_x_contato`. Nesse caso, `variable_curso_maximo_mm` limita a distância do contato ao corte completo. Com `None` ou sem essa variável, o limite continua valendo desde a aproximação. O avanço e o recuo com o batente acionado usam `variable_corte_f` em todo o trecho.

Use `variable_manter_y_corte: 1` somente quando houver folga para o corte com a mesa em qualquer posição de troca. O corte ignora `variable_y_corte` nesse modo. A purga continua usando a posição já configurada para a calha.

## Velocidade e segurança do caminho

O perfil do cortador elimina a formação térmica da ponta e começa com recuo F600, avanço ao bico F240 e purga F180, em mm/min. A captura e as distâncias existentes são preservadas. A BMCU precisa acompanhar o recuo; a velocidade de recolhimento validada é 10 mm/s. Reduza as velocidades se houver patinação ou fluxo insuficiente, sem aumentar a tolerância de erro do encoder para esconder o problema.

Com `variable_posicionamento_paralelo: 1`, o cabeçote pode ir à purga durante a busca nativa até o switch somente com todos os caminhos livres e sensor de entrada desacionado. A extrusora espera o posicionamento terminar antes da captura. Não se antecipa um segundo filamento em um caminho ocupado ou incerto.

Os tempos podem ser comparados em `unload_timing` e `ultimo_corte` no estado de `bmcu_integracao_ender`. Os testes de software verificam a sequência; os tempos reais e a confiabilidade precisam ser medidos na impressora.

## Reset após retirada manual

Depois de cancelar a impressão e deixar hotend e caminho compartilhado fisicamente livres:

```gcode
RESET_BMCU CONFIRMAR=1
```

O reset para os motores da BMCU e confirma os quatro canais pelo comando nativo: `PARKED` onde a entrada ainda detecta filamento, `EMPTY` onde não detecta. Exige sensor de entrada livre e nenhuma impressão ativa/pausada ou operação da BMCU em andamento. Somente após confirmar todos os canais encerra a sessão antiga e limpa a troca pendente. Uma falha parcial não é anunciada como sucesso.

Não retira filamento fisicamente, não aquece, não desentope, não apaga calibrações e não declara que o servo foi recolhido. Para preservar uma impressão pausada, siga a [recuperação de troca](Ender3_V3_SE_Print_Recovery.md). Se o corte deixou o batente incerto, libere-o fisicamente; `CORTADOR_SERVO` permite recolhê-lo nessa recuperação pausada com confirmação e sem operação da BMCU ativa.
