# Achados e limites da pesquisa

Este resumo contém fatos estruturais e nomes inferidos, sem bytes do jogo,
pseudocódigo, saves ou dumps. Observações estáticas e observações históricas de
save states não devem ser tratadas como testes de uma modificação em execução.

## Perfil estudado

- Executável USA `SLUS_210.50`, ELF32 little-endian MIPS/PS2 R5900.
- SHA-256 do executável estudado:
  `e118dba952bf9fde6a04ee284bb1f06fa0bb49c9e04bbe762af1039dcc443c66`.
- Tabela de símbolos vazia; nomes de funções usados na análise são automáticos
  ou inferidos. Ghidra com extensão R5900 produziu análise e pseudocódigo.
- O reconhecimento do ELF pelo REA não significa suporte de descompilação pelo
  seu adaptador; a pesquisa usou diretamente scripts do Ghidra.

## Recursos

- `GLOBALUS.BIN`: header de 16 bytes, 4.006 offsets uint32LE absolutos e
  ascendentes para textos UTF-16LE. O leitor exporta índices/offsets/textos apenas
  para uma pasta local ignorada.
- Há 36 `GAMEDATA.BGD`. Os examinados possuem marcador de versão 9 e o texto
  `B3tGameDataGame`. Seu formato de registros e fixups ainda não foi recuperado.
- As amostras de `CRASH*.RWS` analisadas são bancos sonoros, não layouts de tráfego.
- O loader lê `TLIST.BIN` em bloco de 4.096 bytes. O header começa com `(4, 36)`;
  o significado completo não está estabelecido.
- O candidato `STAGEHED.BIN` possui 377 registros em base `0x278`, stride `0x3e0`,
  corroborados pela análise e por ordinais exatos em todos os registros.
  Cada registro tem seis slots de `0x98`, dois IDs de 64 bits por slot e arrays
  numéricos ainda parcialmente desconhecidos. Há lógica de seleção de veículos
  e variantes; nenhuma coordenada de spawn de tráfego foi identificada ali.
- A ligação exata do global de runtime ao buffer de STAGEHED permanece pendente.
  O ponteiro candidato era zero nos dois saves históricos examinados. Os 168
  bytes finais do recurso não foram classificados como padding.

## Pool de tráfego candidato

Análise estática propôs o layout abaixo, corroborado estruturalmente por dois
save states históricos do perfil USA, e novamente em estados fornecidos depois:

| Estrutura | Endereço / stride |
| --- | --- |
| Manager | `0x00527440` |
| Objetos | `0x00539c10` / `0x180`, 254 posições |
| Nodes | `0x00551910` / `0x50`, 254 posições |
| Matrizes | `0x00556870` / `0x50` |
| Translação visual do objeto | objeto `+0xa0` |
| Dois pontos físicos absolutos | objeto `+0x00` e `+0x30` |
| Translação na matriz de seguimento | matriz `+0x30` |

Índices próprios, listas livres, partições livre/alocado, bitmaps, flags,
contadores e backlinks conferiram nas capturas examinadas. Nas capturas anteriores,
as contagens de objetos foram 4 e 46; há componentes com links pai/filho, portanto isso não equivale ao
número de veículos independentes ou visíveis. Alguns componentes tinham node
nulo. A associação espacial foi ligada a um veículo na tela no teste descrito
em [repositioning-milestone.md](repositioning-milestone.md).

O primeiro teste visual isolado confirmou que os dois saves anteriores restauravam telas
de resultados do Crash Mode. **Aqueles dois não eram referências anteriores ao GO.** Não foi
aplicado patch espacial ou de geração de veículos naquela etapa. Comparar quatro palavras de código no save não prova que
todo o estado esteja sem modificações.

Na segunda atualização, novos estados fornecidos pelo usuário apresentaram
respectivamente 16 objetos/16 nós e 13 objetos/9 nós alocados. As quatro palavras
de código de controle coincidiam com o ELF estudado e duas áreas reservadas
conhecidas estavam zeradas. Esses controles localizados não demonstram ausência
de toda modificação possível. As cenas carregadas foram observadas depois:
uma via tropical com curva e um trecho urbano com caminhão de bombeiros.
**Não foi confirmada uma contagem inicial ou referência anterior ao GO**;
essa classificação não foi inferida apenas pelos números do pool.

## Primeiro marco confirmado em 12/11/2026

Um carro independente foi reposicionado em uma cópia de estado salvo. Alterar
só a fração lateral mudou a matriz de seguimento, sem deslocar o corpo. O teste
confirmado coordenou X/Z dos dois pontos físicos e da translação visual com o
parâmetro lateral do nó. O deslocamento persistiu pelo passo configurado de 30
quadros e a caixa de colisão se atualizou automaticamente.

