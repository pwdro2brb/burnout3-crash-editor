# Lotes, caminhões, pausa e preservação

Estado de 13/11/2026, para Burnout 3 USA `SLUS-21050` / CRC `BEBF8793` no
PCSX2 1.7.2521. A ferramenta continua externa e usa os modelos e caminhos
que o evento já carregou.

## Resultados observados e limites

O usuário confirmou explicitamente o funcionamento de **ambos** os testes:
lote de carros e caminhão com carga. O registro local inclui `batch_finished`
para oito `COMPCAR14` e para um conjunto `HEVYCAR22` + `HEVYCAR27`.
Essas são evidências de ensaios específicos, sem captura instrumentada do impacto
ou demonstração de estabilidade prolongada em todos os eventos.

Também houve três registros posteriores `batch_not_finalized`: a instância ou
identidade já não correspondia à solicitação no momento de finalizar. Presença
no cenário, colisão relatada e finalização técnica são verificações distintas.
O editor não deve alinhar outro objeto para substituir silenciosamente uma
referência que expirou.

## Revisão técnica da finalização

Na revisão com saída protegida, o último stub do lote restaura o hook original antes
de sair. A conclusão global só é publicada numa **landing fixa de doze bytes**,
e a limpeza preserva exatamente essa landing. Assim, se o EE estiver pausado
nessa saída, a retomada ainda encontra o salto de retorno e seu delay slot;
o editor não apaga o código em que ele pode continuar executando.

A finalização exige os probes das solicitações e o marcador global de conclusão.
No formato v2, esse marcador deve conter o token da geração atual, ligado ao
nonce e conferido contra o histórico conhecido. Uma conclusão de outro lote
não satisfaz a solicitação atual. O formato v1 com landing é reconhecido
somente para recuperar uma solicitação antiga já encerrada.
Os demais bytes temporários são limpos para a baseline canônica com essa pequena
saída preservada. As verificações dessa sequência incluem pausa após a publicação,
limpeza e retomada num intérprete de teste.

Na rodada anterior, após reabrir o editor com a saída protegida, o usuário confirmou: **“Lote e
exportação funcionaram”**. A rodada confirmou manualmente o novo fluxo e a
exportação real. **O arquivo exportado ainda não foi restaurado em teste.**

O registro local posterior inclui oito vans `HEVYCAR33` finalizadas no caminho
53 e dois pares `HEVYCAR22` + `HEVYCAR27` em cada um dos caminhos 34 e 53.
Também houve uma recusa posterior de perfil porque as estruturas de tráfego
não passaram na verificação, mantendo uma criação pendente. Esse registro não
estabelece travamento ou falha geral; as verificações de perfil continuam
podendo bloquear operações.

Passaram **157 testes distribuíveis** e **40 privados**: 19 do controlador e
21 do perfil. Os testes e relatos cobrem esses casos e não demonstram estabilidade universal.

O movimento lateral de conjuntos é candidato e precisa de teste próprio após
o deslocamento. A restauração do `.p2s` exportado ainda não foi testada.
**O quarto caminhão-tanque, suas colisões e explosões
continuam sem validação.**

## Pausar e retomar sem depender de Esc

Depois de conectar, os botões **Pausar PCSX2** e **Retomar** aparecem quando
o editor identifica o processo da própria conexão PINE e o menu compatível
do PCSX2 Windows. O resultado é confirmado pelo estado PINE. Isso não introduz
um comando de pausa no protocolo PINE; o botão usa o menu nativo do emulador.
Uma solicitação sem confirmação não é repetida automaticamente.

O frame principal pode ficar oculto enquanto a janela GS está aberta. Essa
ocultação não transforma a janela GS em outro alvo: a identificação permanece
vinculada ao processo da conexão. Se o botão não estiver disponível, use
**Sistema → Pausar** no emulador correto e confira **Jogo pausado** no editor.
A pausa do menu do jogo com **Start** não é suficiente.

