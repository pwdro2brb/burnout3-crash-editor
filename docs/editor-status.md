# Editor externo e identificação de modelos

Na revisão de 14/11/2026 passaram **241 testes distribuíveis** e **45 testes
locais com capturas privadas**: 19 do controlador, 21 do perfil e 5 da integração
de caminhos/velocidade. A prévia de uma referência preservada mostrou 27
caminhos e o caminho selecionado P21; a leitura e o ajuste de alvo foram
verificados em memória copiada, sem aplicar mudanças na sessão do jogo.
O novo controle de velocidade ainda precisa de validação em execução real.

Os testes automatizados cobrem transporte, perfil, fila, cancelamento, projeção
por ponto, preservação do caminho no replay, retorno lateral experimental,
visualização de vias e velocidade nominal. A conferência visual e os ensaios
reais dos fluxos novos permanecem separados dessa validação. Esses resultados
não comprovam estabilidade com muitos veículos.

Estado documentado em 13/11/2026. A interface do evento atual está implementada
e foi ligada a uma cópia isolada do PCSX2 real. O usuário relatou: **“A van
apareceu e a colisão funcionou”**, na rodada preparada pela interface no Grand
Slam. Esse relato manual não constitui um impacto instrumentado nem comprova
estabilidade prolongada. Os ensaios anteriores de reposicionamento e criação
do carro adicional têm seus próprios resultados.

## O que o catálogo identifica

O modelo usado na criação anterior foi **COMPCAR14**, classificado como **Car**
pela tabela de rótulos do jogo. O identificador corresponde ao recurso do jogo;
ele não estabelece um fabricante ou modelo real de automóvel.

Os IDs de 64 bits codificam nomes com até 12 caracteres em **base 40**. O
alfabeto é ` -/0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_`, com espaços de preenchimento
à direita. Codificar e decodificar os nomes reproduziu exatamente os 40 valores
da tabela de tráfego do executável USA. Portanto, a identificação de categoria
não depende de escolher um número aleatório ou adivinhar pela aparência.

A verificação local comparou três fontes: os 40 IDs da tabela do ELF, os
índices da tabela paralela de rótulos resolvidos em `GLOBALUS.BIN` e a existência
dos recursos correspondentes. Os 40 IDs, os 40 índices e os 40 caminhos de
recursos conferiram; os 40 nomes também passaram na ida e volta do codec.
Os arquivos examinados mantiveram os hashes de origem.

| Modelo | Categoria do jogo | Índice de rótulo | Associação observada no estado examinado |
| --- | --- | --- | --- |
| `COMPCAR14` | Car | 1897 | Objetos independentes de tipo 1; inclui a instância criada anteriormente |
| `HEVYCAR33` | Van | 1925 | Objeto independente de tipo 2 |
| `HEVYCAR35` | Van | 1927 | Objeto independente de tipo 2 |
| `HEVYCAR17/18` | Van | 1909/1910 | Associação nativa consistente a tipo 3 nas referências desta etapa |
| `HEVYCAR19/21` | Bus | 1911/1913 | Associação nativa consistente a tipo 5 nas referências desta etapa |
| `HEVYCAR20` | Bus | 1912 | Modelo carregado, sem instância independente ativa na referência; criação bloqueada |

Para reproduzir a associação estática, a tabela de 40 IDs começa em
`0x004cdc00` e a de índices em `0x004cdd40`. `COMPCAR14` ocupa o ordinal 3,
contado a partir de zero, e seu ID é `0x5b55839b95f21600`. O perfil usa o ELF
USA de SHA-256
`e118dba952bf9fde6a04ee284bb1f06fa0bb49c9e04bbe762af1039dcc443c66`.
Os metadados reproduzíveis estão em `scripts/editor/catalog.py`; dumps e
relatórios locais não fazem parte do repositório.

Conhecer a categoria não demonstra que a criação daquele modelo funcione.
O perfil inicial oferecia somente modelos carregados com associação observada
a tipos independentes 1 ou 2. A versão seguinte também admite cabine tipo 4
com carga tipo 11, somente nas combinações nativas observadas e carregadas.
Uma carga elegível aparece como **Disponível com caminhão**, sem criação
avulsa. Ônibus e combinações sem validação continuam bloqueados. A
disponibilidade é calculada para a sessão carregada;
a lista estática de 40 modelos não significa que todos estejam na memória.

