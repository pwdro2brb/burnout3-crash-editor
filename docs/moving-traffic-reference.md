# Reposicionamento de tráfego em movimento no Grand Slam

Em 12/11/2026 foi aplicado um pequeno deslocamento a um veículo em movimento
do Grand Slam, numa cópia isolada do PCSX2 1.7.2521.0. A comparação da RAM após
passos configurados de 30 e 120 quadros confirmou que o corpo continuou andando
e manteve a separação lateral. **A identificação visual desse alvo ainda está
pendente**: as capturas ficaram na aproximação da curva do Hotel Grand.

## Referência e seleção

O novo slot 1 fornecido pelo usuário restaurou a introdução **Grand Slam** e,
depois de Continue, a contagem inicial e o GO. A referência preservada tem
14.309.260 bytes e SHA-256
`68e2c8429aa8ef5dfb31c62d248fe86467eaba7f7cd8ba696865dc40a4be4476`.
As referências anteriores também foram preservadas.

Na introdução há 10 objetos e 9 nós ativos; na aproximação usada pelo teste,
12 objetos e 10 nós. Os invariantes examinados passaram. Quatro palavras de
código conhecidas coincidem com o ELF pesquisado; isso não prova que todo o
estado esteja sem modificações.

O alvo foi o objeto independente 9, associado ao nó 8/caminho 21, com dois
pontos físicos inicializados e descritor de colisão válido. Os objetos 5/6
formam um conjunto articulado e foram excluídos. Alguns objetos distantes
possuem âncoras zeradas apesar de estarem ativos: eles ainda não servem como
entrada deste método. O protótipo agora recusa pares de âncoras degenerados.

## Alteração e comparação

A referência de aproximação tem SHA-256
`3abef54f23f5029e0eb5e9afbd4de00ffbdce21db5ce03a4111f2635d6a210a9`.
A variante alterou sete floats: X/Z dos dois pontos físicos e da translação
atual, além da fração lateral do nó, de aproximadamente 0,4635 para 0,55.
O delta horizontal efetivo foi `(+0.212890625, -0.462646484375)` em X/Z,
cerca de 0,51 unidade do jogo. Todos os outros bytes da RAM de entrada e os
demais membros do ZIP foram preservados.

O deslocamento foi recalculado para o ponto atual do caminho. Reutilizar o
vetor estimado na introdução produziria outra direção após a curva. A projeção
local da largura e do AABB ajudou a escolher a variante, mas não substitui um
teste real de contato com a pista ou com outro veículo.

Controle e variante foram restaurados separadamente, com os mesmos inputs
neutros e o mesmo número de comandos de avanço. Os números de quadros abaixo
são os passos configurados no emulador; um contador interno do jogo não foi
validado independentemente.

| Passo configurado | Distância do controle desde o início | Distância da variante desde seu início | Separação entre os carros |
| --- | ---: | ---: | ---: |
| 30 quadros | 6,716 | 6,713 | 0,513 |
| 120 quadros | 26,621 | 26,608 | 0,523 |

As distâncias são normas entre posições amostradas, em unidades do jogo,
não comprimentos integrados de trajetória nem metros estabelecidos.
A progressão do caminho e os campos candidatos de velocidade ficaram iguais
entre controle e variante. A fração lateral 0,55 permaneceu nos dois passos.

O jogo atualizou os dois pontos físicos, a transformação, o alvo armazenado e
o AABB. Y também mudou durante a execução: a diferença entre os corpos ficou
próxima de -0,0205 e -0,0197 nos dois passos. A orientação e as extensões do
AABB tiveram pequenas diferenças; o resultado não é uma translação rígida
exatamente constante numa curva.

Nos dois pares, os 253 outros registros de objetos, os 253 outros nós e suas
matrizes foram byte a byte iguais. Os 11 descritores dos outros objetos ativos
também conferiram. A região examinada do gerenciador e o bloco inferido do
jogador ficaram iguais. Há diferenças fora dessas regiões em RAM não
classificada; não foi demonstrada ausência global de efeitos.

Restaurar o controle e repetir 30 quadros devolveu exatamente os mesmos 32 MiB
de EE RAM do controle anterior. Saves, capturas e relatórios de comparação
permanecem locais e não são distribuídos neste repositório.

## Limites e próximo teste

O resultado confirma um reposicionamento físico limitado de uma instância
existente em movimento. Falta enquadrar e identificar esse veículo na tela,
testar uma colisão real e ampliar a duração/modelos antes de generalizar.
Segundo o usuário, deve-se avançar e entrar à direita para ver a via com
tráfego em sentidos opostos; esse enquadramento ainda não foi concluído.

Não foi criada uma instância adicional nem alterado um recurso persistente
do evento. Adicionar veículos, criar uma interface dentro do jogo e usar
locais novos continuam como investigações posteriores. O ISO, o executável
e os saves originais do usuário não foram escritos.
