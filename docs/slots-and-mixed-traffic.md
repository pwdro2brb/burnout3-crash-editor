# Slots, referências paradas e lotes alternados

Esta revisão acrescenta arquivamento de slots e criação com modelos alternados.
Os fluxos novos ainda precisam de confirmação no PCSX2 em execução; os ensaios
automatizados usam arquivos temporários e memória copiada.

## Liberar um slot preservando o save

1. Conecte o editor ao PCSX2 e pause o emulador. Finalize qualquer criação
   pendente antes de administrar os arquivos de estado.
2. Na aba **Projeto**, clique em **Gerenciar slots…**. A lista mostra os dez
   índices usados pelo editor, os arquivos encontrados e seu tamanho.
3. Selecione um slot ocupado e use **Arquivar e liberar selecionado**. Confira
   os caminhos apresentados antes de confirmar.
4. Aguarde a confirmação. A cópia fica em `editor-slot-backups/slotNN-…`, dentro
   da instalação portátil reconhecida. O caminho completo aparece na resposta.

O arquivamento copia e verifica todos os arquivos reconhecidos daquele slot
antes de liberar seus nomes originais. As versões nas pastas principal e
específica do jogo, quando ambas existem, ficam separadas em `flat/` e
`nested/` dentro do backup. O arquivo `backup.json` relaciona os caminhos e
hashes. Outros slots e a configuração do emulador são preservados.

A ação não apaga definitivamente o save: o `.p2s` arquivado pode ser escolhido
em **Sistema → Carregar estado → Arquivo…** no PCSX2. Guarde a pasta do backup.
Um estado danificado ou vazio pode ser arquivado para liberar o slot, mas
preservar seus bytes não o torna carregável.

Links, redirecionamentos e arquivos acima do tamanho admitido são bloqueados.
Se o emulador for retomado ou os arquivos mudarem durante o processo, a
operação para e preserva as cópias. Se parte do slot já tiver sido arquivada,
a mensagem informa isso; não repita automaticamente. Atualize a lista e
confira o backup. Liberação de arquivo não é uma transação atômica com ações
externas feitas no emulador.

## Usar veículos parados e na contramão

Estar na contramão em relação ao jogador não é um motivo de bloqueio do
perfil. A referência usa seu próprio caminho e orientação. Um controlador de
tráfego com avanço zero também pode servir de referência quando caminho,
parâmetros e física estão válidos.

Selecione o veículo e confira a explicação dos detalhes quando uma ação estiver
desabilitada. Um carro parado no trânsito pode ter um caminho válido; um
objeto estacionário do cenário pode não ter nó ou caminho de tráfego.
Esses casos não são equivalentes. Cargas vinculadas continuam sendo editadas
pela cabine, e tipos físicos ainda não reconhecidos permanecem bloqueados.
Não há liberação indiscriminada de qualquer objeto nem movimento livre fora
dos caminhos pesquisados.

## Criar um lote com modelos alternados

1. Pause e selecione uma referência habilitada.
2. No painel **Adicionar veículos atrás**, escolha **Alternar modelos** e
   **Escolher modelos alternados…**.
3. Marque pelo menos dois modelos com **Ctrl/Shift** e confirme **Usar seleção**.
   A ordem mostrada se repete no lote: por exemplo, carro → van → carro → van.
4. Defina distância e quantidade e use **Adicionar veículos atrás**. Retome e
   pause para concluir cada grupo, como nos lotes anteriores.

Só entram na seleção os modelos independentes carregados e admitidos pela
leitura atual. Na interface, caminhões com carga continuam em **Modelo único**,
com a carga nativa compatível. Ônibus podem exigir o espaçamento de veículos
grandes. O lote é validado antes da primeira escrita; uma escolha inválida
não é ignorada silenciosamente.

O modo normal continua limitado a oito por grupo. Pedidos ampliados passam
pelas verificações de capacidade e pela fila experimental; modelos alternados
não aumentam o limite seguro de colisões do jogo.

## Variação visual experimental

**Original (0)** conserva o valor do argumento nativo usado anteriormente.
**Alternar variações (0–7)** passa valores diferentes ao criador nativo ao longo
do lote. O efeito na cor depende do modelo e ainda precisa de confirmação.
Não há associação comprovada entre cada índice e uma cor, nem garantia de oito
cores diferentes ou de que todos os veículos mudem de pintura. A opção atua
nos novos veículos do lote; não repinta automaticamente os já presentes.

Receitas de ações registram o modelo e a variação de cada criação confirmada.
Projetos continuam preservando a cena por seus estados `.p2s` locais. Nenhum
save, backup ou recurso do jogo é incluído no repositório.
