# Burnout 3 Crash Editor — pesquisa experimental

O jogador confirmou o teste do **Grand Slam editado na ISO**. A próxima etapa é identificar a origem do primeiro carro vermelho e tornar sua posição editável no arquivo do evento. Consulte o [histórico do projeto e dos testes](docs/contexto-do-projeto.md) e o [plano de desenvolvimento com as oito issues](docs/plano-de-desenvolvimento.md).

Ferramentas próprias para pesquisar e desenvolver um editor de eventos do
Crash Mode de Burnout 3: Takedown. Há uma **interface externa experimental**
para identificar modelos, reposicionar veículos e acrescentar lotes de
veículos atrás de uma referência ou criar um veículo num ponto X/Z do evento
carregado. A vista de cima também mostra a geometria pesquisada dos caminhos de
tráfego, e os veículos habilitados oferecem um alvo de velocidade nominal.
Na aba **Projeto**, a primeira versão de eventos personalizados organiza uma
base original e cenas editadas: **Testar cena** salva e retoma o jogo,
**Voltar ao início** restaura a cena salva e **Abrir projeto…** reabre o trabalho.
**Gerenciar slots…** permite arquivar um save verificado para liberar seu slot,
preservando uma cópia. Os lotes também oferecem modelos alternados e variação
visual experimental; referências paradas são admitidas quando física e caminho
estão prontos. Veja [slots e lotes alternados](docs/slots-and-mixed-traffic.md).
Há suporte experimental
a cabine com carga, limitado a pares nativos já carregados. A integração real confirmou leitura,
reposicionamento e criação pelo controlador; o usuário também relatou presença
e colisão da van preparada pela interface no Grand Slam.
Em **Projeto → Eventos nativos…**, o editor também abre os 100 eventos de Crash
da extração USA. Dá para ver as vias da pista, trocar a ordem dos modelos em
um grupo, mudar as metas das medalhas e ajustar quantas batidas ativam o
Crashbreaker. A exportação gera arquivos separados ou uma nova cópia da ISO.
O catálogo abre com o PCSX2 fechado. Veja o [guia de eventos nativos](docs/native-crash-events.md).

Os ensaios anteriores em cópias de save states confirmaram reposicionamento e
criação no Grand Slam. O usuário relatou ter visto e atingido o veículo
adicional normalmente. A rodada seguinte identificou e acrescentou uma van
`HEVYCAR33`, com confirmação manual de presença e colisão. Os detalhes e os
limites da finalização estão em [editor-status.md](docs/editor-status.md).
Em uma rodada posterior, o usuário confirmou explicitamente que **ambos**
funcionaram: o lote de carros e o caminhão com carga. O registro local inclui
finalização de oito `COMPCAR14` e de um conjunto `HEVYCAR22` + `HEVYCAR27`.
Também houve finalizações recusadas após mudança de instância ou identidade;
os resultados não validam todos os níveis, modelos e situações.

A revisão que introduziu a saída protegida foi testada antes da etapa atual.
Após reabrir aquela versão do editor, o usuário confirmou: **“Lote e exportação
funcionaram”**. A restauração do arquivo exportado ainda não foi testada.
Há sucessos registrados em diferentes caminhos e bloqueios de perfil posteriores;
isso não estabelece estabilidade geral.

Na rodada seguinte, o usuário confirmou que as novas mudanças funcionaram,
incluindo a revisão com caminhos e velocidade, mas relatou uma espera infinita
depois de criar vários carros. A revisão de 15/11/2026 limita a espera pela
física de um lote já encerrado e acrescenta ajuste de velocidade para uma
seleção de veículos. A confirmação anterior não valida essas duas correções.
Em seguida, o usuário confirmou **“Está tudo funcionando!”**, abrangendo a
finalização dos lotes e a velocidade em grupo. É uma confirmação manual de uso;
não estabelece estabilidade geral nem confirma a restauração do `.p2s` exportado.
O guia da primeira versão está em [Projetos de eventos de Crash](docs/custom-event-projects.md),
incluindo a alternativa manual quando todos os slots estão ocupados. O fluxo
novo foi verificado offline e ainda precisa de confirmação de restauração e
repetição no jogo.

