# Editor do evento atual — primeiro uso

Esta interface externa edita o evento que está carregado no PCSX2. A interface
permite identificar os veículos presentes, deslocar um veículo na
largura da via, acrescentar lotes atrás de uma referência e criar um veículo
num ponto X/Z aproximado a caminhos carregados. Mostra a geometria pesquisada
das vias de tráfego e permite ajustar o alvo nominal de velocidade dos registros
admitidos. O modo normal usa grupos de
1 a 8; o modo experimental permite pedidos maiores sujeitos à capacidade. Caminhões
com carga usam somente pares nativos já carregados pelo jogo.

O perfil pesquisado é Burnout 3 USA, `SLUS_210.50`, no PCSX2 1.7.2521. Outros
executáveis e versões do emulador exigem validação própria. Use uma cópia de
teste do emulador e preserve uma referência do evento antes de editar.

## Abrir e conectar

1. Tenha Python 3.10 ou posterior com Tcl/Tk. O editor não instala dependências.
2. No PCSX2 de teste, habilite PINE e carregue o jogo e o evento que deseja editar.
   Na versão pesquisada, a configuração fica em `inis/PCSX2_vm.ini`, na seção
   `[EmuCore]`: `EnablePINE=enabled`. Se editar esse arquivo, feche o emulador
   antes, preserve uma cópia e reinicie-o depois. Altere somente a instalação
   de teste. A porta padrão é 28011 e a conexão é local.
3. Abra **Abrir Editor.cmd** na pasta do projeto e clique em **Conectar / nova sessão**.
4. Se aparecerem, use **Pausar PCSX2** e **Retomar** no editor. Esses botões
   identificam a instalação da conexão PINE e confirmam a pausa pelo emulador.
   Sem eles, use **Sistema → Pausar** no PCSX2 correto. **Start**, no menu de
   pausa do jogo, não substitui a pausa do núcleo.
5. Selecione um veículo em **Veículos presentes** para ver seu modelo e posição.
   Use **Atualizar lista** para reler a sessão atual. Após carregar outro estado
   ou evento, clique em **Conectar / nova sessão** antes de iniciar uma receita.

Ao selecionar um veículo bloqueado, os detalhes explicam se ele é um
componente vinculado, um tipo ainda não habilitado ou se o jogo ainda não
inicializou sua física. Estar listado não significa estar pronto para editar.

Em janelas baixas, use a barra vertical do painel direito para alcançar os
controles de velocidade, modelo e carga. A roda sobre o mapa continua reservada
ao zoom; o botão direito desloca a vista.

## Criar um projeto de evento

Na aba **Projeto**, dê um nome ao evento e use **Criar projeto…** com o PCSX2
pausado antes da batida. A referência original fica preservada. Edite os
veículos e finalize os lotes; **Testar cena** salva a versão e retoma o jogo.
Para repetir, pause e use **Voltar ao início**, que restaura a última cena
editada salva. **Restaurar base original** recupera a referência sem substituir
essa cena. Para reabrir o trabalho, selecione `event.b3event.json` em
**Abrir projeto…**.

O fluxo automático precisa de um slot livre e não substitui saves existentes.
Se todos estiverem ocupados, a seção **Alternativa sem slot livre** permite
salvar/carregar um `.p2s` pelo menu do PCSX2 e importar/conferir essa cena no
editor. O arquivo escolhido precisa corresponder à memória pausada verificada.
Veja o [guia de projetos](custom-event-projects.md) para o procedimento completo.
Os projetos conservam estados locais; o fluxo novo ainda precisa de confirmação
de restauração e repetição no jogo.

Se a identidade do jogo foi confirmada, mas o perfil de tráfego é recusado,
o editor mantém a conexão e desabilita a edição. Com o jogo pausado, **Finalizar
pendência** continua disponível, sem exigir seleção de veículo. Uma limpeza
bem-sucedida permanece informada mesmo se a leitura seguinte ainda falhar;
use **Atualizar lista** para liberar a edição somente após uma leitura válida.

Uma nova conexão limpa a receita de ações que ainda está no editor. Salve a
configuração antes de iniciar outra sessão, caso queira conservar essa receita.

O editor não inicia nem controla a direção do veículo no PCSX2. Se a conexão
falhar, confira se o jogo está carregado e se o PINE da instalação de teste
está habilitado. Evite manter dois emuladores usando a mesma porta PINE.

Também é possível abrir pelo terminal, a partir da pasta do projeto:

```powershell
python -B scripts/editor/run_editor.py
```

Para uma porta local diferente, use `--port 28112`. No PCSX2 wx pesquisado,
o ajuste de porta feito pelo diálogo PINE não permanece após reiniciar.

