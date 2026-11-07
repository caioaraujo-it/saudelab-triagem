# Saúdelab Exames Laboratoriais — Bot de Triagem 24h & Painel PWA Autenticado (v4.1.0)

Sistema enxuto, rápido e 24h de triagem automática para o WhatsApp da **Saúdelab Exames Laboratoriais** (`saudelabexames.com.br` — Vila Valqueire, Rio de Janeiro/RJ), com **Painel Web + PWA protegido por Login e Senha**.

---

## 1. Arquitetura Polida (Apenas o Necessário)

- `whatsapp.js` — Ponte WhatsApp (`@whiskeysockets/baileys`) + Servidor Web Autenticado (`http://127.0.0.1:5006`) com QR Code ao vivo, Logs em tempo real, chaveamento Teste/Produção e PWA Mobile.
- `bot.py` — Motor persistente em Python/Flask (`http://127.0.0.1:5007`) com máquina de estados em SQLite WAL (`triagem.db`), validação de CPF/Data de Nascimento, detecção de intenção de cotação/orçamento, tratamento de áudios/chamadas perdidas e timer de ociosidade.
- `test_suite.py` — Suíte automatizada de testes cobrindo todos os fluxos de negócio.
- `.env` / `.env.example` — Configurações de modo de operação, credenciais do painel e temporizadores.
- `Dockerfile` & `requirements.txt` — Prontos para deploy em nuvem ou VPS Linux.

---

## 2. Regras de Negócio Implementadas

1. **Atendimento 100% Particular e Foco em Triagem:**
   - Não envia preparo nem valores e não agenda horário (a recepcionista faz a cotação pelo **Worklab** e agenda diretamente).
   - A mensagem final enviada ao paciente contém apenas o texto cordial de confirmação (sem bloco de resumo técnico no chat).
2. **Menu de 5 Opções + Entendimento de Pedido de Cotação/Orçamento:**
   - `1` — Exames na Unidade / Orçamento (Rua dos Miosótis, 55 - Sala 504 - Vila Valqueire)
   - `2` — Coleta Domiciliar / Orçamento (pergunta bairro/endereço + exames)
   - `3` — Exame Toxicológico (CNH / DETRAN / Concurso / CLT — avança direto para Nome Completo)
   - `4` — Falar sobre um agendamento já realizado (pede Nome Completo + CPF/Data de Nascimento e encaminha)
   - `5` — Falar diretamente com uma atendente
   - Se o cliente já mandar mensagem pedindo **valor, preço, cotação, orçamento** ou mandar a **foto do pedido médico**, o bot entende a intenção, pergunta apenas se prefere **Unidade (1)** ou **Coleta Domiciliar (2)** e segue para Nome e CPF/Data de Nascimento.
3. **Validação de CPF e Data de Nascimento (Com ou Sem Máscara):**
   - Aceita CPF com ou sem pontuação (`123.456.789-01` ou `12345678901`) validando os dígitos verificadores.
   - Aceita Data de Nascimento com ou sem barras (`15/08/1985`, `15-08-1985` ou `15081985`).
   - Caso inválido, solicita gentilmente a digitação correta.
4. **Regras para Áudio e Ligações de WhatsApp:**
   - **Áudio no início/menu ou em Nome/CPF:** avisa gentilmente que a triagem automática não ouve áudios e pede para digitar a opção ou os dados (ou `5` para atendente).
   - **Áudio na etapa de Exames ou Endereço:** aceita o áudio normalmente e avança para o próximo passo.
   - **Ligação de Voz/Vídeo no WhatsApp:** inicia a triagem por mensagem **somente se a chamada não for atendida**. Se a equipe atender a ligação, o bot não envia mensagem.
5. **Controle de Ociosidade (5 minutos, até 2 avisos):**
   - A cada 5 minutos sem resposta na triagem, pergunta se o cliente ainda está lá (até 2 vezes).
   - Se continuar sem responder após a 2ª tentativa, encerra o atendimento (`state = IDLE`, `paused_for_human = 0`) e reativa automaticamente quando o cliente mandar nova mensagem.
6. **Painel Web + PWA com Login e Senha:**
   - Protegido pelas variáveis `PANEL_USER` e `PANEL_PASS` do `.env`.
   - Permite ler o QR Code, acompanhar os logs ao vivo, alternar entre **Modo Teste (`#saudelab`)** e **Modo Produção 24h**, ou desconectar/trocar o aparelho de WhatsApp com 1 clique.

---

## 3. Como Executar

```powershell
cd D:\Projetos\saudelab-triagem
node whatsapp.js
```

Acesse no navegador ou celular:
- **URL Local:** `http://127.0.0.1:5006`

---

**Criado por: Caio Araujo - Analista de TI | Build v4.1.0**
