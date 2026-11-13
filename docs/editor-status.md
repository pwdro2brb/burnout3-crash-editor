# Editor externo e identificação de modelos

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

Em uma leitura posterior, o jogo também apresentou instâncias independentes
de `HEVYCAR20` com tipo 5. Sua criação continua bloqueada: a primeira versão
do editor não admite esse tipo 5.

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
- Vista de cima das posições X/Z, com seleção de veículo. Não contém malha ou
  desenho da pista e não acompanha o jogo em tempo real.
- Reposicionamento lateral de independente com física inicializada e uma
  edição candidata do conjunto cabine/carga, protegida pelo vínculo nativo.
- Lotes de 1 a 8, usando a rotina do próprio jogo em um único ciclo de retomar
  e pausar; cabine e carga contam como um conjunto.
- Distância de 8 a 50 unidades nos independentes e de 30 a 50 para caminhão
  ou referência composta, sem equivalência estabelecida em metros.
- Botões **Pausar PCSX2** e **Retomar**, quando a instalação Windows da
  conexão PINE e seu menu compatível são identificados.
- Receitas JSON para reaplicar as ações sobre exatamente o mesmo estado inicial.
- Exportação **Salvar estado…** para `.p2s`, implementada para a instalação
  portátil; o usuário confirmou a exportação real. O arquivo exportado ainda
  não foi restaurado em teste.

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

## Limites e próxima validação

A interface usa os modelos e caminhos já carregados pelo jogo. As alterações
ocorrem na sessão atual, sem gravar recursos do ISO ou arquivos persistentes de
Crash Events. Um `.p2s` pretende preservar a sessão para restaurá-la no PCSX2;
ele não transforma o layout em recurso permanente do jogo. **Restart**, troca de evento e carregamento de outro estado podem
recriar o tráfego. Um preset JSON guarda uma receita; ele não substitui um
save state e não resolve a persistência no evento.

Os testes automatizados verificam o protocolo, o perfil, a rotina de criação,
o fluxo da interface e as simulações de controle de janela/exportação.
Passaram **122 testes distribuíveis** e **35 privados**: 19 do controlador e
16 do perfil. Eles não demonstram
impacto, estabilidade prolongada ou funcionamento de todos os modelos e níveis.
A integração e o relato manual acima cobrem somente os ensaios descritos.
Edição dentro do jogo,
novos locais de Crash e gravação persistente continuam como etapas futuras.

Os testes posteriores do usuário, o diagnóstico de veículos bloqueados e a
pesquisa sobre cabine/carga e a hipótese de três tanques estão em
[traffic-capacity-and-trucks.md](traffic-capacity-and-trucks.md).