O perfil atual também admite tipos independentes 3 e 5, quando a captura contém
associação nativa consistente: `HEVYCAR17/18` nas vans de tipo 3 e
`HEVYCAR19/21` nos ônibus de tipo 5. Na referência desta etapa, `HEVYCAR20`
está somente carregado e continua inelegível sem essa associação. A habilitação
não é inferida apenas pelo nome da categoria. Tipos especiais 6 a 10 continuam
bloqueados; o teste real de criação de ônibus ainda está pendente.

Os independentes 1/2/3/5 exigem dois pontos físicos inicializados e não
degenerados, caminho admitido e coerência com render e collider. Um modelo
elegível para criação não torna editável uma instância ainda sem física pronta.

## Integração real observada

Na cópia isolada do PCSX2, a interface conectou, leu os veículos e aplicou
o controle lateral ao objeto 9. Catálogo e vista de cima foram conferidos
na janela real, incluindo a referência do jogador.

Um teste do controlador criou a van **HEVYCAR33**, objeto 13/nó 11, atrás
do carro 12 que já existia na referência desse ensaio. A conferência final
confirmou tipo 2, modelo, caminho 21, pontos físicos inicializados e lateral
de 85%. O hook original e os 4096 bytes temporários ficaram limpos. O jogo
também criou tráfego natural durante o intervalo; a variação total do pool
não deve ser atribuída somente ao editor.

No primeiro teste pela interface, o objeto retornado pela criação já não
constava da lista ativa na finalização. O editor recusou alinhar ou limpar
uma solicitação que não podia mais confirmar. Essa captura não determina
se houve descarte ao fim do trecho ou reinicialização do evento. Pause
logo após o aviso de criação; deixar a simulação correr pode invalidar a
referência antes da finalização.

Na outra rodada pela interface, no início do Grand Slam, o usuário confirmou
presença e colisão da van. O registro local mostrou preparação de `HEVYCAR33`
atrás do objeto 9, com distância solicitada de 10 unidades. Depois registrou
cancelamento da solicitação ao encontrar o hook original e a área temporária
zerada após recarregamento de estado. Não registrou `spawn_finished` nessa
rodada: a conclusão técnica de alinhamento/limpeza foi demonstrada no teste
separado do controlador acima. Presença/colisão relatadas e finalização
registrada são evidências distintas.

## Finalização após o teste manual

O usuário confirmou novamente que o veículo foi adicionado e funcionou no
jogo, embora a interface ainda pedisse retomar ou pausar. A observação da
janela mostrou **Carro criado** com **Jogo em execução**: a solicitação já
havia retornado do alocador e aguardava a pausa do núcleo. Ao pausar a cópia
correta, a validação já não reconheceu a instância original. Isso explica
uma pendência de finalização, sem invalidar o relato manual de presença e
colisão nem provar a causa exata da mudança daquela instância.

O controlador passou a encerrar esse caso com aviso. Após validar a pausa,
a identidade e todos os bytes imutáveis da própria solicitação, ele restaura
somente o hook e a área temporária, cancela a fila e não alinha veículos nem
registra a criação na receita. Uma falha na limpeza continua bloqueando
edições e exige referência limpa. A interface preserva o aviso em âmbar,
distingue espera do tráfego de espera da pausa e destaca as duas etapas.

Para atualizar a sessão aberta, uma recuperação local validou a última
solicitação `HEVYCAR35` contra seu nonce registrado e os bytes canônicos da
rotina. Ela removeu apenas o código temporário; os hashes de toda a região
de objetos/nós/matrizes antes e depois ficaram iguais. Hook e área temporária
ficaram limpos, sem carregar outro estado ou alinhar atores. A interface
atualizada reconectou com **Jogo pausado**, sem criação pendente.

## Implementação disponível

- Interface externa em Tkinter, aberta por `Abrir Editor.cmd`.
- Conexão PINE local, com validação de PCSX2 1.7.2521 e Burnout 3 USA,
  `SLUS-21050` / CRC `BEBF8793`.
- Identificação dos veículos presentes e dos modelos carregados.
- Conexão mantida com perfil inválido após confirmar a identidade do jogo,
  mantendo **Finalizar pendência** disponível e a edição bloqueada.