O repositório contém somente código e documentação. Cada usuário fornece sua
própria cópia extraída do jogo, ferramentas e, quando necessário, save states.
Não são incluídos ISO, ELF, BIOS, recursos, saves, dumps, código descompilado,
exportações de análise nem Ghidra/JDK/PCSX2.

## Requisitos

- Python 3.10 ou posterior, usando somente a biblioteca padrão. A interface
  gráfica também exige Tcl/Tk, normalmente incluído no instalador do Python para Windows.
- Para editar a sessão em andamento: Burnout 3 USA `SLUS-21050`, CRC `BEBF8793`, no PCSX2
  **1.7.2521**, com PINE habilitado numa instalação de teste.
- Para editar o evento no disco, use a extração USA com as pastas `DATA` e
  `TRACKS`. Para gerar uma ISO, forneça também a imagem correspondente.
- Para análise nativa: Ghidra com a extensão Emotion Engine Reloaded e linguagem
  `r5900:LE:32:default`. A instalação usada na pesquisa foi Ghidra 12.2 com JDK 25
  e extensão v2.1.39 correspondente. As ferramentas não são baixadas pelos scripts.
- O launcher de Ghidra é PowerShell para Windows. Os leitores Python são portáveis.
- A inspeção de save state usa ZIP com um único `eeMemory.bin` de 32 MiB e um
  perfil específico do executável USA; não é um leitor universal de saves.

## Editor do evento atual

Abra **Abrir Editor.cmd** na pasta do projeto, ou execute:

```powershell
python -B scripts/editor/run_editor.py
```

Carregue o evento no PCSX2 de teste e conecte. Quando disponíveis, use os botões
**Pausar PCSX2** e **Retomar** do editor; a pausa é confirmada pela conexão PINE.
O menu **Sistema → Pausar** do emulador é a alternativa manual. Pause antes de
atualizar ou editar. A pausa do menu do jogo com **Start** não basta.
O editor não inicia o emulador nem dirige o veículo.

- **Veículos presentes:** modelo, categoria, posição e valores nominais de alvo
  e seguimento dos objetos da sessão, quando existe um nó de tráfego reconhecido.
- **Catálogo carregado:** todos os modelos encontrados na memória, incluindo os
  que ainda não estão liberados para criação. `COMPCAR14` é classificado pelo
  jogo como **Car**; `HEVYCAR33` e `HEVYCAR35`, como **Van**; `HEVYCAR20`, como **Bus**.
- **Vista de cima:** vias de tráfego pesquisadas, com bordas, centro, setas de
  progressão e posições dos veículos. **Mostrar vias** alterna a geometria;
  **Caminho** enquadra o caminho do veículo selecionado, **Enquadrar** mostra
  o conjunto, a roda aproxima e arrastar com o botão direito move a vista.
  Caminhos candidatos sem veículo associado aparecem como `P?`, com uso atual
  não confirmado. As faixas não são a malha de asfalto, e alturas podem se
  sobrepor na projeção X/Z. Um clique seleciona o veículo para edição.
  **Marcar posição** e os campos X/Z permitem escolher um ponto para uma nova
  criação, aproximado a um dos caminhos com referência móvel válida; a presença
  de um candidato no desenho não o habilita para criação.
- **Velocidade:** os detalhes distinguem **Alvo nominal** e **Seguimento nominal**
  em km/h. Use **Ctrl/Shift** ou **Selecionar aptos para velocidade** para aplicar
  o mesmo alvo a vários registros, inclusive zero. A seleção inteira precisa
  estar habilitada; em caminhões, selecione a cabine. A linha em foco continua
  sendo a referência para posição e criação. Filas e obstáculos podem reduzir
  o avanço; a escala é nominal, sem medição física calibrada em tempo real.
- **Edição:** deslocamento na largura do caminho e, no modo normal, lotes de 1 a 8
  atrás de uma referência, com os modelos carregados e admitidos pelo perfil. Caminhões
  oferecem seleção de carga compatível; a quantidade conta conjuntos completos.
