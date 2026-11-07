# CONTEXTO DO PROJETO — Saúdelab Triagem Direta WhatsApp

**Versão Atual:** 4.3.0  
**Data de Atualização:** 07/11/2026  
**Responsável Técnico:** Caio Ferreira de Araujo — Analista de TI  
**Cliente:** Saúdelab Exames Laboratoriais (`saudelabexames.com.br`)  
**Endereço da Unidade:** Rua dos Miosótis, 55 - Sala 504 – Vila Valqueire, Rio de Janeiro - RJ  

---

## 1. Registro de Decisões e Evolução (v4.0.0)

- **Polimento e Limpeza Completa do Código:**
  - Removidos todos os arquivos antigos/não utilizados (`saudelab-bot` antigo, `cli_handler.py`, `testar_conversa.py`, `iniciar_bot.bat`, `qrcode_whatsapp.png`).
  - Mantidos exclusivamente os arquivos essenciais de produção (`bot.py`, `whatsapp.js`, `test_suite.py`, `.env`, `.env.example`, `Dockerfile`, `requirements.txt`, `package.json`, `app-icon.png`).
- **Autenticação por Login e Senha no Painel (`whatsapp.js`):**
  - Tela de login responsiva (`/login`) validando `PANEL_USER` e `PANEL_PASS` definidos no `.env` com sessão assinada via HMAC-SHA256 (`HttpOnly`).
  - Botão no painel para alternar com 1 clique entre **Modo Teste (`#saudelab`)** e **Modo Produção 24h** (`/api/toggle-mode`).
  - Botão no painel para **Desconectar / Trocar WhatsApp e Gerar Novo QR Code** (`/api/whatsapp-logout`), permitindo que a proprietária da Saúdelab conecte o número da clínica sem precisar de terminal.
- **Regras de Negócio Ativas:**
  - Atendimento 100% Particular; sem envio de preparo/preço pelo bot e sem resumo técnico no encerramento.
  - Validação de CPF (com/sem máscara) e Data de Nascimento (com/sem barra).
  - Detecção de intenção de cotação/orçamento e múltiplas fotos de pedido médico sem repetição de pergunta.
  - Tratamento inteligente de áudios e envio de triagem automática em chamadas de WhatsApp **apenas quando não atendidas**.
  - Timer de ociosidade de 5 minutos (até 2 tentativas), encerrando e reativando automaticamente se o cliente voltar a falar depois.

---

**Criado por: Caio Araujo - Analista de TI | Build v4.3.0**
