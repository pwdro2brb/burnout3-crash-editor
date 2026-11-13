# Primeiro veículo adicional no Grand Slam — resultado parcial

Em 12/11/2026, um ensaio local criou uma nova instância independente atrás do
veículo anteriormente reposicionado no Grand Slam. A criação foi conferida
nas estruturas do jogo. Depois de assumir a direção, **o usuário relatou que
o carro apareceu e a colisão funcionou**. Esse retorno manual é registrado
separadamente das verificações instrumentadas de estruturas e posições.

O experimento usa novas cópias de save state no PCSX2 isolado. O ISO, o ELF e
os saves originais do usuário não receberam escrita. O código experimental
de criação permanece no laboratório; este repositório ainda não oferece um
criador portátil ou uma interface de edição dentro do jogo.

## Criação pela rotina original

Uma chamada de execução única à rotina original de criação recebeu o modelo
já carregado do alvo, seu caminho e uma progressão menor, para colocar o carro
atrás dele. O jogo alocou os registros, associou o caminho e registrou o novo
colisor. Nenhum veículo ativo foi removido ou movido para simular um acréscimo.

Depois de um passo configurado de 30 quadros, o retorno da chamada apontava
para o novo objeto 12 e o novo nó 10. O alvo anterior permanece como objeto 9,
nó 8, no caminho 21. As contagens examinadas foram:

| Estrutura | Antes | Depois |
| --- | ---: | ---: |
| Objetos ativos | 12 | 13 |
| Nós ativos | 10 | 11 |
| Descritores de colisão | 32 | 33 |
| Endpoints por eixo | 64 | 66 |

Objetos incluem componentes articulados: **13 objetos não significa 13 carros
independentes**. O novo objeto tem tipo e modelo iguais aos do alvo, pontos
físicos finitos e separados e colisor próprio. Listas livres, bitmaps,
contagens, identidades, backlinks, cadeia/grid do caminho e registros de
colisão/endpoints passaram nas verificações implementadas.

Os 30 quadros são o avanço configurado no emulador; um contador interno do
jogo não foi validado independentemente. Não há evidência válida de uma
janela de 120 quadros para esta criação.

## Limpeza e alinhamento

Após conferir a criação, uma nova cópia restaurou as instruções usadas pela
chamada temporária e limpou sua área auxiliar. Os registros criados pelo jogo
foram preservados. A versão entregue ao teste manual não mantém o código
instalado para criar carros repetidamente.

O reposicionador já usado na pesquisa alinhou somente o carro novo à lateral
0,85. Os dois carros ficam nessa mesma lateral; o centro do novo objeto está
aproximadamente **10,85 unidades do jogo atrás** do alvo. Essa distância é
uma medida entre posições salvas, não metros ou comprimento de trajetória
estabelecidos. Os 253 demais registros de objetos ficaram idênticos durante
essa etapa de alinhamento, inclusive o alvo anterior.

O script não escreveu o alvo em cache, a matriz do caminho ou o AABB do novo
objeto. Esses dados dependentes precisam se atualizar durante a execução.
As verificações de registro continuam aprovadas offline, mas não comprovam
essa atualização espacial nem a resposta de uma colisão real.

## Teste manual e limites

Na cópia de teste preparada para o usuário, o slot 1 conserva a versão anterior
com o deslocamento e sem o carro adicional; o slot 2 contém a nova instância.
Os conteúdos substituídos foram preservados, e o mapeamento do controle físico
foi restaurado antes da entrega. Recarregar o estado do slot 2 restaura a
instância extra; o Restart interno do jogo pode recriar os dados do evento.

O teste manual da instância adicional recebeu o retorno: “Apareceu e a colisão
funcionou”. O usuário conduziu o veículo e realizou essa verificação no cenário.
A sequência completa do impacto não foi capturada pelo agente nem ligada por
instrumentação ao objeto 12. Portanto, ainda faltam amostras temporais de
movimento após o alinhamento, um impacto instrumentado e duração maior para
a instância nova. A capacidade geral, outros modelos/locais e a persistência
ao reiniciar o evento não foram estabelecidos.

Saves, capturas, relatórios de RAM e exportações do executável permanecem
locais, fora deste repositório.