Na instalação pesquisada, foi desmarcada a opção **Ocultar a janela quando
estiver em pausa**, correspondente a `CloseOnEsc=disabled` em `PCSX2_ui.ini`.
Isso mantém a janela do jogo visível ao pausar; o nome da chave não significa
que Esc seja a única forma de pausa. A preferência foi alterada pela interface
do PCSX2 e não é modificada automaticamente pelo editor. Faça o ajuste somente
na instalação que pretende usar para os testes.

## Um ciclo para o lote inteiro

1. Pause o PCSX2 e atualize a lista.
2. Selecione a referência, o modelo e a quantidade de **1 a 8**.
3. Informe a distância entre as criações. Independentes 1/2/3 usam **8 a 50** unidades;
   ônibus tipo 5, caminhão ou referência desses tipos usa **30 a 50**. Esses valores não são metros estabelecidos.
4. Prepare o lote e clique em **Retomar** uma vez.
5. Quando o editor solicitar, clique em **Pausar PCSX2** para finalizar todas
   as criações. Aguarde a confirmação antes de dirigir.

A quantidade não exige uma sequência manual de retomar/pausar por veículo.
Enquanto houver criação pendente, o banner amarelo permanece e novas edições
ficam bloqueadas. Na apresentação **Continue**, o evento precisa começar para
o jogo executar a atualização do tráfego.

O limite de oito é o limite desta operação do editor, não uma capacidade total
do motor. Espaço atrás da referência, objetos, nós e colisões continuam sendo
recursos compartilhados. Um lote pode ser recusado mesmo com objetos livres
se não houver trecho ou combinação compatível.

## Cabine e carga

O criador usa **primário tipo 4 + secundário tipo 11**, com IDs de modelos
separados. A interface oferece somente pares nativos observados com os dois
recursos carregados. Ao escolher uma cabine, aparece **Carga do caminhão**;
a carga fica fora da lista principal de criação. Se o alvo já for um conjunto
validado, seu modelo de carga nativo pode ser preselecionado. Nos demais casos,
a escolha é explícita.

**Conjuntos = 3** solicita três cabines com suas três cargas, não três objetos
isolados. Cada par usa dois objetos e seus registros físicos, mas um nó de
caminho. A presença de vários tanques no desenho original não estabelece um
limite geral de três; a pesquisa não encontrou esse limite nas rotinas examinadas.
Os efeitos de dano e explosão exigem ensaios separados.

O reposicionamento composto prepara **onze floats protegidos**: X/Z dos pontos
e da translação da cabine, X/Z do ponto traseiro e da translação da carga, mais
a fração lateral do nó. Preserva o vínculo, as coordenadas Y e o primeiro ponto
nulo da carga tipo 11. Esse método só é oferecido quando o layout admitido é
reconhecido; a sua implementação não comprova estabilidade física após mover.

## Vans de tipo 3 e ônibus de tipo 5

O perfil admite associações nativas consistentes de `HEVYCAR17/18` a tipo 3
e de `HEVYCAR19/21` a tipo 5. Esses independentes passam pelos mesmos guardas
de dois pontos físicos inicializados e não degenerados, render e collider
coerentes, caminho válido e listas/ocupação admitidas. A referência também
precisa de movimento de seguimento válido.

`HEVYCAR20` apenas carregado continua bloqueado sem uma associação ativa
consistente ao tipo 5. O nome **Bus** no catálogo não autoriza uma instância
sem essa evidência. Tipos especiais 6 a 10 continuam fora do editor.
**O teste real de criação de ônibus ainda está pendente.** Vans de tipo 3
mantêm o intervalo de 8 a 50 unidades; ônibus escolhido ou usado como
referência exige 30 a 50.

Uma solicitação de ônibus tipo 5 em formato v2 foi preparada nesta fase e
aguardava a retomada do tráfego pelo usuário. Preparação não demonstra criação
finalizada, movimento ou colisão no emulador real.

## Finalizar uma solicitação restaurada

Salvar e depois recarregar um estado anterior à limpeza pode recolocar uma
rotina temporária antiga na memória. Esse foi o diagnóstico da pendência
investigada nesta fase. A recuperação real alterou somente a área temporária
de 4 KiB; as regiões classificadas de objetos, nós e matrizes ficaram idênticas
byte a byte. Nenhum veículo foi reposicionado.

