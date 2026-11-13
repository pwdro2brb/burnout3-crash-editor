# Editor do evento atual — primeiro uso

Esta interface externa edita o evento que está carregado no PCSX2. A primeira
versão permite identificar os veículos presentes, deslocar um veículo na
largura da via e acrescentar lotes de 1 a 8 atrás de uma referência. Caminhões
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
carregados e admitidos pelo perfil. Há tipos independentes 1/2 e conjuntos
nativos de cabine tipo 4 com carga tipo 11. Ao escolher uma cabine, a interface
mostra **Carga do caminhão** e somente combinações observadas e carregadas.
A carga não é oferecida como veículo avulso. Ônibus e combinações sem validação
continuam fora da criação.

A aba **Catálogo carregado** mostra todos os modelos encontrados, sua categoria
e o estado da criação: **Disponível**, **Disponível com caminhão** ou
**Criação não validada**. Assim é possível
identificar um ônibus carregado mesmo quando ele não aparece na escolha de criação.

Na aba **Vista de cima**, os pontos representam as posições X/Z da última leitura.
Não há desenho da pista. Clique em um ponto para selecionar o veículo; use a roda
do mouse para aproximar e **Enquadrar** para ver todos novamente. O jogador aparece
em vermelho com uma seta de direção quando essa referência está disponível.
Essa vista é atualizada com a lista, sem acompanhar o jogo em tempo real.

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

1. Com o emulador pausado, selecione o veículo de referência.
2. Escolha o modelo, **Quantidade** de 1 a 8 e **Distância atrás**. Para os
   independentes, o valor inicial é 10 e o intervalo é de 8 a 50 unidades do jogo.
3. Para uma cabine, escolha também a carga compatível. **Conjuntos** conta
   pares completos, não componentes. A carga nativa do alvo só é preselecionada
   quando seu vínculo foi validado. Para caminhão ou referência composta,
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

Durante uma criação em andamento, não carregue outro estado, troque de evento
ou feche o editor. A mensagem da interface indica a etapa necessária. Se uma
operação falhar, siga a mensagem exibida. Se for pedido um estado limpo, recarregue
a referência anterior, pause o emulador e clique em **Conectar / nova sessão**.
A criação anterior não é repetida automaticamente. Repetir uma ação sem saber
seu resultado pode acrescentar outra instância.

## Guardar a configuração

**Salvar configuração** gera um JSON local com os dados usados pelo editor.
**Abrir configuração** aplica a configuração admitida pelo perfil ao evento
atual. Ela exige **exatamente o mesmo estado inicial**, anterior às edições,
usado para preparar a receita. Recarregue essa referência e pause o emulador,
inicie uma nova sessão no editor e abra o JSON. Uma receita que cria veículos
exige as mesmas etapas de retomar e pausar descritas acima.

**Salvar estado…** exporta um arquivo `.p2s` da sessão editada, com o emulador
pausado e nenhuma criação pendente. Escolha um nome novo. O botão só aparece
quando a instalação portátil pode ser identificada. A implementação usa um slot
livre, verifica o arquivo gerado e recusa substituir estados e destinos existentes.
**O usuário confirmou a exportação real; o arquivo exportado ainda não foi
restaurado em teste.** Para
reabrir, carregue o jogo correspondente e use a opção do PCSX2 de carregar um
estado a partir de arquivo. O editor não carrega esse arquivo automaticamente.

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

Após reabrir a revisão com a saída protegida do lote, o usuário confirmou que
lote e exportação funcionaram. A validação automatizada passou em 122 testes
distribuíveis e 35 privados (19 do controlador e 16 do perfil). Bloqueios de
perfil ainda podem impedir uma operação; o relato não valida todos os cenários.

O fluxo de lotes, caminhões, pausa e arquivos está em
[batches-trucks-and-pause.md](batches-trucks-and-pause.md). As restrições,
o erro de proteção e a investigação de caminhões estão em
[traffic-capacity-and-trucks.md](traffic-capacity-and-trucks.md).