Para manter a janela do jogo visível ao pausar, desmarque **Ocultar a janela
quando estiver em pausa** nas configurações do PCSX2 de teste. Na instalação
pesquisada, isso corresponde a `CloseOnEsc=disabled` em `PCSX2_ui.ini`.
O editor não altera essa preferência automaticamente. Consulte os detalhes
de [pausa e preservação](batches-trucks-and-pause.md).

## Identificar e escolher o modelo

O identificador do carro usado no primeiro ensaio foi **COMPCAR14**. A tabela
de rótulos do próprio jogo o classifica como **Car**. O catálogo também distingue
categorias como Van, Bus, táxi e carretas; isso não identifica um fabricante
ou um modelo real de automóvel.

A lista de criação oferece **Mesmo modelo do selecionado** e os modelos
carregados e admitidos pelo perfil. Há tipos independentes 1/2/3/5 e conjuntos
nativos de cabine tipo 4 com carga tipo 11. Ao escolher uma cabine, a interface
mostra **Carga do caminhão** e somente combinações observadas e carregadas.
A carga não é oferecida como veículo avulso. Vans `HEVYCAR17/18` de tipo 3 e
ônibus `HEVYCAR19/21` de tipo 5 são admitidos quando há associação nativa
consistente e física pronta. `HEVYCAR20` apenas carregado, sem essa associação,
continua bloqueado. Tipos especiais 6 a 10 não estão habilitados. O teste real
de criação de ônibus ainda está pendente.

Nos independentes, o perfil exige dois pontos físicos inicializados e não
degenerados, coerência com a posição renderizada e o collider, além de caminho
e ocupação válidos. Um veículo distante com pontos zerados continua bloqueado.

A aba **Catálogo carregado** mostra todos os modelos encontrados, sua categoria
e o estado da criação: **Disponível**, **Disponível com caminhão** ou
**Criação não validada**. Assim é possível
identificar um ônibus carregado mesmo quando ele não aparece na escolha de criação.

## Visualizar os caminhos

1. Pause o PCSX2 e use **Atualizar lista**. Selecione um veículo e abra
   **Vista de cima**.
2. Ative **Mostrar vias** para ver bordas, centro e identificadores `P0`, `P1`
   etc. A via do veículo selecionado fica destacada; **Caminho** a enquadra.
   **Enquadrar** ajusta a vista ao conjunto mostrado. Use a roda para aproximar
   e arraste com o botão direito para deslocar a vista.
3. As setas indicam a **progressão do caminho**. Uma seta tracejada não comprova
   o sentido atual do tráfego. Caminhos candidatos sem veículo associado têm
   rótulo `P?`, cor mais clara e uso atual não confirmado.
4. Clique num ponto de veículo para selecioná-lo. O jogador aparece em vermelho
   com sua direção, quando essa referência está disponível. **Marcar posição**
   mantém o significado X/Z do mapa ao aproximar ou deslocar a vista.

As faixas mostram a geometria de seguimento do tráfego pesquisada na memória;
não são a malha de asfalto ou uma garantia de superfície dirigível. Ruas em
alturas diferentes podem se sobrepor na vista X/Z. Um caminho candidato visível
não libera a criação por ponto: ela continua exigindo referência móvel válida.
Se a leitura exceder seu orçamento ou omitir dados inválidos, o aviso informa
que a visualização é parcial. A vista corresponde à última leitura pausada,
atualizada com a lista; não acompanha os carros continuamente.

## Consultar e ajustar a velocidade

1. Pause o PCSX2, atualize a lista e selecione um ou mais veículos. Use **Ctrl**
   para escolher vários, **Shift** para um intervalo ou **Selecionar aptos para
   velocidade** para reunir os registros habilitados. A coluna
   **Nominal km/h A/S** mostra alvo e seguimento; os detalhes apresentam os
   nomes completos. Registros sem nó reconhecido mostram indisponível.
2. Quando o perfil admitir a alteração, preencha **Alvo nominal (km/h)** e
   clique em **Aplicar velocidade** ou **Aplicar aos N selecionados**. O mesmo
   alvo vale para todos os selecionados. Um registro bloqueado impede a ação
   inteira; ele não é ignorado. Zero é aceito; um alvo positivo pode ser
   reaplicado posteriormente. No modo normal, o máximo nominal é 386,24256 km/h,
   correspondente ao teto de controle pesquisado; isso não significa que o carro
   consiga atingir esse valor.
3. Para caminhão com carga, selecione a cabine. O editor não grava velocidade
   numa carga avulsa. Aguarde a confirmação e use **Retomar** para observar.

