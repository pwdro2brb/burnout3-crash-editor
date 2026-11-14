# Muitos veículos e testes experimentais

Investigação iniciada em 13/11/2026 e atualizada em 14/11/2026 para Burnout 3 USA
e PCSX2 1.7.2521.

## O que o erro informa

O usuário relatou falhas depois de acrescentar mais de cinquenta veículos ao
tráfego original: alguns perdem a física e uma batida com muitos envolvidos
pode congelar ou terminar no assert `FQC = 0 on VIF FIFO READ!`. Esse é um
resultado observado pelo usuário em determinados eventos; ainda não estabelece
um máximo geral de cinquenta veículos adicionados.

No código dessa versão do PCSX2, `ReadFIFO_VIF1` exige uma contagem FIFO diferente
de zero antes de ler. No caminho de transferência para a memória, a rotina espera
o GS, obtém os dados e reduz a quantidade restante. O assert indica que o emulador
recebeu uma leitura com contagem zero. Ele não mede carros, corpos físicos ou o
espaço disponível nos pools do jogo. O erro sozinho não permite decidir entre
estado inválido do jogo, comportamento de emulação ou outra causa anterior.
[Código oficial de FiFo.cpp](https://github.com/PCSX2/pcsx2/blob/v1.7.2521/pcsx2/FiFo.cpp#L42).

`FQC` representa a quantidade de dados no FIFO, e `FDR` sua direção de
transferência, no modelo de registradores dessa versão. Desativar a verificação
não demonstra que os dados de uma transferência estejam corretos nem resolve a
perda de física. Esta etapa não alterou o emulador ou seus asserts.
[Registradores VIF oficiais](https://github.com/PCSX2/pcsx2/blob/v1.7.2521/pcsx2/Vif.h#L112).

## Existem vários recursos finitos

O pool de tráfego é somente uma parte do problema. A pesquisa do executável
mostra estruturas distintas, compartilhadas com outros objetos do cenário:

| Recurso pesquisado | Limite ou comportamento observado | O que não comprova |
| --- | --- | --- |
| Objetos de tráfego e nós de caminho | 254 posições em cada pool; componentes de caminhão também usam objetos | Que 254 carros possam participar de uma batida |
| Descritores de colisão | Região pesquisada comporta 1.224 registros | Que todos possam ser processados simultaneamente com física completa |
| Endpoints da ordenação espacial | 2.448 por eixo, dois por descritor | Que haja recursos livres em outras etapas |
| Lista de pares candidatos a colisão | A rotina examinada só acrescenta pares enquanto seu contador é menor que 256 | Um limite de 256 veículos ou a causa exata do assert VIF |

A limitação de pares está explícita na função `0x001b8f00`: o teste em
`0x001b9198` compara o contador com `0x100`, e o salto seguinte ignora a inclusão
quando a lista está cheia. Cada registro tem tamanho `0x30`. Os pares admitidos
são enviados à rotina `0x001b7220` para o tratamento de colisão.

Numa concentração de veículos, a quantidade de pares possíveis cresce mais
rápido que a quantidade de carros. Com 24 objetos há 276 combinações de dois;
o jogo filtra quais caixas realmente se sobrepõem antes de registrar pares.
Esse exemplo explica por que uma fila de contatos pode ficar pressionada sem
esgotar o pool de tráfego. Não demonstra que aquela rodada tenha atingido a fila
nem determina quais contatos seriam descartados durante o teste do usuário.

Também foi encontrado um conjunto de 64 registros maiores, inicializados em
`0x001b9850`, com tamanho `0x2430` e construtor `0x002513f0`. O tratamento de
colisões usa campos desse layout para um tipo de corpo. A ligação completa entre
criação, conversão do tráfego para física de batida, ocupação e descarte desses
registros ainda precisa ser mapeada. Portanto, **64 não é apresentado como um
limite geral de veículos nem como a causa comprovada das falhas**.

O número `0x001b93bc` no texto da pilha coincide com uma instrução logo após a
chamada de tratamento de pares no executável USA. A pilha apresentada não inclui
o contexto de registradores convidado necessário para atribuir esse valor ao PC
do jogo. A coincidência é uma pista de investigação, não um diagnóstico fechado.

## O que o modo experimental pode liberar

O editor pode afrouxar limites próprios de quantidade por pedido, distância e
proximidade para experimentar cenas mais densas. Isso não amplia automaticamente
as estruturas fixas do motor nem carrega modelos ausentes. A indicação desse modo
deve ser visível: **há chance alta de crash, congelamento ou perda de física**.

Continuam necessários modelo carregado compatível, caminho reconhecido, valores
finitos, pausa do núcleo para escrita e conferência do código temporário. O
editor também deve recusar ultrapassar as regiões de memória e capacidades
conhecidas. Uma opção chamada ilimitada não pode transformar um endereço fora
do pool em um registro válido.

Criar mais carros e aumentar a capacidade de uma batida são trabalhos diferentes.
A ampliação real de capacidade exige identificar todos os consumidores de cada
estrutura, ajustar armazenamento e índices e validar a conversão, os contatos,
o desenho e os efeitos. Esta pesquisa não implementou essa ampliação.

## Validação que falta

Para isolar a perda de física, o próximo ensaio instrumentado deve conservar uma
referência do mesmo evento e aumentar a densidade em etapas, comparando tráfego
disperso, veículos concentrados sem impacto e a batida. Contagens de objetos,
pares, corpos convertidos e colisões precisam ser observadas antes da falha.
Repetir o mesmo cenário permite diferenciar quantidade total de contatos
simultâneos. Um assert sem essa captura não prova qual recurso se esgotou.

Nesta passagem foram lidas fontes oficiais e exportações estáticas preservadas.
Duas funções foram exportadas adicionalmente por Ghidra em modo somente leitura,
sem reanálise do projeto. Nenhum crash foi provocado, nenhum input foi enviado ao
jogo e nenhuma captura privada ou código descompilado é distribuído neste documento.
