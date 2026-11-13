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
O perfil inicial oferece somente modelos carregados com associação observada
a tipos independentes 1 ou 2. Ônibus e componentes articulados precisam de
validação própria de tipo, vínculos e ciclo de vida. A aba **Catálogo carregado**
permite identificá-los, com **Criação não validada**, sem incluí-los na escolha
de novos veículos. A disponibilidade é calculada para a sessão carregada;
a lista estática de 40 modelos não significa que todos estejam na memória.

Em uma leitura posterior, o jogo também apresentou instâncias independentes
de `HEVYCAR20` com tipo 5. Sua criação continua bloqueada: a primeira versão
do editor admite apenas as associações independentes de tipo 1 ou 2.

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

## Implementação disponível

- Interface externa em Tkinter, aberta por `Abrir Editor.cmd`.
- Conexão PINE local, com validação de PCSX2 1.7.2521 e Burnout 3 USA,
  `SLUS-21050` / CRC `BEBF8793`.
- Identificação dos veículos presentes e dos modelos carregados.
- Vista de cima das posições X/Z, com seleção de veículo. Não contém malha ou
  desenho da pista e não acompanha o jogo em tempo real.
- Reposicionamento lateral de um carro ou van independente com física inicializada.
- Criação atrás de uma referência, usando a rotina do próprio jogo, com
  distância admitida de 8 a 50 unidades do jogo.
- Receitas JSON para reaplicar as ações sobre exatamente o mesmo estado inicial.

O emulador deve estar pausado com **Esc** ao listar e editar. A pausa interna
com **Start** não suspende o núcleo da mesma forma. Para acrescentar um veículo,
a interface prepara a operação durante a pausa; o usuário retoma com **Esc**
para executar a criação e pausa com **Esc** novamente para a finalização.
Só após a confirmação deve retomar para jogar. Os detalhes estão no
[guia de primeiro uso](editor-quickstart.md).

As ações do controlador passam por um único trabalhador da interface, e uma
criação pendente bloqueia novas edições. Falhas de escrita ambíguas não são
repetidas automaticamente. As verificações de pausa e leitura de retorno não
tornam a operação uma transação: retomar o emulador durante uma escrita pode
interromper a edição. Uma falha que exigir referência limpa deve ser resolvida
recarregando essa referência, pausando com Esc e conectando novamente.

## Limites e próxima validação

A interface usa os modelos e caminhos já carregados pelo jogo. As alterações
ocorrem na sessão atual, sem gravar recursos do ISO ou arquivos persistentes de
Crash Events. **Restart**, troca de evento e carregamento de outro estado podem
recriar o tráfego. Um preset JSON guarda uma receita; ele não substitui um
save state e não resolve a persistência no evento.

Os testes automatizados verificam o protocolo, o perfil, a rotina de criação
e o fluxo da interface. Nesta revisão passaram 41 testes distribuíveis e 25
testes locais com capturas privadas do perfil/controlador. Eles não demonstram
impacto, estabilidade prolongada ou funcionamento de todos os modelos e níveis.
A integração e o relato manual acima cobrem somente os ensaios descritos.
Edição dentro do jogo,
novos locais de Crash e gravação persistente continuam como etapas futuras.
