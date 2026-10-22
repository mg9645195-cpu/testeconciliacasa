# BioRenal ERP — módulo financeiro

Aplicativo local para conciliação bancária, prestação de contas, notas e tributos, projeção de pagamentos e prestadores. O servidor é Python com SQLite; a interface usa JavaScript e bibliotecas estáticas locais em `public/vendor/`.

## Dados e privacidade

O código não precisa das planilhas ou do banco de produção no GitHub. O arquivo SQLite, planilhas, certificados HTTPS, chaves privadas e logs ficam em `data/` e são ignorados pelo Git. Nunca copie a pasta `data/` para outro computador para dar acesso ao sistema: os usuários devem acessar o servidor do PC principal pelo navegador.

O repositório teve versões antigas com arquivos de dados rastreados. Removê-los da versão mais recente não apaga o histórico anterior. Mantenha o repositório privado e planeje a limpeza do histórico separadamente antes de qualquer publicação pública.

## Execução local

Instale Python 3.12+ e `pip install -r requirements.txt`. Coloque a planilha oficial em `data/` ou use uma cópia íntegra do banco em `data/biorenal_2026.db`. Execute `python backend/server.py 8090` e abra `http://127.0.0.1:8090/login.html`. O primeiro administrador só pode ser criado neste PC.

O aplicativo empacotado inclui o Python necessário e atalhos que iniciam o servidor sem manter uma janela CMD aberta. Para instalar em outro PC e configurar HTTPS, siga [CONFIGURAR_REDE.md](CONFIGURAR_REDE.md).