- **Modo experimental:** aviso persistente de alto risco de travamento e perda
  de física; permite pedidos maiores e distância positiva sem o teto de 50.
  Pedidos de até 253 são sujeitos à capacidade real disponível e executados
  em grupos de até oito, com um ciclo de retomar/pausar por grupo. **Cancelar
  fila** descarta o restante; o grupo já preparado ainda precisa finalizar.
- **Estatísticas:** objetos ativos, física inicializada, recursos livres e
  operações na fila. Componentes de caminhões contam como objetos separados;
  essas contagens não estabelecem a capacidade segura de uma batida.
- **Recuperação:** **Finalizar pendência** confere e limpa uma solicitação
  reconhecida, inclusive quando o perfil impede listar os veículos. A conexão
  fica disponível e a edição permanece bloqueada até uma leitura válida. Quando
  todas as criações terminaram e só falta confirmar a física, a espera fica
  limitada a cinco segundos. A limpeza conserva os veículos criados pelo jogo,
  cancela a fila e não confirma alinhamento nem receita desse lote. A rotina
  precisa estar encerrada; código ativo ou desconhecido continua protegido.

O perfil também admite associações nativas consistentes de tipo 3 nas vans
`HEVYCAR17/18` e tipo 5 nos ônibus `HEVYCAR19/21`. Exige dois pontos físicos,
render e colisão coerentes. Ônibus carregado sem associação ativa consistente,
como `HEVYCAR20` na referência examinada, continua bloqueado. Tipos especiais
6 a 10 não foram habilitados; o teste real de ônibus ainda está pendente.

A criação de cada grupo de até oito usa um ciclo: preparar com o emulador pausado, retomar
para o jogo criar as instâncias e pausar novamente para finalizar todas.
Depois da confirmação, retome para dirigir e testar. A interface acompanha a
etapa; o teste de presença e colisão é feito pelo usuário.

O modo experimental libera restrições do editor, sem ampliar os pools fixos do
jogo. O fim do caminho, modelos compatíveis, pausa confirmada e verificações de
memória continuam exigidos. A criação por ponto não permite definir Y, carregar
mapas ausentes ou teleportar um corpo existente. Uma posição fora da largura
normal da via pode perder física; quando o perfil ainda admitir a edição, o
controle lateral de 0% a 100% permite tentar devolvê-la à via com o modo ligado.
Receitas com ações experimentais só são carregadas com o toggle explicitamente
ativo; abrir um JSON não ativa esse modo automaticamente.

O assert `FQC = 0 on VIF FIFO READ!` relatado após cenas muito densas não prova
um limite geral de cinquenta carros. Esta revisão não corrige o crash nem
desativa asserts do emulador. A investigação e seus limites estão em
[muitos veículos e testes experimentais](docs/high-density-experiments.md).

As alterações valem para a sessão atual. As configurações JSON são receitas
para **o mesmo estado inicial**, não novos arquivos de evento. Reiniciar o
evento ou carregar outro estado pode descartar as alterações. **Salvar estado…**
exporta um `.p2s` para reabrir no PCSX2 quando há um slot temporário livre.
Na sessão atual, os dez slots já estão ocupados e o botão recusa substituir
qualquer um deles. Use **Sistema → Salvar estado → Arquivo…** no PCSX2 com um
destino novo; uma cópia de controle foi salva e validada por essa rota manual.
A restauração do arquivo ainda não foi testada. A sugestão de destino do editor
é `outputs/events/`, com nome único; o rodapé mostra o caminho exportado. Para
restaurar, use **Sistema → Carregar estado → Arquivo…** no PCSX2. Combinações de
caminhão não observadas continuam bloqueadas. O reposicionamento conjunto de
cabine/carga ainda é experimental.

Uma edição pode usar um veículo observado depois da referência inicial, desde
que ele passe nas verificações do perfil. Se a receita depender dessa referência
sem criação confirmada, **Salvar configuração** recusa o JSON. Preserve a sessão
em `.p2s` ou inicie uma nova sessão com o cenário atual como referência.

