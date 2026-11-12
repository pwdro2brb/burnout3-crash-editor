# Nova referência para tráfego em movimento

Em 12/11/2026 o usuário substituiu o slot 1. A nova gravação foi copiada para
uma referência separada, com SHA-256 estável antes/depois da leitura:
`68e2c8429aa8ef5dfb31c62d248fe86467eaba7f7cd8ba696865dc40a4be4476`.
Seu tamanho é 14.309.260 bytes. A referência anterior foi preservada.

Na cópia isolada do PCSX2, o estado restaurou a introdução do evento
**Grand Slam**. Portanto, não é apenas uma regravação da referência anterior
da curva/rampa. Nenhum veículo foi modificado nesta nova referência.

O pool contém 10 objetos e 9 nós ativos, com invariantes estruturais válidos.
As quatro palavras de código de controle coincidem com o ELF pesquisado e as
duas áreas de injeção conhecidas estão zeradas. Isso é uma verificação
localizada, não uma prova de que todos os dados do estado são originais.

Cinco nós, associados ao caminho candidato 20, possuem valor 60 no campo
`+0x00`; quatro, associados ao caminho 21, possuem valor 30. No campo `+0x2c`
há valores candidatos de velocidade entre aproximadamente 11,35 e 26,82.
Na referência anterior, os 16 valores de `+0x00` examinados eram zero.
Esses campos corroboram a utilidade da nova referência, mas não substituem
uma medição temporal de movimento no jogo.

Segundo o usuário, é necessário avançar e entrar à direita para alcançar uma
rua com tráfego em sentidos opostos. Esse percurso ainda não foi realizado
na conferência visual: a captura desta etapa mostra a introdução do evento.

Para o próximo teste, os objetos independentes 0–4 e 7–9 oferecem candidatos.
Os objetos 5/6 formam um par articulado e ficam fora do caso validado pelo
protótipo. É necessário observar o fluxo, selecionar um veículo visível e
comparar controle/variante no mesmo intervalo antes de afirmar que o método
de reposicionamento já foi validado para veículos em movimento.

Não foi criada uma instância adicional. Adicionar veículos permanece uma
investigação separada de alterar a posição de uma instância existente.