A linha em foco continua sendo a referência das ações de posição e criação;
selecionar vários não move nem acrescenta vários alvos por essas ações.

O alvo é o pedido ao controlador de tráfego, e o seguimento é um valor
recalculado pelo jogo. Uma fila, um obstáculo ou um veículo sobreposto pode
reduzir o avanço, apesar de o alvo permanecer alto. A escala km/h é **nominal**,
derivada dos campos pesquisados; não é uma medição física calibrada da carroceria.
O editor altera o alvo e deixa o jogo recalcular o seguimento. A leitura é feita
com o emulador pausado, não por um velocímetro contínuo.

Receitas JSON também registram alterações do alvo de velocidade para o mesmo
estado inicial. A exigência de ativar o modo experimental ao carregar ações
experimentais permanece. Consulte [caminhos e velocidade](routes-and-speed.md)
para a evidência e os limites dessa interpretação.

## Mover um veículo

1. Clique em **Pausar PCSX2** ou pause pelo menu do emulador e atualize a lista.
2. Selecione um veículo disponível para edição.
3. Ajuste **Posição na largura da via** e clique em **Aplicar posição**.
4. Use **Retomar** para continuar e observar.

O controle de 0% a 100% percorre a largura do caminho. Ele não corresponde
necessariamente a uma faixa de trânsito ou a uma borda de colisão da pista.
A posição longitudinal é mantida. Comece com alterações pequenas; alguns
objetos distantes ainda não têm seus pontos físicos atualizados e não podem
ser editados por este método.

Para um caminhão habilitado, selecione a cabine: a edição candidata move os
dados da cabine e da carga em conjunto, preservando o vínculo. O movimento e
a colisão após esse reposicionamento composto ainda exigem validação própria.
Tráfego na contramão também pode servir de referência quando a física e o
caminho estiverem inicializados; a direção relativa ao jogador não é o bloqueio.

## Adicionar um lote ou caminhão com carga

Os intervalos abaixo são do modo normal, com o toggle experimental desligado.

1. Com o emulador pausado, selecione o veículo de referência.
2. Escolha o modelo, **Quantidade** de 1 a 8 e **Distância atrás**. Para os
   independentes 1/2/3, o valor inicial é 10 e o intervalo é de 8 a 50 unidades do jogo.
3. Para uma cabine, escolha também a carga compatível. **Conjuntos** conta
   pares completos, não componentes. A carga nativa do alvo só é preselecionada
   quando seu vínculo foi validado. Para ônibus tipo 5, caminhão ou referência desses tipos,
   a distância mínima é 30; a interface ajusta o valor menor para 30.
4. Clique em **Adicionar veículos atrás** ou **Adicionar conjuntos atrás**.
   Use **Retomar** uma vez para executar o lote. Não repita o clique de criação.
5. Quando o editor solicitar, clique em **Pausar PCSX2**. O editor acompanha
   a operação e finaliza o lote nessa pausa, sem um ciclo manual por veículo.
   Faça essa pausa logo após o aviso, antes que o novo veículo saia do trecho
   ou que o evento recrie seu tráfego. Se estiver na tela de apresentação
   **Continue**, é preciso iniciar o evento para a rotina de tráfego executar.
6. Aguarde a confirmação no editor. Depois use **Retomar** para jogar e
   testar presença, movimento e colisão. As distâncias são unidades do jogo,
   sem equivalência estabelecida em metros.

Confira também **Jogo pausado** no editor e `<PAUSED>` no título da janela
do jogo. Se houver duas instalações abertas, pausar a outra janela do PCSX2
não pausa a sessão à qual o editor está conectado.

A faixa amarela **CRIAÇÃO PENDENTE** permanece até a finalização. O aviso de
que o veículo foi criado ainda exige a segunda pausa, antes de dirigir.
Se o veículo já mudou ou saiu do cenário, o editor pode encerrar com
**Atenção: ... Código temporário removido. Alinhamento não confirmado.**
Nesse caso ele limpa somente sua rotina temporária, libera a interface e
não inclui essa criação na receita JSON. Ele não move outro veículo para
tentar corrigir uma referência antiga.

Se todas as criações já retornaram, mas a física ainda não permite confirmar
o alinhamento, a espera fica limitada a cinco segundos a partir da primeira
verificação pausada dessa etapa. Depois, o editor remove apenas o código
temporário reconhecido, conserva os veículos que o jogo criou e cancela a fila
restante. O lote não entra na receita. **Finalizar pendência** permite encerrar
essa espera imediatamente, desde que a rotina já tenha devolvido o controle ao
jogo. Código ativo, desconhecido ou sem prova de conclusão continua bloqueado.

