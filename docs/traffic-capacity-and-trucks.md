# Tráfego tardio, restrições e caminhões

Pesquisa atualizada em 13/11/2026, para o executável USA pesquisado.

## Resultados e restrições atuais

O usuário relatou criação de vários veículos em níveis diferentes, inclusive
atrás de tráfego que apareceu depois e atrás de outros veículos acrescentados.
Na etapa de criação individual, o registro local examinado confirmou 20 operações `spawn_finished`, em seis modelos,
com referências nos caminhos 2, 3, 6 e 21 e referências lógicas a atores criados.
São ensaios específicos; isso não valida todos os eventos e situações do jogo.

O editor usa recursos já carregados. A primeira versão admitia criação
com uma associação independente e consistente a tipos 1 ou 2. A categoria
visual não corresponde necessariamente ao byte de tipo: há modelos chamados
Car, Van ou Motorhome com associações admitidas. Criar um modelo ausente exige
investigar seu carregamento e dependências; não basta trocar o ID. A versão
seguinte também admite lotes de 1 a 8 e pares nativos carregados de cabine
tipo 4 com carga tipo 11; o estado atual está em
[batches-trucks-and-pause.md](batches-trucks-and-pause.md).

O perfil desta etapa também admite independentes 3/5 com associação nativa
consistente: vans `HEVYCAR17/18` de tipo 3 e ônibus `HEVYCAR19/21` de tipo 5.
Exige dois pontos físicos não degenerados, coerência do render e collider,
caminho e ocupação válidos. `HEVYCAR20` apenas carregado continua bloqueado sem
associação ativa consistente ao tipo 5. Tipos especiais 6 a 10 não foram
habilitados. O teste real de criação de ônibus ainda está pendente; a distância
admitida para ônibus escolhido ou usado como referência é de 30 a 50 unidades.

Um lote de ônibus tipo 5 em formato v2 foi preparado e aguardava o usuário
retomar o tráfego; a etapa não comprova presença, movimento, colisão ou finalização.
Na rodada de validação passaram 157 testes distribuíveis e 40 privados
(19 do controlador e 21 do perfil).

Após reabrir a revisão com finalização protegida, o usuário confirmou lote e
exportação reais. O registro local também inclui oito `HEVYCAR33` finalizados
no caminho 53 e dois pares `HEVYCAR22` + `HEVYCAR27` finalizados em cada um dos
caminhos 34 e 53. Uma leitura posterior registrou recusa estrutural de perfil
com uma solicitação pendente. Isso não prova travamento ou falha geral e não
elimina as restrições de física, vínculos e caminho. A restauração do `.p2s`
exportado e um quarto tanque continuam sem teste.

Com os dez slots ocupados na sessão atual, a exportação PINE pelo editor é
recusada sem substituir saves. A alternativa **Sistema → Salvar estado → Arquivo…**
com destino novo gerou uma cópia de controle validada como ZIP/EE de 32 MiB.
A restauração usa **Sistema → Carregar estado → Arquivo…** e ainda precisa
de validação do arquivo exportado.

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

Uma pendência investigada depois veio do recarregamento de um estado feito
antes da limpeza. O botão **Finalizar pendência** passou a conferir o registro
local e o payload canônico v1/v2 com landing, exigindo conclusão e devolução
de controle antes de limpar. Uma recuperação real mudou somente a área
temporária de 4 KiB; objetos, nós e matrizes permaneceram idênticos byte a byte,
sem reposicionar veículos. A receita antiga e seu alinhamento não foram recuperados.
O token v2 por geração impede aceitar a conclusão de outra solicitação.

Com a identidade do jogo confirmada e o perfil inválido, a conexão é mantida
para essa recuperação explícita. Listagem e mutações continuam bloqueadas até
uma leitura válida. Se o código ou registro não conferir, o editor exige uma
referência limpa e não tenta remover bytes desconhecidos.

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

A interface agora representa o conjunto como uma unidade com seleção separada
de cabine e carga, preservando seus dois objetos físicos. Só oferece os pares
nativos observados e carregados; a carga não é criada avulsa. O usuário confirmou
o funcionamento de um caminhão com carga, e o registro local inclui finalização
de um par `HEVYCAR22` + `HEVYCAR27`. Isso não valida todos os pares, o movimento
composto candidato ou um quarto tanque.

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