Com o jogo pausado, **Finalizar pendência** compara a solicitação com o registro
local e sua construção canônica. Só limpa solicitações v1/v2 baseadas na landing
que já devolveram o controle ao jogo, com hook original, probes concluídos e
marcador de conclusão correspondente. Código desconhecido, registro ausente ou execução incompleta
continuam bloqueados. A limpeza preserva os veículos existentes; o alinhamento
e a receita da solicitação antiga não são recuperados.

Essa recuperação exige o clique explícito. O auto-poll não repete a criação
nem limpa uma solicitação antiga restaurada. A GUI mantém a conexão se a
identidade foi confirmada e apenas o perfil falhou, deixando **Finalizar
pendência** acessível mesmo sem seleção. Depois de uma limpeza bem-sucedida,
uma falha na leitura mantém o aviso e desabilita a lista e mutações até
**Atualizar lista** retornar dados válidos.

## Tráfego na contramão

O controlador não bloqueia pelo sentido relativo ao jogador. A referência
precisa de caminho válido, vínculo admitido e física inicializada, com valores
coerentes de orientação, velocidade de seguimento e progressão. Nas leituras
que motivaram a investigação, os carros da contramão ainda tinham pontos físicos
zerados e velocidade de seguimento zero. Isso explica aqueles bloqueios sem
classificar toda a contramão como incompatível. Selecione o objeto para consultar
o motivo de bloqueio; não trate posição finita, por si só, como física pronta.

## Receita JSON e estado `.p2s`

| Arquivo | O que conserva | Como reutilizar |
| --- | --- | --- |
| JSON de **Salvar configuração** | Receita de ações e referência inicial | Recarregar exatamente o estado inicial, conectar e abrir a receita |
| `.p2s` de **Salvar estado…** | Captura da sessão editada do emulador | Carregar o jogo correspondente e restaurar o arquivo pelo PCSX2 |

A exportação de estado exige pausa confirmada e nenhuma criação pendente.
O destino sugerido é `outputs/events/` na pasta do projeto, com nome único
de data/hora. Após concluir, o rodapé mostra **Arquivo:** e o caminho retornado.
Escolha um destino novo: a implementação recusa substituir arquivos existentes,
procura um slot livre da instalação portátil e verifica o arquivo antes de
copiá-lo. O reconhecimento de uma solicitação PINE de salvar não é tratado
como conclusão imediata. O usuário confirmou a exportação real; restaurar esse
arquivo ainda precisa de validação manual.
O editor não restaura o `.p2s` automaticamente.

Se os dez slots estiverem ocupados, a exportação pelo botão é recusada antes
de substituir qualquer estado. Essa foi a situação da sessão atual. Use o
menu do PCSX2 **Sistema → Salvar estado → Arquivo…** e escolha um destino
**novo** com extensão `.p2s`. Uma cópia de controle salva por essa rota manual
foi validada como ZIP com memória EE de 32 MiB. Isso não comprova o botão PINE
de exportação numa sessão com todos os slots ocupados.

Para restaurar no PCSX2 wx 1.7.2521: com o jogo correspondente aberto, use
**Sistema → Carregar estado → Arquivo…**, selecione o `.p2s` onde foi salvo e
clique em **Abrir**. O jogo volta ao instante salvo. Pause e conecte o editor
como nova sessão antes de editar; se o arquivo trouxer uma pendência antiga,
use o procedimento explícito acima.

O item de arquivo e o diálogo `.p2s` estão no
[código oficial do PCSX2 wx 1.7.2521](https://github.com/PCSX2/pcsx2/blob/v1.7.2521/pcsx2/gui/MainMenuClicks.cpp#L792).

Nenhum desses formatos grava o layout em recursos do ISO ou em um novo
Crash Event persistente. **Restart**, troca de evento ou outro estado podem
recriar o tráfego. O estado salvo é uma forma de restaurar uma sessão; não é
equivalente a modificar o evento original do jogo.

O [guia de primeiro uso](editor-quickstart.md) cobre a sequência básica, e
[traffic-capacity-and-trucks.md](traffic-capacity-and-trucks.md) registra a
investigação de capacidade, pares e tanques.