- Vista de cima das posições X/Z e da geometria pesquisada dos caminhos de
  tráfego, com bordas, centro, setas de progressão e destaque da via selecionada.
  **Mostrar vias**, **Caminho**, **Enquadrar**, roda e arrasto com botão direito
  permitem navegar. Candidatos sem veículo associado são marcados `P?`;
  seu uso atual não é confirmado. A vista mantém alvo por clique e entrada manual
  para criação; não é a malha de asfalto nem acompanhamento em tempo real.
- Consulta do alvo e do seguimento em escala nominal km/h, com edição apenas do
  alvo quando o perfil admite o registro. Zero pode ser aplicado e alterado
  depois; cabine e carga não recebem escritas independentes de velocidade.
- Painel direito com barra vertical e rodapé do mapa em duas linhas para manter
  os controles acessíveis em janelas menores, com quebra de texto ajustada à largura.
- Reposicionamento lateral de independente com física inicializada e uma
  edição candidata do conjunto cabine/carga, protegida pelo vínculo nativo.
- No modo normal, lotes de 1 a 8, usando a rotina do próprio jogo em um ciclo
  de retomar e pausar; cabine e carga contam como um conjunto.
- No modo normal, distância de 8 a 50 unidades nos independentes e de 30 a 50 para caminhão
  ou referência composta e ônibus tipo 5, sem equivalência estabelecida em metros.
- Modo experimental explícito, com aviso persistente de alto risco de
  travamento/perda de física, distância positiva sem o teto de 50 e pedidos
  maiores sujeitos aos recursos disponíveis. A fila é executada em grupos
  de até oito; **Cancelar fila** remove só o que ainda não foi preparado.
- Estatísticas de objetos ativos e inicializados, objetos/nós livres e fila,
  com aviso quando objetos conhecidos deixam de ter física inicializada.
- Botões **Pausar PCSX2** e **Retomar**, quando a instalação Windows da
  conexão PINE e seu menu compatível são identificados.
- Receitas JSON para reaplicar as ações sobre exatamente o mesmo estado inicial.
- Exportação **Salvar estado…** para `.p2s`, implementada para a instalação
  portátil; o usuário confirmou a exportação real. O arquivo exportado ainda
  não foi restaurado em teste. A sugestão fica em `outputs/events/`, com nome
  único e caminho retornado no rodapé. A restauração usa
  **Sistema → Carregar estado → Arquivo…** no PCSX2.

Na sessão atual, os dez slots de Burnout 3 já estavam ocupados e a exportação
por PINE foi recusada para preservar os arquivos existentes. A alternativa
**Sistema → Salvar estado → Arquivo…**, com destino novo, produziu uma cópia
de controle validada como ZIP com memória EE de 32 MiB, sem substituir originais.
Esse resultado é da rota manual de arquivo, não do botão PINE com slots cheios.
O leitor de configuração aceita padding NUL somente no final do INI UTF-8 sem BOM
examinado; não ignora NUL interno nem altera a configuração do emulador.

O emulador deve estar pausado ao listar e editar. Use **Pausar PCSX2** ou o
menu **Sistema → Pausar** do emulador correto. A pausa interna com **Start**
não suspende o núcleo da mesma forma. Para acrescentar um lote, a interface
prepara a operação durante a pausa; o usuário retoma uma vez para executar
as criações e pausa novamente para a finalização.
Só após a confirmação deve retomar para jogar. Os detalhes estão no
[guia de primeiro uso](editor-quickstart.md).

As ações do controlador passam por um único trabalhador da interface, e uma
criação pendente bloqueia novas edições. Falhas de escrita ambíguas não são
repetidas automaticamente. As verificações de pausa e leitura de retorno não
tornam a operação uma transação: retomar o emulador durante uma escrita pode
interromper a edição. Uma falha que exigir referência limpa deve ser resolvida
recarregando essa referência, pausando o emulador e conectando novamente.

## Lotes e conjunto cabine/carga

O usuário confirmou explicitamente que o lote de carros e o caminhão com carga
apareceram e funcionaram. O registro local inclui `batch_finished` para oito
`COMPCAR14` e para um par `HEVYCAR22` + `HEVYCAR27`. Também houve três registros
posteriores `batch_not_finalized`, após mudança da instância ou identidade.
Esses casos não foram alinhados como se a referência antiga ainda fosse válida.
Sucessos específicos e bloqueios de segurança não demonstram validade universal.