Recarregar um estado salvo antes da limpeza pode recolocar código temporário
antigo na memória. A recuperação explícita exige correspondência com o registro
local, payload canônico e conclusão válida; não reposiciona veículos nem recupera
uma receita antiga. A conclusão v2 usa um token por geração para distinguir lotes.

Consulte o [guia de primeiro uso](docs/editor-quickstart.md) e o
[estado da implementação e evidências do catálogo](docs/editor-status.md), além de
[lotes, caminhões, pausa e preservação](docs/batches-trucks-and-pause.md) e
[caminhos e velocidade](docs/routes-and-speed.md).

## Caminhos locais

Copie `config.example.json` para um arquivo local, por exemplo `config.local.json`,
e preencha seus próprios caminhos. O exemplo usa `null` e não contém dados pessoais.
O arquivo local é ignorado pelo Git. Alternativamente, use argumentos ou variáveis:

| Variável | Uso |
| --- | --- |
| `B3_GAME_ROOT` | Pasta extraída que contém `SLUS_210.50`, `DATA` e `TRACKS` |
| `B3_OUTPUT_ROOT` | Pasta separada para relatórios, projetos e logs |
| `B3_GHIDRA_DIR` | Raiz de uma instalação local do Ghidra |
| `B3_JAVA_HOME` | Raiz do JDK usado pelo Ghidra |

Prioridade: argumento explícito, variável de ambiente, configuração JSON.
Sem caminho de saída, usa-se `outputs/`, ignorado pelo Git. Os diretórios de jogo
e saída devem ser árvores separadas, sem sobreposição. Os scripts de recursos
recusam sobrescrever os relatórios existentes: use uma pasta nova por execução.

Exemplos em PowerShell, depois de configurar as variáveis ou o JSON:

```powershell
python scripts/resources/index_binary.py --config config.local.json
python scripts/resources/survey_resources.py --config config.local.json
python scripts/resources/parse_stagehed.py --config config.local.json
```

Os mesmos scripts aceitam `--game-root <pasta-extraida> --output-root <pasta-saida>`.
O indexador produz `candidate_strings.tsv`, usado pela triagem do Ghidra.

```powershell
./scripts/ghidra/Invoke-Ghidra.ps1 -Config config.local.json -Mode Import
```

O import cria um projeto de análise separado; não modifica o ELF. Para consultar
um projeto existente, use `-Mode Process` (sem reanálise, modo read-only),
`-ProjectDir`, `-ProjectName`, `-PostScript` e `-PostArgs` explícitos. Os scripts
Java recebem o destino como primeiro argumento. `ExportFunctions.java` exporta
funções para investigação local; esses resultados devem permanecer fora do Git.
No launcher, o primeiro argumento de exportação deve ficar dentro de `OutputRoot`.
O launcher não muda variáveis de ambiente globais nem configura o REA.

Para inspecionar um save state fornecido explicitamente:

```powershell
python scripts/runtime/inspect_savestate.py <estado.p2s> --output-root <pasta-saida> --output traffic.json
```

O inspector lê a RAM em memória, compara listas/bitmaps/índices, calcula hashes
antes/depois e não extrai nem regrava o save. O limite padrão é oito exemplos;
`--max-examples` permite 0..16. Relatórios incluem caminhos locais e amostras de
RAM: devem permanecer privados e ignorados. Formatos ZIP com compressão não
suportada pelo Python local podem exigir uma configuração compatível no PCSX2.

## Protótipo de reposicionamento em save state

`scripts/runtime/reposition_vehicle.py` gera um **arquivo novo**. Ele exige o
SHA-256 explícito da referência, um objeto ativo independente com node válido,
as quatro palavras de código de controle originais e os invariantes conhecidos
do pool. Os dois pontos físicos devem estar inicializados e separados; objetos
distantes com âncoras degeneradas são recusados. O perfil é específico do
executável USA pesquisado. Não aceita escrita
no arquivo de entrada nem sobrescrita de saída ou relatório.

Exemplo, com caminhos de teste e hash fornecidos pelo usuário:

```powershell
python scripts/runtime/reposition_vehicle.py --input <referencia.p2s> --output <nova-copia.p2s> --report <relatorio.json> --source-sha256 <sha256-da-referencia> --vehicle-index 9 --dx 2.1409912109375 --dz 0.3963623046875 --lateral 0.1
```

