# Burnout 3 Crash Editor — pesquisa experimental

Ferramentas próprias para investigar um futuro editor de eventos do Crash Mode
de Burnout 3: Takedown. **Não existe editor dentro do jogo neste repositório.**
Há um protótipo que reposiciona um veículo existente em uma nova cópia de
save state, validado em um teste controlado. Um ensaio local também criou uma
instância adicional no Grand Slam, que o usuário relatou ter visto e atingido
normalmente em um teste manual. Edição persistente de eventos e locais novos
são etapas posteriores.

O repositório contém somente código e documentação. Cada usuário fornece sua
própria cópia extraída do jogo, ferramentas e, quando necessário, save states.
Não são incluídos ISO, ELF, BIOS, recursos, saves, dumps, código descompilado,
exportações de análise nem Ghidra/JDK/PCSX2.

## Requisitos

- Python 3.10 ou posterior para os scripts de leitura, usando somente a biblioteca padrão.
- Para análise nativa: Ghidra com a extensão Emotion Engine Reloaded e linguagem
  `r5900:LE:32:default`. A instalação usada na pesquisa foi Ghidra 12.2 com JDK 25
  e extensão v2.1.39 correspondente. As ferramentas não são baixadas pelos scripts.
- O launcher de Ghidra é PowerShell para Windows. Os leitores Python são portáveis.
- A inspeção de save state usa ZIP com um único `eeMemory.bin` de 32 MiB e um
  perfil específico do executável USA; não é um leitor universal de saves.

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

## Estado e próximos passos

Consulte [docs/findings.md](docs/findings.md) e o marco de reposicionamento para
fatos e limites. O teste controlado ligou um objeto de RAM a uma mudança visual
localizada e verificou atualização dos limites de colisão. Isso não demonstra
um editor de eventos completo. Ainda faltam testes de física e repetição mais
amplos, generalizar a criação de veículos e uma interface de edição.
O reempacotamento implementado é de save states, não de recursos do jogo.

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
O código temporário foi removido da cópia entregue. Esse criador ainda não
está empacotado como ferramenta portátil no repositório. Detalhes em
[docs/vehicle-creation-milestone.md](docs/vehicle-creation-milestone.md).

Os endereços conhecidos pertencem ao perfil USA pesquisado. Uma versão diferente
do jogo exige nova validação. Pseudocódigo, nomes inferidos e valores plausíveis
não demonstram por si só o comportamento em execução.

## Conteúdo permitido

A `.gitignore` usa uma allowlist de código, Markdown e configuração de exemplo.
Não coloque artefatos do jogo ou resultados de análise dentro de `scripts/` ou
`docs/`. Não há licença escolhida para este projeto; os termos de uso e
redistribuição do código ainda precisam ser definidos pelo titular.