Os demais registros de objetos ficaram idênticos ao controle. A diferença de
pixels ficou localizada no carro distante e restaurar a referência devolveu o
viewport original. Isso não comprova um impacto contra o carro reposicionado
nem estabilidade prolongada. O protótipo portátil gera apenas novas cópias de
save state; não há editor dentro do jogo.

## Tráfego em movimento no Grand Slam

A referência seguinte restaurou a introdução do Grand Slam e sua contagem
inicial. Num estado de aproximação, um veículo independente com âncoras
inicializadas recebeu um deslocamento horizontal de cerca de 0,51 unidade e
uma nova fração lateral do caminho. Após passos configurados de 30 e 120
quadros, a comparação dos estados mostrou movimento real das posições,
separação lateral persistente e atualização automática do AABB e de Y.

Os outros registros dos pools de objetos, nós e matrizes ficaram iguais entre
controle e variante, assim como os outros descritores ativos de colisão.
Isso não estabelece igualdade de toda a RAM: existem diferenças fora das
regiões classificadas. Numa variante posterior com deslocamento maior, o
usuário relatou mudança visível e colisão funcionando, identificando o candidato
como o primeiro carro vermelho. A associação dessa cor ao índice interno e
um impacto instrumentado ainda não foram estabelecidos. Método e limites em
[moving-traffic-reference.md](moving-traffic-reference.md).

Objetos distantes podem estar ativos com os dois pontos físicos ainda zerados.
O protótipo recusa âncoras degeneradas; estar ativo e ter coordenadas finitas
não basta para usar esse caso de reposicionamento.

## Primeiro veículo adicional — resultado parcial

Um ensaio local chamou a rotina original de criação para acrescentar uma
instância independente ao Grand Slam. Após o passo configurado de 30 quadros,
o retorno apontava para o novo objeto 12/nó 10. As contagens passaram de
12/10 objetos/nós para 13/11, com um descritor de colisão adicional. Objetos
incluem componentes articulados; isso não equivale a 13 carros independentes.

Listas livres, bitmaps, backlinks, cadeia/grid do caminho e registros de
colisão/endpoints examinados passaram. Uma cópia posterior removeu o código
temporário, preservou a instância criada e alinhou somente o objeto novo cerca
de 10,85 unidades atrás do alvo. Depois de assumir a direção, o usuário
relatou que o carro adicional apareceu e a colisão funcionou. Esse resultado
manual não constitui uma captura instrumentada do impacto. Não há prova de
120 quadros para a criação, movimento temporal após o alinhamento ou
persistência após reiniciar o evento.

Método e limites em [vehicle-creation-milestone.md](vehicle-creation-milestone.md).
Esse ensaio usou um criador local. A ferramenta externa acrescentada depois
está descrita em [editor-status.md](editor-status.md); ainda não há editor
dentro do jogo.

## Catálogo e editor externo do evento atual

Os 40 identificadores de tráfego foram decodificados em base 40 e associados
à tabela de rótulos do próprio jogo e aos recursos correspondentes. O carro
do ensaio anterior usa `COMPCAR14`, classificado como **Car**. `HEVYCAR33` e
`HEVYCAR35` são **Van**; `HEVYCAR20` é **Bus**. O catálogo identifica os
modelos carregados, inclusive aqueles cuja criação ainda está bloqueada.

A interface externa lista veículos, mostra suas posições em vista de cima,
aplica deslocamento lateral e prepara uma criação atrás de uma referência.
Uma integração real por PINE confirmou leitura e reposicionamento. O
controlador também criou `HEVYCAR33` como objeto independente de tipo 2,
com nó, pontos físicos inicializados e lateral alinhada; o hook original e
a área temporária foram restaurados. Isso não demonstra a colisão dessa
van, a persistência no evento ou a validação de todos os modelos.

Na rodada seguinte preparada pela interface, o usuário relatou presença e
colisão da van no Grand Slam. O cancelamento após recarregar o estado e a
finalização técnica do ensaio separado estão distinguidos no registro abaixo.

O fluxo pela interface e o teste manual desta versão estão documentados em
[editor-status.md](editor-status.md) e no [guia](editor-quickstart.md).

## Próximas verificações

1. Medir movimento após o alinhamento e registrar um impacto instrumentado.
2. Ampliar a duração e os modelos dos ensaios de reposicionamento/criação.
3. Investigar persistência no evento, capacidade e edição de locais.

Este repositório é uma base de pesquisa experimental. Não comprova que todos os
locais do jogo possam hospedar eventos Crash nem que um editor dentro do jogo
possa ser implementado apenas alterando os arquivos já identificados.