Durante uma criação em andamento, não carregue outro estado, troque de evento
ou feche o editor. A mensagem da interface indica a etapa necessária. Se uma
operação falhar, siga a mensagem exibida. Se for pedido um estado limpo, recarregue
a referência anterior, pause o emulador e clique em **Conectar / nova sessão**.
A criação anterior não é repetida automaticamente. Repetir uma ação sem saber
seu resultado pode acrescentar outra instância.

## Modo experimental e pedidos maiores

1. Preserve um estado de controle antes de testar. Ative **Modo experimental:
   ampliar quantidade e distância** e leia o aviso persistente de alto risco de
   travamento, congelamento e perda de física.
2. Informe uma distância positiva e finita. O teto de 50 e os mínimos de 8/30
   deixam de ser restrições do editor nesse modo; o fim do caminho continua
   sendo respeitado. Distâncias pequenas podem sobrepor veículos.
3. A quantidade aceita pedidos de até 253, mas o pedido precisa caber nos
   objetos, nós e registros de colisão disponíveis. Não são 253 carros
   garantidos; um conjunto cabine/carga consome dois objetos.
4. Pedidos maiores usam uma fila em grupos de até oito. Faça **Retomar →
   Pausar PCSX2** e aguarde a confirmação de cada grupo. O rodapé informa o
   próximo grupo e a fila restante. Não repita o clique de criação.
5. **Cancelar fila** descarta as operações restantes. Ele não remove veículos
   já criados nem desfaz o grupo que já foi preparado; finalize esse grupo
   conforme a mensagem antes de voltar a editar.

O aviso permanece visível enquanto o modo estiver ativo. O editor mostra
contagens de objetos ativos, física pronta, objetos/nós livres e fila; pode
avisar quando objetos de uma referência deixam de ter física inicializada.
Esses dados não estabelecem uma capacidade segura de impacto. Se um objeto
perder física, não trate a quantidade livre no pool como prova de que ele
continuará funcionando; restaure a referência de controle para comparar.

Este modo não corrige o assert VIF relatado e não amplia estruturas do motor.
O erro e a observação de falhas após mais de cinquenta carros estão descritos em
[muitos veículos e testes experimentais](high-density-experiments.md). O relato
não demonstra um limite universal de cinquenta.

## Criar no ponto marcado

1. Pause o PCSX2, atualize a lista e selecione uma referência com caminho e
   física válidos. Escolha o modelo carregado e, se for caminhão, a carga compatível.
2. Abra **Vista de cima**. Clique em **Marcar posição** e depois no mapa; o alvo
   aparece com X/Z. Também é possível digitar X e Z diretamente nos campos.
3. Clique em **Adicionar no ponto**. Essa ação prepara um veículo ou conjunto,
   usando o modelo escolhido no painel lateral; a quantidade do lote atrás
   não multiplica a criação no ponto.
4. Siga **Retomar → Pausar PCSX2**, aguarde a finalização e só então retome para
   observar presença, movimento e colisão.

O ponto X/Z é projetado de forma aproximada no melhor caminho entre aqueles
que têm referências prontas na sessão. No modo normal a posição é ajustada à
largura admitida da via, e pontos muito distantes são recusados. O modo
experimental admite lateral fora dessa largura, com risco maior de física
inválida; ele ainda precisa de um caminho reconhecido.

Não há seleção de altura Y ou busca de terreno. O mapa desenha caminhos de
tráfego pesquisados, sem malha de asfalto e sem carregar locais ausentes,
por isso o resultado pode diferir do clique.
Essa criação não teleporta um veículo existente. Quando um objeto fora da via
ainda tiver física e layout admitidos, o modo experimental pode liberar
**Aplicar posição** para tentar retorná-lo à largura de 0% a 100%. Ele continua
sem servir de referência para novas criações enquanto estiver fora do perfil normal.

## Finalizar uma pendência antiga

1. Pause o PCSX2 e confira **Jogo pausado**.
2. Clique em **Finalizar pendência**, mesmo se a lista estiver bloqueada ou vazia.
3. Leia o resultado no rodapé. Se a solicitação for reconhecida e já tiver
   devolvido o controle ao jogo, o editor limpa somente a área temporária admitida.
4. Clique em **Atualizar lista**. Se o perfil continuar inválido, restaure uma
   referência limpa pelo PCSX2 antes de editar.