O movimento composto é uma implementação candidata: prepara onze valores
protegidos para deslocar cabine/carga, sem separar o vínculo. O relato de criação
do conjunto não comprova movimento e colisão após esse reposicionamento.
Um quarto caminhão-tanque e seus efeitos de explosão continuam sem validação.
Detalhes de uso e evidência em [batches-trucks-and-pause.md](batches-trucks-and-pause.md).

A revisão seguinte da finalização restaura o hook no último stub e publica a
conclusão somente numa landing fixa de doze bytes, preservada pela limpeza.
Isso protege a retomada do EE caso a pausa ocorra enquanto ele ainda termina
essa saída. Após reabrir o editor com esse builder, o usuário confirmou:
**“Lote e exportação funcionaram”**. Essa rodada confirmou manualmente o novo
fluxo e a exportação real; não incluiu restauração do arquivo exportado.

Leituras posteriores do registro local mostram finalização de oito vans
`HEVYCAR33` no caminho 53 e de dois pares `HEVYCAR22` + `HEVYCAR27` em cada
um dos caminhos 34 e 53. Um registro ainda posterior recusou o perfil porque
as estruturas de tráfego não passaram na verificação, mantendo uma pendência.
Essa recusa não estabelece travamento ou falha geral; os limites de perfil
continuam ativos mesmo após os ensaios bem-sucedidos.

## Recuperação explícita de solicitações restauradas

O diagnóstico desta etapa ligou uma pendência antiga ao recarregamento de um
estado feito antes da limpeza: a rotina temporária voltou à memória junto
com aquele estado. **Finalizar pendência** reconhece apenas payloads canônicos
v1/v2 baseados na landing, com correspondência no registro local e prova de que
o lote devolveu o controle ao jogo. Código desconhecido ou execução incompleta
continua bloqueado.

Uma recuperação real alterou somente a área temporária de 4 KiB. As regiões
classificadas de objetos, nós e matrizes permaneceram idênticas byte a byte;
nenhum veículo foi reposicionado. Isso encerrou o código antigo, sem recuperar
seu alinhamento ou sua receita JSON. Os dumps, tokens e hashes privados dessa
conferência não são distribuídos.

O formato v2 liga a publicação de conclusão a um token da geração daquela
solicitação e evita reutilização do histórico conhecido. Os probes e o token
esperado precisam concordar: uma publicação de outro lote não conclui o atual.
O formato v1 com landing permanece reconhecido somente para recuperação
controlada de uma solicitação antiga já encerrada.

A ação de recuperação é explícita e passa pelo trabalhador da interface.
Ela continua acessível com perfil de tráfego inválido, sem seleção de veículo.
Se a limpeza for confirmada e a leitura seguinte falhar, o aviso de sucesso é
preservado e a lista/edição ficam bloqueadas até uma leitura válida.

Um novo lote de ônibus tipo 5 em formato v2 foi preparado. A conferência foi
interrompida antes de confirmar sua finalização; isso não confirma movimento,
presença visível ou colisão de ônibus em execução.

## Densidade experimental e criação no ponto

O usuário relatou perda de física e congelamento/assert VIF em cenas com mais
de cinquenta carros adicionais e muitos envolvidos no mesmo impacto. O assert
`FQC = 0 on VIF FIFO READ!` indica uma leitura FIFO com contagem zero no emulador;
não é um contador de carros nem comprova um teto geral de cinquenta. A pesquisa
encontrou outros recursos finitos, mas não atribuiu a causa exata da falha.
As fontes, o escopo estático e as hipóteses estão em
[high-density-experiments.md](high-density-experiments.md).

O modo experimental da interface libera limites próprios do editor; não aumenta
as estruturas fixas do jogo e não corrige o crash. Cada pedido aceita no máximo
253 por causa do pool conhecido e precisa caber nas reservas reais de objetos,
nós e colisão. Um conjunto cabine/carga usa dois objetos. Pedidos acima de oito
viram grupos sucessivos de até oito, com confirmação de retomar/pausar a cada
grupo; eles não executam centenas de alocações num único frame. Cancelar a fila
não desfaz veículos criados ou o grupo já preparado.

Com o toggle ativo, uma distância positiva e finita deixa de ter o intervalo
artificial de 8/30 a 50, e a proteção de proximidade é relaxada. O caminho ainda
precisa existir e ter trecho utilizável. Identidade, pausa, modelo carregado,
formato de código, conclusão e limites conhecidos de memória continuam exigidos.
As estatísticas da interface descrevem os objetos da sessão; não demonstram
que todos possam participar de uma batida com física completa.

