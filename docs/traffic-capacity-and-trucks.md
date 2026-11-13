# Tráfego tardio, restrições e caminhões

Pesquisa atualizada em 13/11/2026, para o executável USA pesquisado.

## Resultados e restrições atuais

O usuário relatou criação de vários veículos em níveis diferentes, inclusive
atrás de tráfego que apareceu depois e atrás de outros veículos acrescentados.
O registro local confirma 20 operações `spawn_finished`, em seis modelos,
com referências nos caminhos 2, 3, 6 e 21 e referências lógicas a atores criados.
São ensaios específicos; isso não valida todos os eventos e situações do jogo.

O editor usa recursos já carregados. Na primeira versão, só admite criação
com uma associação independente e consistente a tipos 1 ou 2. A categoria
visual não corresponde necessariamente ao byte de tipo: há modelos chamados
Car, Van ou Motorhome com associações admitidas. Criar um modelo ausente exige
investigar seu carregamento e dependências; não basta trocar o ID.

Não há teste de direção relativa ao jogador no controlador. Ele exige
pontos físicos inicializados, caminho válido e concordância entre orientação,
velocidade de seguimento e progressão do caminho. Numa leitura pausada do
evento atual, quatro carros orientados no sentido oposto ao jogador tinham
pontos físicos não inicializados e velocidade de seguimento zero. Essa leitura
explica a recusa desses quatro casos, sem estabelecer que todo tráfego na
contramão seja incompatível. A interface agora mostra o motivo de bloqueio
ao selecionar um objeto.

## Quantidade e erro de proteção

Os pools são compartilhados. A capacidade nominal pesquisada de objetos é
254 registros, incluindo componentes de caminhões; isso não equivale a 254
veículos seguros, nem substitui as capacidades de nós e colisão. A criação
também depende de recursos carregados e de espaço útil atrás da referência.
Encadear criações perto do início de um caminho pode esgotar esse trecho.

O erro **Há uma alteração de código não reconhecida na atualização do tráfego**
é outra proteção: os bytes do retorno da rotina diferem dos aceitos pelo perfil.
Ele não demonstra esgotamento do pool ou fim da pista. A causa histórica da
imagem do usuário não foi capturada. Na leitura posterior, o retorno já estava
original e a área temporária zerada; não foi necessário alterar o jogo.

O controlador passou a registrar `profile_rejected`, incluindo estado de pausa,
bytes do retorno e da pequena identificação da solicitação, no log local.
Isso permitirá distinguir uma solicitação antiga de outra alteração se o erro
reaparecer. Uma solicitação reconhecida de outra sessão recebe orientação
específica; código desconhecido continua bloqueado. O editor não tenta
restaurá-lo por adivinhação. Esses diagnósticos ficam fora do repositório.

## Cabine e carga são um conjunto

Os callers de tráfego examinados solicitam primário tipo 4 e secundário
tipo 11, com IDs de modelos separados. O criador registra o filho em
`primário+0x110` e o pai em `filho+0x10c`. O primário tem nó de caminho;
o secundário acompanha o conjunto sem consumir um segundo nó. Ambos têm
descritores físicos próprios.

Um save preservado contém dez cabines `HEVYCAR22` e dez reboques: três
tanques `HEVYCAR29`, quatro plataformas `HEVYCAR27` e três carretas fechadas
`HEVYCAR30`. O arquivo manteve seu hash durante a leitura. Isso comprova mais
de três componentes de tipo 11, inclusive quatro plataformas do mesmo modelo.

Para um conjunto semelhante, espera-se verificar:

| Estrutura | Consumo adicional esperado |
| --- | ---: |
| Objetos e respectivos registros de ocupação | 2 |
| Nó de caminho, cadeia e grid | 1 |
| Descritores de colisão | 2 |
| Endpoints por eixo | 4 |

A interface deverá representar o conjunto como uma unidade com seleção
separada de cabine e carga, preservando seus dois objetos físicos. Até validar
essa criação, os componentes continuam bloqueados no editor atual.

## Existe limite de três tanques?

Não foi encontrado esse limite em `0x164a50` (criação), `0x1864f0`
(inicialização), `0x1b85f0` (registro de colisão) ou nos callers examinados.
O `%3` observado no criador escolhe um atributo entre três bytes do manager;
não conta caminhões tanque. As condições de capacidade são compartilhadas.

Isso não prova que quatro tanques e suas explosões sejam estáveis. Rotinas
posteriores de dano, explosão e efeitos não foram cobertas por essa busca.
Ter três no desenho original de um evento não estabelece o máximo do motor.

O teste decisivo será acrescentar um quarto conjunto cabine+tanque numa cópia
isolada com três, usando uma combinação nativa já observada. Primeiro verificar
os dois objetos, vínculos, nó/grid e colliders; depois movimento e, com o
usuário dirigindo, colisão e explosões. Existência, movimento e impacto são
verificações distintas. Nenhum quarto tanque foi criado nesta investigação.

As conclusões estáticas reutilizam as exportações locais das funções
`0x164a50`, `0x1864f0`, `0x1b85f0`, `0x2662e0`, `0x267ec0`, `0x267800`
e `0x266ae0`. Exportações e saves permanecem privados e não são distribuídos.