Esses valores pertencem ao primeiro ensaio estacionário. A direção lateral
deve ser recalculada para o caminho e o ponto da nova captura.

`--dx` e `--dz` transladam X/Z dos dois pontos de ancoragem e da transformação
atual; `--lateral` é opcional e deve estar em `0..1`. Y, normais, listas,
velocidades, alvo armazenado e limites de colisão não são editados pelo script.
O jogo precisa atualizar seus dados dependentes. O relatório registra campos,
hashes, endereços de todos os bytes diferentes e verificações do ZIP. Os outros
membros mantêm seus conteúdos e payloads comprimidos originais. O perfil de ZIP
admitido usa entradas simples stored/deflate, sem duplicatas, criptografia,
descritores de dados, ZIP64 ou múltiplos discos. Nenhum membro é extraído.

Use uma configuração isolada do emulador e cópias de teste. O protótipo não muda
o ISO nem os recursos do evento. Há um teste visual de 30 quadros e um teste
físico de tráfego em movimento no Grand Slam até 120 quadros configurados.
Outros modelos, impactos e persistência após reiniciar o evento ainda precisam
de investigação. Detalhes em [docs/repositioning-milestone.md](docs/repositioning-milestone.md)
e [docs/moving-traffic-reference.md](docs/moving-traffic-reference.md).

## Histórico dos primeiros testes

Consulte [docs/findings.md](docs/findings.md) e o marco de reposicionamento para
os resultados históricos, e [docs/editor-status.md](docs/editor-status.md) para
a interface em integração. O teste controlado ligou um objeto de RAM a uma
mudança visual localizada e verificou atualização dos limites de colisão.
Os testes automatizados cobrem transporte, perfil, criação, recuperação,
interface e exportação. A implementação do modo ampliado e da criação por ponto
não constitui validação real de cenas densas. Ainda faltam testes de física e repetição mais
amplos, confirmar a restauração e repetição dos novos projetos em jogo e
generalizar os modelos e eventos admitidos. O ciclo de projetos está descrito
em [custom-event-projects.md](docs/custom-event-projects.md).
O primeiro protótipo reempacotava save states. A edição nativa acrescentada depois gera uma nova ISO com os recursos editados. [Guia da edição nativa](docs/native-crash-events.md)

A nova referência foi confirmada como **Grand Slam**, incluindo a contagem
inicial. Um veículo continuou em movimento e manteve um pequeno deslocamento
lateral após 30 e 120 quadros configurados, com atualização automática do AABB.
Numa variante posterior com deslocamento maior, o usuário relatou mudança
visível e colisão funcionando. A associação visual ao índice interno e um
impacto instrumentado ainda não foram estabelecidos; veja
[docs/moving-traffic-reference.md](docs/moving-traffic-reference.md).

Um ensaio posterior chamou a rotina original do jogo para acrescentar um
objeto independente, depois alinhado cerca de 10,85 unidades atrás do alvo.
Pools, caminho e registros de colisão passaram nas verificações locais. No
teste manual, o usuário relatou que o carro apareceu e a colisão funcionou;
um impacto instrumentado e estabilidade prolongada ainda não foram validados.
O código temporário foi removido da cópia entregue. A rotina desse ensaio foi
generalizada no editor externo, cuja integração ainda está em validação.
Detalhes do ensaio anterior em
[docs/vehicle-creation-milestone.md](docs/vehicle-creation-milestone.md).

Os endereços conhecidos pertencem ao perfil USA pesquisado. Uma versão diferente
do jogo exige nova validação. Pseudocódigo, nomes inferidos e valores plausíveis
não demonstram por si só o comportamento em execução.

## Conteúdo permitido

A `.gitignore` usa uma allowlist de código, Markdown e configuração de exemplo.
Não coloque artefatos do jogo ou resultados de análise dentro de `scripts/` ou
`docs/`. Não há licença escolhida para este projeto; os termos de uso e
redistribuição do código ainda precisam ser definidos pelo titular.
