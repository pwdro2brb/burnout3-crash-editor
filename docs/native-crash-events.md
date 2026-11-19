# Editar um evento nos arquivos do jogo

Abra **Abrir Editor.cmd → Projeto → Eventos nativos…**. A janela funciona
com o PCSX2 fechado. Escolha **Abrir pasta do jogo…** e indique a pasta
extraída de Burnout 3 USA que contém `DATA` e `TRACKS`. Se a extração
estiver ao lado do editor com o nome padrão, a janela abre o catálogo automaticamente.

## Preparar uma edição

1. Busque o evento pelo nome, pela pista ou pela chave. **Localizar evento da
   sessão** seleciona o último evento identificado pela atualização da lista
   com o PCSX2 pausado.
2. Em **Tráfego e metas**, segure **Ctrl** e selecione dois modelos do mesmo
   grupo. Clique em **Trocar dois modelos do mesmo grupo**. O evento mantém
   todos os modelos que já carregava. Essa operação edita a lista do evento.
   A posição e a ordem em que os veículos aparecem na rodada ainda estão em pesquisa.
3. Ajuste os valores em dólares para ouro, prata e bronze. Use números
   inteiros em ordem decrescente. **Batidas para o Crashbreaker** define quantos
   veículos precisam bater para liberar a explosão. O editor aceita de 6 a 15,
   a faixa encontrada nos eventos originais. As metas ficam somente para
   leitura nos dois eventos em que as tabelas do próprio jogo divergem.
4. **Caminhos da pista** mostra as linhas centrais das vias em uma vista de
   cima. A mesma pista pode abrigar vários eventos. O desenho abrange a pista
   inteira e pode incluir vias distantes do cruzamento.
5. **Gerar cópia ISO…** pede a imagem correspondente à extração e um nome novo
   para a saída. Reserve espaço para uma segunda ISO inteira. Para trabalhar
   somente com os recursos, use **Exportar arquivos…** e escolha uma pasta de
   destino. O editor cria uma subpasta exclusiva com os arquivos alterados.
   Cada exportação inclui as edições do evento selecionado.

## Teste no Grand Slam

Na versão USA original, a meta de ouro é **$280.000**, a de prata é
**$200.000**, a de bronze é **$60.000** e o Crashbreaker pede **10 batidas**.
Para tornar o teste fácil de reconhecer, uma combinação é mudar o ouro para
**$310.000**, o Crashbreaker para **6** e trocar `COMPCAR14` com `COMPCAR12`
no primeiro grupo.

Inicie a nova ISO pelo PCSX2 desde o boot e entre no Grand Slam pelo menu do
jogo. Pode usar seu progresso do memory card para acessar o evento. Um
savestate antigo restaura os dados da rodada anterior que já estavam na RAM.
Confira o ouro na apresentação do evento e o contador do Crashbreaker no início
da rodada. Observe separadamente se a distribuição dos modelos mudou.

Essa combinação foi exportada e iniciada no PCSX2 1.7.2521. A comparação
integral das imagens encontrou dez bytes diferentes nos dois arquivos previstos.
Após o boot, a tabela carregada pelo próprio jogo continha a chave do Grand Slam,
as metas de $310.000, $200.000 e $60.000 e o contador de seis batidas. A ordem
dos dois modelos foi conferida no arquivo da pista. O jogador iniciou o teste e
confirmou que a rodada funcionou. A identificação visual de cada modelo trocado
e o instante exato da ativação do Crashbreaker não foram registrados separadamente.
O próximo teste rastreia o primeiro carro vermelho até a sua origem no evento.
[Histórico dos testes](contexto-do-projeto.md) · [Plano de desenvolvimento](plano-de-desenvolvimento.md)

## Como os dados foram conferidos

- Os 100 registros de Crash em `PRGDATA.BIN` identificam o evento e a pista.
  A ordem das 100 chaves coincide com a usada pelo executável USA para buscar
  os títulos em `GLOBALUS.BIN`. Grand Slam usa a chave `1G0007EUC3V1` e o
  arquivo `TRACKS/EU/C3_V1/GAMEDATA.BGD`.
- A chave liga o registro em `DATA/STAGEHED.BIN` ao descritor no diretório da
  pista. As três metas ficam em `+0x3A0`, `+0x3A4` e `+0x3A8`. A tela do
  evento liga esses valores aos textos de ouro, prata e bronze. O campo em
  `+0x3AC` alimenta o contador de veículos batidos exibido pelo Crashbreaker.
- O bloco de cada evento contém seis grupos de modelos. Nos 100 eventos,
  trocar a ordem dos identificadores, reler e desfazer a troca recuperou os
  arquivos originais byte por byte. A exportação conserva os campos auxiliares
  dos modelos e as dimensões dos arquivos.
- Foram lidos 2.572 caminhos em 36 arquivos de pista. No Grand Slam, os 27
  caminhos e os 2.821 pares de pontos conferem com a captura do evento em
  memória. Os arquivos das variantes V1 e V2 da mesma pista podem compartilhar
  a geometria. O identificador do evento distingue qual delas foi carregada.
- Para exportar a ISO, o editor confere integralmente os arquivos de origem,
  conserva seus setores e verifica a cópia gravada por SHA-256 antes de
  disponibilizá-la. A edição ocupa a entrada existente no menu do jogo.
