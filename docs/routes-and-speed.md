# Caminhos e velocidade do tráfego

Atualização de 14/11/2026 para Burnout 3 USA `SLUS-21050` / CRC `BEBF8793`
no PCSX2 1.7.2521. Esta etapa melhora a leitura e a edição do evento carregado;
não cria a malha de uma nova rua nem altera os recursos do ISO.

## Ver os caminhos

1. Conecte o editor, pause o PCSX2 e use **Atualizar lista**.
2. Abra **Vista de cima** e mantenha **Mostrar vias** ligado.
3. Selecione um veículo e use o enquadramento de seu caminho para acompanhar
   a faixa que ele percorre. O caminho selecionado fica destacado.
4. Use o zoom e o deslocamento da vista para examinar cruzamentos, curvas e
   trechos que ficam além dos veículos visíveis naquele instante.

O desenho mostra as duas bordas e o centro aproximado das faixas de tráfego
carregadas. Os identificadores `P…` distinguem os caminhos. As setas indicam
**progressão crescente no caminho**; elas não estabelecem, por si só, uma rede
de conexões entre ruas nem o sentido permitido para o carro do jogador.

Há uma distinção entre caminhos com referência de veículo e descritores
candidatos sem referência observada. Um candidato passa por verificações de
identidade e geometria, mas isso não comprova que o evento use aquele trecho,
que ele esteja conectado ao próximo ou que a criação ali seja compatível.
A direção do tráfego só recebe confirmação quando uma referência móvel
corrobora a orientação do caminho.

As curvas são amostradas, e a leitura usa limites de memória e quantidade de
pontos. Uma leitura parcial pode omitir caminhos; o aviso do mapa informa essa
limitação. O desenho não representa o asfalto, a geometria de colisão, prédios,
obstáculos ou um mapa completo do cenário. Cruzamentos em X/Z podem estar em
alturas diferentes. Os dados correspondem à última leitura pausada e precisam
ser atualizados depois que o jogo voltar a simular.

**Adicionar no ponto** continua usando uma projeção aproximada em um caminho
admitido, com a altura de sua geometria. Marcar X/Z não escolhe um terreno novo
nem define Y livremente. A visualização de um descritor candidato também não
o transforma automaticamente numa referência válida para criar veículos.

## Ler a velocidade

Ao selecionar um veículo com nó de tráfego reconhecido, a interface separa o
**alvo nominal** do **seguimento nominal**. Os valores podem divergir:

| Informação | Significado pesquisado | Uso no editor |
| --- | --- | --- |
| Controle original, no nó `+0` | Alvo usado pelo controlador de tráfego | Pode ser alterado com as verificações do perfil |
| Avanço, no nó `+0x2c` | Valor que o jogo usa para avançar pelo caminho, após seu controle de tráfego | Somente leitura |
| Campo separado, no nó `+0x24` | Argumento preservado do criador; seu significado completo não foi fechado nesta etapa | Preservado, sem tratá-lo como velocidade |

O controlador aplica ao alvo o fator **0,44704**, compatível com uma escala
nominal de mph. A interface apresenta as conversões `controle × 1,609344` e
`avanço × 3,6` como **km/h nominais**. São conversões dos campos internos,
não medições da velocidade física ou renderizada do carro, nem prova da escala
em metros de todas as coordenadas do jogo.

Filas, obstáculos e estados do tráfego podem reduzir o avanço, inclusive até
zero, enquanto o alvo permanece positivo. Isso é compatível com a observação
do usuário de que veículos sobrepostos podem aguardar espaço para sair do
congestionamento. As margens de 8 unidades, ou 30 para conjuntos/ônibus, são
restrições conservadoras do modo normal do editor; não são apresentadas como
distâncias mínimas obrigatórias do motor.

Registros sem nó reconhecido mostram velocidade indisponível, em vez de
converter campos padrão zerados em uma falsa medição. Cargas vinculadas
indicam que o controle pertence à cabine. Veículos já convertidos para outro
estado físico podem deixar de ter um controle de tráfego editável.

## Alterar o alvo

1. Pause o PCSX2 e selecione um veículo ou cabine com controle disponível.
2. Preencha **Alvo nominal (km/h)** e clique em **Aplicar velocidade**.
3. Retome o jogo para observar a resposta do controlador. Compare alvo e
   seguimento na próxima leitura pausada, especialmente se houver uma fila.

O alvo **zero** solicita parada através do controle normal do jogo. Ele não
zera diretamente a velocidade física ou o avanço atual. Aumentar o alvo
posteriormente permite ao controlador buscar outra velocidade, mas não remove
um carro que esteja bloqueando a frente nem garante aceleração imediata.

No modo normal o intervalo do controle original é `0..240`, o mesmo intervalo
admitido pelo criador pesquisado do editor. Isso corresponde a aproximadamente
`0..386,24 km/h` na apresentação nominal; não é uma faixa de estabilidade
universalmente validada. O modo experimental admite alvos maiores finitos e
representáveis em float32, com o aviso de risco mantido.

A alteração muda somente **um float de alvo**. O editor verifica pausa,
associação entre objeto e nó, proprietário, caminho, estado do nó, tipo e valor
anterior. Ele mantém a física e os campos calculados sob controle do jogo.
Não altera diretamente o avanço, a aceleração, o campo `+0x24` ou a carga.

**Salvar configuração** conserva a ação de velocidade na receita JSON, junto
das demais ações. A receita exige sua referência inicial correspondente; uma
ação experimental exige que o modo experimental esteja ligado ao carregá-la.
Um estado `.p2s` conserva um instante da sessão. Reiniciar ou trocar de evento
pode reconstruir os valores originais do tráfego.

## Base da interpretação e validação restante

O criador grava o controle no nó em `0x00164d90`. O inicializador
`0x00161590` produz o avanço inicial com o fator 0,44704; a constante foi
resolvida na região carregada do ELF em `0x004e11f4` usando seu valor de GP.
A rotina `0x00161b50` ajusta o avanço conforme comportamento e obstáculos.
Depois, `0x00162e80` integra a progressão usando esse avanço, o delta do jogo
em `0x0052267c` e o comprimento do segmento. Essa sequência fundamenta a
distinção entre alvo, seguimento e movimento físico observado.

Preparar patches protegidos e passar nos testes automatizados não demonstra
resposta real de todos os modelos, calibração física em km/h ou estabilidade
em cenas densas. O novo controle e a visualização precisam desses ensaios.
Os resultados sobre muitos carros batidos e renderização são tratados
separadamente em [high-density-experiments.md](high-density-experiments.md).
