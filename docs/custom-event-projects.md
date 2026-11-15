# Projetos de eventos de Crash — versão 1

A aba **Projeto** organiza um evento personalizado em um mapa existente:
nome, referência original e cena editada com veículos, posições e velocidades.
O projeto usa estados locais do PCSX2 para repetir a mesma cena. O perfil
aceito continua sendo Burnout 3 USA, `SLUS-21050 / BEBF8793`, no PCSX2
`1.7.2521` portátil com PINE.

O usuário confirmou o funcionamento dos lotes e da velocidade em grupo na
revisão anterior. O fluxo de projetos e restauração desta versão foi verificado
offline; sua restauração e repetição em jogo ainda precisam de confirmação.

## Criar e testar

1. Carregue o evento, conecte o editor e use **Pausar PCSX2**. Escolha um instante
   anterior à batida para poder repetir o teste a partir dele. Finalize qualquer
   criação pendente.
2. Na aba **Projeto**, informe um nome com até 100 caracteres e clique em
   **Criar projeto…**. Escolha a pasta que receberá uma nova subpasta do projeto.
   A cena pausada é copiada como referência original; arquivos existentes não
   são substituídos.
3. Organize os veículos e suas velocidades pelos controles do editor. Finalize
   os lotes antes de salvar. **Salvar cena no projeto** guarda essa versão e
   mantém o emulador pausado.
4. **Testar cena** salva uma nova versão e retoma o jogo. Dirija e teste a batida.
5. Para repetir, pause novamente e clique em **Voltar ao início**. Aguarde a
   confirmação de restauração antes de editar ou retomar o jogo.

**Voltar ao início** restaura a última **cena editada salva**, incluindo o
instante em que o jogador estava ao salvá-la. Ele não usa o reinício normal do
menu do jogo e não volta automaticamente à referência sem alterações.
Se o PCSX2 não retomar após **Testar cena**, a mensagem distingue a cena já
salva da falha de retomada; confira a pausa antes de continuar.

## Reabrir e recuperar a referência

Com o jogo correspondente carregado e o emulador pausado, use **Abrir projeto…**
e selecione `event.b3event.json`. O editor verifica os arquivos e restaura a
última cena salva. Uma nova sessão de edição é iniciada a partir dela; a receita
JSON de ações da sessão anterior não é reconstruída.

**Restaurar base original** carrega a referência capturada quando o projeto
foi criado. A cena editada salva é preservada: **Voltar ao início** ainda pode
recuperá-la, até que uma nova cena seja salva. As restaurações permanecem
pausadas ao terminar, prontas para conferência e edição.

## Quando não há slot livre

A captura e a restauração automáticas usam um slot temporário que esteja livre.
O editor recusa substituir qualquer um dos dez slots existentes. A área
**Alternativa sem slot livre**, na aba Projeto, permite usar o menu do PCSX2:

1. Para criar uma referência ou guardar uma cena, mantenha o instante desejado
   pausado e use **Sistema → Salvar estado → Arquivo…** no PCSX2, escolhendo um
   arquivo `.p2s` novo.
2. Use **Criar de .p2s…** para um projeto novo, ou **Salvar cena de .p2s…** para
   atualizar o projeto aberto. O arquivo precisa corresponder à cena pausada;
   o editor confere antes de copiá-lo e preserva o original.
3. Para repetir manualmente, use **Sistema → Carregar estado → Arquivo…** e
   escolha o arquivo da cena do projeto. Depois pause o PCSX2 e use **Conferir
   cena carregada…**, selecionando o manifesto desse projeto.
4. Para recuperar a referência, carregue `base.p2s` pelo mesmo menu e use
   **Conferir base carregada…**.

Os botões **Conferir** verificam o que já foi carregado; eles não enviam um
comando de carregamento. Para testar uma cena salva por essa alternativa,
use **Retomar**. **Testar cena** usa a captura automática e continua exigindo
um slot livre.

## Arquivos e preservação

Uma pasta de projeto contém:

```text
evento-…/
  event.b3event.json
  base.p2s
  scene-<identificador>.p2s
```

Logo após a criação, a cena salva aponta para `base.p2s`, sem duplicá-lo.
Cada gravação posterior cria um novo arquivo `scene-…p2s` e só então atualiza o
manifesto. A base e as cenas anteriores não são sobrescritas. A interface usa a
versão atual indicada no manifesto; ainda não há navegador de versões antigas.

O manifesto guarda nome, perfil, resumo e referências relativas aos estados,
com hashes de integridade. Arquivos externos, referências com travessia de
pastas, links e redirecionamentos não são admitidos. Se o manifesto mudar em
outra sessão, abra-o novamente antes de salvar. Uma falha de cópia ou publicação
preserva os arquivos existentes; uma captura ou versão sem referência pode
ficar no disco para conferência.

Os projetos são locais e podem ficar em `outputs/events/`. Estados `.p2s`
contêm dados do jogo e não são enviados ao repositório. Mantenha a pasta inteira
para reabrir o projeto. O projeto não exige que todos os veículos da cena tenham
uma criação registrada na receita JSON de ações; ele restaura o estado salvo.

## Conferência da restauração

O reconhecimento de um ZIP válido e dos códigos compatíveis é feito antes do
pedido automático de carregamento. A confirmação de recebimento desse pedido
pelo PCSX2 não é tratada como conclusão. O editor publica um marcador aleatório
de 16 bytes em sua área de dados ociosa e exige que a restauração o remova,
inclusive se a cena de destino já estava carregada. Depois confere pausa,
identidade, código temporário limpo e regiões de memória da cena em duas leituras.
O controlador valida novamente o perfil antes de liberar a edição.
Os dados conferidos incluem tráfego, descritores de caminhos e transformação
do jogador quando seu ponteiro é válido. Essa prova não compara integralmente
todo o estado do PS2. O hash do arquivo é vinculado à referência do projeto
antes de copiar ou carregar, para recusar uma substituição entre a conferência
e o uso.

Se o carregamento ficar ambíguo, não há repetição automática nem tentativa de
reverter memória: novas edições ficam bloqueadas até recuperar uma referência
limpa. Essa conferência não é uma prova de estabilidade da física, da colisão
ou do render em cenas densas.

## Limites desta versão

Criar veículos ainda depende de modelos carregados, caminhos admitidos e
referências válidas. Um caminho candidato desenhado no mapa não fica
automaticamente disponível para criação. O **Restart** normal do jogo pode
reconstruir o tráfego original; para repetir o trabalho salvo, use o projeto.

O projeto preserva cenas externas ao jogo. Ele não grava eventos nos arquivos
do ISO, não acrescenta opções ao menu de Crash, não carrega modelos ausentes e
não cria geometria de mapa. Usar novos locais exige pesquisar caminhos,
colisão, câmera e regras da área. Identificar os dados nativos de eventos e
seus fluxos de tráfego, pontuação e encerramento continua sendo uma etapa
posterior.
