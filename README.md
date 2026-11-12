# Burnout 3 Crash Editor — pesquisa experimental

Ferramentas próprias para investigar um futuro editor de eventos do Crash Mode
de Burnout 3: Takedown. **Não existe editor pronto neste repositório.** O primeiro
marco é reposicionar um veículo de um evento existente e confirmar a mudança no
jogo. Adicionar veículos e usar locais novos são etapas posteriores.

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

## Estado e próximos passos

Consulte [docs/findings.md](docs/findings.md) para fatos e limites. Não há patch
espacial, criação de veículos, reempacotador ou interface de edição implementados.
Ainda precisamos confirmar visualmente uma referência do Crash na contagem
inicial ou antes do GO, ligando um objeto de RAM a um veículo visível. Novos
estados fornecidos pelo usuário passaram por verificações estruturais, mas o
frame inicial ainda não foi confirmado na tela. O plano é validar uma única
mudança reversível em uma cópia de teste antes de desenvolver edição persistente.

Os endereços conhecidos pertencem ao perfil USA pesquisado. Uma versão diferente
do jogo exige nova validação. Pseudocódigo, nomes inferidos e valores plausíveis
não demonstram por si só o comportamento em execução.

## Conteúdo permitido

A `.gitignore` usa uma allowlist de código, Markdown e configuração de exemplo.
Não coloque artefatos do jogo ou resultados de análise dentro de `scripts/` ou
`docs/`. Não há licença escolhida para este projeto; os termos de uso e
redistribuição do código ainda precisam ser definidos pelo titular.
