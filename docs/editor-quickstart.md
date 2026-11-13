# Editor do evento atual — primeiro uso

Esta interface externa edita o evento que está carregado no PCSX2. A primeira
versão permite identificar os veículos presentes, deslocar um veículo na
largura da via e acrescentar um veículo atrás dele. Ela usa os caminhos e os
modelos que o jogo já carregou.

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
3. Na janela do jogo, pressione **Esc** para pausar o emulador. **Start**, no
   menu de pausa do jogo, não substitui essa pausa.
4. Abra **Abrir Editor.cmd** na pasta do projeto e clique em **Conectar / nova sessão**.
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

## Identificar e escolher o modelo

O identificador do carro usado no primeiro ensaio foi **COMPCAR14**. A tabela
de rótulos do próprio jogo o classifica como **Car**. O catálogo também distingue
categorias como Van, Bus, táxi e carretas; isso não identifica um fabricante
ou um modelo real de automóvel.

A lista de criação oferece **Mesmo modelo do selecionado** e os modelos
carregados e admitidos pelo perfil inicial. Nesta versão, a criação é limitada
aos tipos independentes de carro e van observados nas referências. Um ônibus
ou uma carreta pode estar identificado no catálogo sem estar liberado para
criação. Essa restrição evita tratar um componente articulado como carro avulso.

A aba **Catálogo carregado** mostra todos os modelos encontrados, sua categoria
e o estado da criação: **Disponível** ou **Criação não validada**. Assim é possível
identificar um ônibus carregado mesmo quando ele não aparece na escolha de criação.

Na aba **Vista de cima**, os pontos representam as posições X/Z da última leitura.
Não há desenho da pista. Clique em um ponto para selecionar o veículo; use a roda
do mouse para aproximar e **Enquadrar** para ver todos novamente. O jogador aparece
em vermelho com uma seta de direção quando essa referência está disponível.
Essa vista é atualizada com a lista, sem acompanhar o jogo em tempo real.

## Mover um veículo

1. Pause o emulador com **Esc** e atualize a lista.
2. Selecione um veículo disponível para edição.
3. Ajuste **Posição na largura da via** e clique em **Aplicar posição**.
4. Volte à janela do jogo e pressione **Esc** para continuar e observar.

O controle de 0% a 100% percorre a largura do caminho. Ele não corresponde
necessariamente a uma faixa de trânsito ou a uma borda de colisão da pista.
A posição longitudinal é mantida. Comece com alterações pequenas; alguns
objetos distantes ainda não têm seus pontos físicos atualizados e não podem
ser editados por este método.

## Adicionar um veículo atrás

1. Com o emulador pausado por **Esc**, selecione o veículo de referência.
2. Escolha o modelo e informe **Distância atrás**. O valor inicial é 10,
   com intervalo permitido de 8 a 50 unidades do jogo; não são metros estabelecidos.
3. Clique em **Adicionar atrás** e siga a mensagem de status do editor.
4. Volte ao PCSX2 e pressione **Esc** para retomar. A rotina do jogo criará
   a instância na atualização seguinte.
5. Quando o editor solicitar, pressione **Esc** novamente no PCSX2. O editor
   acompanha a operação e finaliza o registro e o alinhamento nessa pausa.
   Faça essa pausa logo após o aviso, antes que o novo veículo saia do trecho
   ou que o evento recrie seu tráfego. Se estiver na tela de apresentação
   **Continue**, é preciso iniciar o evento para a rotina de tráfego executar.
6. Aguarde a confirmação no editor. Depois pressione **Esc** para jogar e
   testar a presença e a colisão do carro novo.

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
a referência anterior, pause com **Esc** e clique em **Conectar / nova sessão**.
A criação anterior não é repetida automaticamente. Repetir uma ação sem saber
seu resultado pode acrescentar outra instância.

## Guardar a configuração

**Salvar configuração** gera um JSON local com os dados usados pelo editor.
**Abrir configuração** aplica a configuração admitida pelo perfil ao evento
atual. Ela exige **exatamente o mesmo estado inicial**, anterior às edições,
usado para preparar a receita. Recarregue essa referência, pause com **Esc**,
inicie uma nova sessão no editor e abra o JSON. Uma receita que cria veículos
exige as mesmas etapas de retomar e pausar descritas acima.

O JSON não contém os recursos do jogo e não substitui um save state. A edição
vale para os dados da sessão atual: **Restart** do jogo, troca de evento ou
carregamento de outro estado podem recriar o tráfego e descartar a alteração.
Preserve estados de teste separadamente. Ainda não há gravação persistente
dos arquivos de Crash Events, criação de mapas ou editor dentro do jogo.

O protocolo e a pausa exigida foram conferidos no
[PINE oficial do PCSX2 v1.7.2521](https://github.com/PCSX2/pcsx2/blob/v1.7.2521/pcsx2/PINE.cpp).
As mensagens de sucesso da interface não substituem a observação no jogo.

As restrições, o erro de proteção e a investigação de caminhões estão em
[traffic-capacity-and-trucks.md](traffic-capacity-and-trucks.md).
