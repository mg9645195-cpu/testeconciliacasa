@echo off
chcp 65001 >nul
echo ============================================================================
echo   BIORENAL - SISTEMA DE CONCILIAÇÃO BANCÁRIA, RATEIO 1:N E BI EM SAÚDE 2026
echo   Centro de Hemodiálise de Santa Inês/MA
echo ============================================================================
echo.
echo [1] Abrindo navegador em: http://127.0.0.1:8090
echo [2] Para acesso de outro PC, siga CONFIGURAR_REDE.md e use HTTPS.
echo.
echo Não feche esta janela enquanto estiver utilizando o sistema.
echo.
start http://127.0.0.1:8090
python "%~dp0backend\server.py" 8090
pause
