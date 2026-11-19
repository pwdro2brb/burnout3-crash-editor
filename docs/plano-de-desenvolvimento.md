# Plano de desenvolvimento do editor de eventos de Crash

O **primeiro marco jogável** é entrar no Grand Slam pelo menu, encontrar o primeiro carro vermelho em outra posição da mesma via e conseguir bater nele. Hoje já temos a geometria dessa pista, um teste de colisão com o carro deslocado em memória e uma exportação de ISO confirmada pelo jogador. Falta ligar o veículo visto na rua aos dados que determinam sua entrada no evento. [Histórico e evidências](contexto-do-projeto.md)

## Oito etapas em ordem

As issues guardam os critérios de conclusão e os resultados conforme a pesquisa avança. As etapas 1 e 2 formam o primeiro teste de ponta a ponta.

| Etapa | Entrega | Como reconhecer o resultado |
| ---: | --- | --- |
| 1 | Identificar a origem do carro vermelho no Grand Slam. | Em duas aproximações comparáveis, conseguimos explicar o caminho, o sentido e a condição que traz o carro à via. Se a escolha de modelo variar, identificamos a regra que se repete. [Issue #1](https://github.com/pwdro2brb/burnout3-crash-editor/issues/1) |
| 2 | Mover um veículo de forma persistente na ISO. | Uma edição isolada muda onde o carro aparece em relação a um marco da rua. Ao reentrar na fase pelo menu, o veículo volta ao ponto escolhido, segue a via e participa da colisão. [Issue #2](https://github.com/pwdro2brb/burnout3-crash-editor/issues/2) |
| 3 | Editar a posição pelo mapa do evento. | O autor seleciona o alvo, distingue faixa, sentido e vias sobrepostas, escolhe o destino e reproduz a edição anterior sem digitar coordenadas. [Issue #3](https://github.com/pwdro2brb/burnout3-crash-editor/issues/3) |
| 4 | Adicionar e remover tráfego na definição nativa. | Uma variante ganha um carro e outra perde o veículo escolhido. Ao repetir o percurso, a mudança também funciona para uma entrada de tráfego posterior à largada. [Issue #4](https://github.com/pwdro2brb/burnout3-crash-editor/issues/4) |
| 5 | Ajustar comportamento e veículos especiais. | Testamos velocidade e espaçamento em via livre e com fila. Ensaios separados cobrem contramão, veículos parados, ônibus e cabine com carga. O conjunto articulado mantém o vínculo ao rodar e bater. [Issue #5](https://github.com/pwdro2brb/burnout3-crash-editor/issues/5) |
| 6 | Criar um Crash em outro cruzamento de uma pista existente. | Dentro de uma entrada de teste já existente no menu, o jogador larga, chega ao novo cruzamento, provoca a batida e alcança a tela de resultados. A rodada pode ser repetida. [Issue #6](https://github.com/pwdro2brb/burnout3-crash-editor/issues/6) |
| 7 | Reabrir e compartilhar um projeto de edição nativa. | Duas pessoas com extrações idênticas aplicam o mesmo projeto e obtêm os mesmos arquivos. O teste inclui dois eventos que compartilham uma pista e preserva as duas edições. [Issue #7](https://github.com/pwdro2brb/burnout3-crash-editor/issues/7) |
| 8 | Investigar uma entrada própria no menu e no progresso. | Se for viável ampliar o catálogo, um evento adicional aparece junto aos 100 originais, abre pelo nome e guarda a medalha após reiniciar o jogo. O ensaio usa uma cópia do memory card e confere entradas vizinhas. [Issue #8](https://github.com/pwdro2brb/burnout3-crash-editor/issues/8) |

## Como testar o primeiro deslocamento

1. Na ISO de referência, entrar em Grand Slam pelo menu. Dirigir até a curva e escolher um marco visível na rua de mão dupla. Registrar onde o carro surge e em qual sentido passa. A captura com o caminho 21 ajuda a investigar a correspondência.
2. Em uma cópia da ISO, alterar somente o dado de tráfego cuja ligação ao carro foi demonstrada. Manter os modelos, metas e contador de Crashbreaker iguais entre as duas imagens.
3. Iniciar a cópia pelo menu e repetir a aproximação. Conferir o deslocamento em relação ao marco da rua, o comportamento de um veículo próximo e a colisão com o alvo. Reentrar pelo menu para confirmar que a edição persiste. Um savestate da rodada antiga pode trazer de volta os dados anteriores.

## Dependências que podem mudar o plano

- **Entrada de tráfego.** Se o jogo gerar veículos por regra, o mapa deverá representar a entrada, o grupo e o trecho de via que o autor realmente consegue controlar.
- **Tamanho dos recursos.** O exportador atual conserva tamanhos e setores. Para acrescentar registros na etapa 4, será preciso verificar espaço no bloco e como o carregador encontra as estruturas dependentes. [Formato atual](native-crash-events.md)
- **Densidade e física.** Registrar em separado veículos presentes, concentração no cruzamento e veículos convertidos para a batida. As falhas observadas com cerca de 61–65 envolvidos orientam os ensaios. Ainda falta identificar o recurso que se esgota. [Ensaios de alta densidade](high-density-experiments.md)
- **Progresso.** O editor atual lê cinco grupos de vinte eventos. A criação de uma entrada adicional depende de entender a busca de nomes no executável, os índices de progressão e a gravação no memory card.
