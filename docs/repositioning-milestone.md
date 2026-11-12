# Primeiro reposicionamento observado

Em 12/11/2026 foi confirmado um deslocamento reversível de um veículo existente
no perfil USA pesquisado, usando uma cópia de estado salvo do PCSX2 1.7.2521.0.
O editor dentro do jogo ainda não existe.

O alvo foi um carro independente do pool de tráfego. Uma variante inicial só
mudou a fração lateral do caminho: isso deslocou a matriz de seguimento, mas
não o corpo físico. A posição visual é reconstruída a partir de dois pontos
absolutos do objeto, em `+0x00` e `+0x30`.

No teste confirmado foram deslocados os componentes X/Z dos dois pontos e da
translação da matriz em `+0xa0`, junto da fração lateral do nó em `+0x34`.
Foram sete floats de entrada; o delta foi
`(+2.1409912109375, 0, +0.3963623046875)` em unidades de mundo.

Após o passo configurado de 30 quadros, o corpo, a matriz do caminho, o alvo
armazenado e os limites AABB mantiveram esse delta. A caixa conservou suas
dimensões e a orientação ficou igual. O próprio jogo atualizou o alvo e os
limites; eles não foram escritos na variante. Os 253 outros registros do pool
de objetos ficaram idênticos ao controle, assim como suas matrizes. Um escalar
de um nó vizinho mudou; sua semântica ainda não está estabelecida.

Na imagem, a diferença ficou restrita ao veículo distante junto ao cruzamento.
Restaurar a referência devolveu exatamente o viewport de controle. As capturas,
estados salvos e relatórios de RAM ficam locais, fora deste repositório.

O usuário confirmou que veículos estacionados e lentos são parte normal desses
eventos. Estar parado não indica, por si só, defeito do estado ou do tráfego.

O resultado cobre um reposicionamento horizontal, um veículo independente e
uma janela curta de simulação. Ainda é necessário testar impacto contra o carro
deslocado, deslocamentos maiores, outros modelos, rotação, veículos articulados
e persistência de eventos. Adicionar/remover veículos exige manter recursos,
listas e física; eventos em locais novos também exigem investigar carregamento
e colisões dos mapas.