**Adicionar no ponto** usa um único veículo ou conjunto por ação. X/Z podem vir
do alvo na vista de cima ou dos campos manuais; a implementação aproxima o
ponto ao melhor caminho entre os carregados que têm referências válidas. No
modo normal, limita a lateral à largura admitida e recusa um pedido muito
distante. No experimental, admite uma lateral fora dessa largura, ainda sem
buscar terreno ou definir Y. O resultado pode diferir do clique: não se trata
de um posicionamento exato em qualquer superfície, carregamento de cenário
novo ou teleporte de um corpo existente.

Para um objeto deslocado fora da faixa que ainda mantenha o layout e a física
admitidos, o modo experimental pode oferecer o controle lateral de 0% a 100%
para tentar trazê-lo de volta. Isso não o torna uma referência normal de criação
enquanto estiver fora do perfil. Receitas registram a natureza experimental das
ações; sua carga é recusada com o toggle desligado, sem ativação automática pelo JSON.

Esses fluxos novos têm validação automatizada, mas não receberam ensaio real
nesta etapa. O relato anterior de criação/colisão e o novo relato de falha com
muitos carros não validam a implementação ampliada ou a criação por ponto.

## Caminhos e velocidade nominal

A rede desenhada inclui vias com referência observada e candidatos encontrados
por descritores e geometria reconhecidos. Leituras e amostras são limitadas por
orçamento; dados incompletos são omitidos e a interface conserva o aviso de
visualização parcial. Bordas e centro representam o seguimento do tráfego,
não a malha visual ou a colisão do asfalto. A projeção X/Z pode sobrepor vias em
alturas diferentes. As setas sempre representam progressão geométrica; um sentido
de trânsito só é corroborado quando a referência móvel e sua orientação passam
nas verificações. Candidatos não se tornam referências de criação pelo desenho.

O campo de controle desejado e o avanço de seguimento foram separados. A
conversão exibida em km/h é nominal; não estabelece que uma unidade do mundo
seja um metro nem mede o movimento da carroceria. **Aplicar velocidade** altera
somente o alvo protegido pelo perfil. O seguimento continua sendo calculado
pelo jogo, inclusive para filas e obstáculos, e a carga usa a cabine como
referência em vez de receber um alvo avulso.

O alvo zero não impede uma edição posterior de um registro que ainda conserve
o layout admitido. Essas mudanças também podem ser registradas como ações
`set_speed` em receitas para o mesmo estado inicial; ações experimentais continuam
exigindo o toggle explícito ao carregar. A interface consulta uma captura
pausada e apresenta escala nominal, sem prometer velocímetro contínuo, velocidade
real calibrada ou estabilidade de uma cena densa. A pesquisa e os limites estão
em [routes-and-speed.md](routes-and-speed.md).

Uma conferência offline numa referência preservada produziu uma prévia de 27
caminhos admitidos, com P21 em destaque. Os bytes da memória fornecida à leitura
permaneceram idênticos. É uma verificação da geometria e da geração da prévia,
separada de uma captura da interface real ou de um teste de comportamento no jogo.

## Limites e próxima validação

A interface usa os modelos e caminhos já carregados pelo jogo. As alterações
ocorrem na sessão atual, sem gravar recursos do ISO ou arquivos persistentes de
Crash Events. Um `.p2s` pretende preservar a sessão para restaurá-la no PCSX2;
ele não transforma o layout em recurso permanente do jogo. **Restart**, troca de evento e carregamento de outro estado podem
recriar o tráfego. Um preset JSON guarda uma receita; ele não substitui um
save state e não resolve a persistência no evento.

Os testes automatizados verificam o protocolo, o perfil, a rotina de criação,
o fluxo da interface e as simulações de controle de janela/exportação.
Esses resultados não demonstram impacto,
estabilidade prolongada ou funcionamento de todos os modelos e níveis.
A integração e o relato manual acima cobrem somente os ensaios descritos.
Edição dentro do jogo,
novos locais de Crash e gravação persistente continuam como etapas futuras.

Os testes posteriores do usuário, o diagnóstico de veículos bloqueados e a
pesquisa sobre cabine/carga e a hipótese de três tanques estão em
[traffic-capacity-and-trucks.md](traffic-capacity-and-trucks.md).