Um estado feito antes da limpeza pode restaurar a rotina temporária antiga.
Para recuperar uma solicitação antiga sem acompanhamento na sessão atual,
o editor exige o registro local correspondente e o payload
canônico de um formato reconhecido, com prova de conclusão. Código desconhecido
ou sem prova continua bloqueado. A ação não alinha veículos nem recupera a
receita daquela solicitação. A recuperação de solicitações antigas é explícita;
o auto-poll não repete o comando de criação nem faz essa limpeza por conta própria.

## Guardar a configuração

**Salvar configuração** gera um JSON local com os dados usados pelo editor.
**Abrir configuração** aplica a configuração admitida pelo perfil ao evento
atual. Ela exige **exatamente o mesmo estado inicial**, anterior às edições,
usado para preparar a receita. Recarregue essa referência e pause o emulador,
inicie uma nova sessão no editor e abra o JSON. Uma receita que cria veículos
exige as mesmas etapas de retomar e pausar descritas acima.

Se a receita contiver ações experimentais, ative o toggle e leia o aviso antes
de abri-la. Com o modo desligado, o controlador recusa essas ações; um JSON
não pode ativar o risco por conta própria. A receita ainda exige os mesmos
modelos carregados, referências válidas e estado inicial.

Veículos que aparecerem depois da referência inicial, sem criação confirmada
na receita, podem ser editados quando o perfil os admitir. Se alguma ação usar
essa referência observada, o editor recusa salvar o JSON para não prometer um
replay que não consegue reconstruir. Use um `.p2s` para conservar a sessão,
ou **Conectar / nova sessão** para adotar o cenário atual como nova referência.

**Salvar estado…** exporta um arquivo `.p2s` da sessão editada, com o emulador
pausado e nenhuma criação pendente. Escolha um nome novo. O botão só aparece
quando a instalação portátil pode ser identificada. A implementação usa um slot
livre, verifica o arquivo gerado e recusa substituir estados e destinos existentes.
O diálogo sugere `outputs/events/` na pasta do projeto e um nome com data/hora,
sem colisão com arquivos locais. O rodapé mostra **Arquivo:** com o caminho
retornado após exportar.
**O usuário confirmou a exportação real; o arquivo exportado ainda não foi
restaurado em teste.** Na sessão atual, os dez slots estão ocupados: o botão
recusa a exportação para preservar esses arquivos. Nesse caso, salve pelo próprio
PCSX2 em **Sistema → Salvar estado → Arquivo…**, escolhendo um destino **novo**
com extensão `.p2s`, por exemplo dentro de `outputs/events/`. Uma cópia de
controle salva por essa rota manual passou na verificação de ZIP e memória EE.
Isso não é um teste do botão de exportação nessa sessão com todos os slots cheios.

Para reabrir:

1. Deixe o jogo correspondente aberto no PCSX2.
2. Na janela principal do PCSX2, escolha **Sistema → Carregar estado → Arquivo…**.
3. Selecione o `.p2s` onde foi salvo e clique em **Abrir**. Isso restaura o instante salvo.
4. Pause o emulador e conecte o editor como nova sessão antes de editar.

O editor não carrega esse arquivo automaticamente. Se ele trouxer uma pendência
antiga, siga a seção **Finalizar uma pendência antiga** acima.

O JSON não contém os recursos do jogo e não substitui um save state. A edição
vale para os dados da sessão atual: **Restart** do jogo, troca de evento ou
carregamento de outro estado podem recriar o tráfego e descartar a alteração.
O `.p2s` preserva uma sessão para restaurar; ele não grava um novo evento no ISO
nem transforma um **Restart** em execução persistente do layout. Preserve estados
de teste separadamente. Ainda não há gravação persistente
dos arquivos de Crash Events, criação de mapas ou editor dentro do jogo.

O protocolo e a pausa exigida foram conferidos no
[PINE oficial do PCSX2 v1.7.2521](https://github.com/PCSX2/pcsx2/blob/v1.7.2521/pcsx2/PINE.cpp).
As mensagens de sucesso da interface não substituem a observação no jogo.

Após a confirmação anterior de lote e exportação, o usuário também relatou que
as novas mudanças da revisão com caminhos e velocidade funcionaram. Em seguida,
confirmou também o funcionamento da correção da espera pela física e da seleção
múltipla de velocidade. A restauração do `.p2s` exportado ainda precisa ser
confirmada. Bloqueios de perfil ainda podem impedir uma operação; os relatos
não demonstram estabilidade de todos os cenários.

O fluxo de lotes, caminhões, pausa e arquivos está em
[batches-trucks-and-pause.md](batches-trucks-and-pause.md). As restrições,
o erro de proteção e a investigação de caminhões estão em
[traffic-capacity-and-trucks.md](traffic-capacity-and-trucks.md).
