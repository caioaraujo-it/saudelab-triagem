# CONTEXTO COMPLETO DO PROJETO — Saúdelab Triagem 24h WhatsApp

**Nome do Projeto:** `saudelab-triagem`  
**Versão Atual:** `4.3.0`  
**Data da Última Atualização:** 07/11/2026  
**Responsável Técnico:** Caio Ferreira de Araujo — Analista de TI  
**Cliente:** Saúdelab Exames Laboratoriais (`saudelabexames.com.br`)  
**Endereço da Unidade:** Rua dos Miosótis, 55 - Sala 504 – Vila Valqueire, Rio de Janeiro - RJ  
**Repositório GitHub:** `https://github.com/caioaraujo-it/saudelab-triagem.git`  
**URL em Produção (Render Cloud):** `https://saudelab-triagem.onrender.com`  
**Healthcheck / Keep-Alive URL:** `https://saudelab-triagem.onrender.com/health`  

---

## 1. Objetivo e Escopo do Projeto

Sistema de triagem automática 24 horas para o WhatsApp oficial da **Saúdelab Exames Laboratoriais**, projetado para:
1. Atender o paciente imediatamente (24h por dia, 7 dias por semana), filtrando a demanda e coletando os dados essenciais antes de passar para a recepcionista humana.
2. Operar no **mesmo número de WhatsApp** usado pela recepção da clínica (via leitura de QR Code com `@whiskeysockets/baileys`), permitindo que o celular da clínica e o WhatsApp Web das recepcionistas funcionem simultaneamente.
3. Oferecer um **Painel Web + Aplicativo PWA Mobile/Desktop** protegido por login e senha (`PANEL_USER` e `PANEL_PASS`), permitindo que a proprietária da Saúdelab conecte o QR Code, acompanhe logs ao vivo e alterne entre Modo Teste e Modo Produção de qualquer lugar.

---

## 2. Regras de Negócio Consolidadas

### 2.1 Escopo de Atendimento (Exclusivamente Particular)
- A clínica trabalha **exclusivamente com atendimento Particular** (não atende convênios/planos de saúde).
- O bot **não** informa preços de exames e **não** envia instruções de preparo (jejum, etc.) — essas informações são enviadas pela recepcionista humana juntamente com o orçamento gerado no sistema **Worklab**.
- O bot **não** agenda horário — a combinação de data/horário é feita diretamente pela recepcionista após receber a triagem.
- **Sem bloco de resumo técnico no WhatsApp:** Ao finalizar a triagem, o bot envia apenas a mensagem cordial de confirmação ao paciente (`MENSAGEM_FINAL_TRIAGEM` ou `MENSAGEM_FINAL_AGENDAMENTO`), pois a recepcionista lê diretamente o histórico da conversa.

### 2.2 Menu Principal (5 Opções — Sem Emojis e Visualmente Espaçado)
1. **`1 - Agendamentos / Orçamentos`** — Unidade Vila Valqueire (Rua dos Miosótis, 55 - Sala 504)
   - Pergunta quais exames deseja realizar (aceita texto, foto/PDF do pedido médico ou áudio) $\rightarrow$ pede Nome Completo $\rightarrow$ pede CPF ou Data de Nascimento $\rightarrow$ encerra e passa para a recepcionista.
2. **`2 - Coleta Domiciliar / Orçamento`** — Atendimento no endereço da residência
   - Pergunta o bairro e endereço completo (aceita texto ou áudio) $\rightarrow$ pergunta quais exames (se ainda não informados) $\rightarrow$ pede Nome Completo $\rightarrow$ pede CPF ou Data de Nascimento $\rightarrow$ encerra e passa para a recepcionista.
3. **`3 - Exame Toxicológico`** — CNH / DETRAN / Concurso / CLT
   - Pergunta primeiro se o exame toxicológico é para **Concurso Público** (`1 - Sim` / `2 - Não`).
   - Se responder **1 (Sim)**: pergunta **qual é o concurso** (`WAIT_TOX_WHICH_CONCURSO`), registra o nome do concurso e avança para Nome Completo $\rightarrow$ CPF ou Data de Nascimento.
   - Se responder **2 (Não)**: registra `Exame Toxicológico (CNH / DETRAN / CLT)` e avança direto para Nome Completo $\rightarrow$ CPF ou Data de Nascimento.
4. **`4 - Falar sobre um agendamento já realizado`** — Dúvidas ou remarcação
   - Pede Nome Completo $\rightarrow$ pede CPF ou Data de Nascimento $\rightarrow$ encaminha para a recepcionista localizar o agendamento.
5. **`5 - Falar diretamente com uma atendente`** — Transbordo imediato para a recepção (pausa o bot por 1 hora para aquele contato).

### 2.3 Detecção Inteligente de Pedido de Cotação / Orçamento
- Muitos clientes já iniciam a conversa perguntando preços (`"quanto custa..."`, `"qual o valor..."`, `"quero fazer orçamento"`, `"hemograma"`, etc.) ou enviando a **foto do pedido médico**.
- Quando isso ocorre na abertura ou no menu, o bot reconhece a intenção, guarda os exames/foto já enviados e pergunta apenas se o cliente prefere **`1 - Na Unidade Vila Valqueire`** ou **`2 - Coleta Domiciliar`**, seguindo para Nome Completo e CPF/Data de Nascimento sem repetir perguntas.
- Se o cliente enviar múltiplas fotos do pedido médico em sequência, o bot acumula os anexos silenciosamente sem repetir a pergunta do nome.

### 2.4 Validação de CPF e Data de Nascimento (Com ou Sem Máscara)
- **CPF:** Valida os 11 dígitos e os 2 dígitos verificadores matemáticos, aceitando com pontuação (`123.456.789-01`) ou sem pontuação (`12345678901`), salvando sempre formatado.
- **Data de Nascimento:** Valida datas reais entre `1900` e o ano atual, aceitando com barras/traços (`01/03/2000`, `01-03-2000`) ou 8 dígitos diretos sem máscara (`01032000`), salvando sempre como `DD/MM/AAAA`.
- Caso o cliente digite um valor inválido, o bot solicita a correção (até 2 tentativas; na 2ª falha seguida, transfere para a atendente).

### 2.5 Pausa Automática de 1 Hora quando a Atendente Assume (`fromMe`)
- Assim que qualquer atendente responde na conversa pelo celular da clínica ou WhatsApp Web (`fromMe = true`, seja texto, áudio, imagem ou documento), o bot **aborta imediatamente a triagem em andamento** e pausa o atendimento automático para aquele cliente por **1 hora (`3600` segundos, configurável via `HUMAN_PAUSE_MINUTES`)**.
- Durante essa 1 hora, o bot permanece 100% silencioso para não atropelar a conversa humana.
- Após 1 hora sem bloqueio (ou se a atendente enviar `#bot`, `#reiniciar`, `#reinicio` ou `#saudelab`), o bot volta a ficar disponível para aquele contato.

### 2.6 Tratamento de Áudios e Limite de 2 Tentativas (Clientes com Dificuldade de Leitura)
- **Etapas de Exames (`WAIT_EXAMS`), Endereço (`WAIT_ADDRESS`) e Nome do Concurso (`WAIT_TOX_WHICH_CONCURSO`):** O bot **aceita áudio normalmente** e avança para a próxima etapa.
- **Etapas de Seleção de Opção ou Dados Cadastrais (Menu, Modalidade, Nome, CPF/Data):**
  - **1ª tentativa inválida / 1º áudio (`retry_count = 1`):** O bot explica gentilmente que está na triagem automática e pede para digitar o número da opção ou o dado por texto.
  - **2ª tentativa seguida sem sucesso (`retry_count >= 2`):** Para não prender clientes que não sabem ler ou só enviam áudio, o bot encerra a tentativa automática, informa que está seguindo pelo caminho da **Opção 5 (Falar diretamente com uma atendente)** e pausa o bot por 1 hora para a recepcionista atender.

### 2.7 Ligações de Voz/Vídeo no WhatsApp
- O sistema monitora eventos `call` (`offer`, `accept`, `timeout`, `reject`, `terminate`).
- **Se a chamada for atendida (`accept`) pela equipe:** O bot não envia mensagem.
- **Se a chamada NÃO for atendida:** E o cliente não estiver em pausa humana de 1h nem tiver acabado de receber mensagem nos últimos 45s, o bot envia automaticamente `MENSAGEM_CHAMADA_PERDIDA` iniciando a triagem por texto.

### 2.8 Controle de Ociosidade (5 Minutos, até 2 Tentativas)
- Se o cliente parar de responder no meio da triagem, o bot aguarda **5 minutos** (`INACTIVITY_MINUTES=5`) e pergunta se ele ainda está lá (até **2 vezes**, aos 5 min e aos 10 min).
- Se após mais 5 minutos da 2ª tentativa o cliente não responder, o bot envia a mensagem de encerramento por inatividade e reseta a sessão para `IDLE` (`paused_for_human = 0`), reativando normalmente caso o cliente volte a mandar mensagem depois.

---

## 3. Arquitetura Técnica e Estrutura de Arquivos (`D:\Projetos\saudelab-triagem\`)

| Arquivo | Função |
| :--- | :--- |
| `whatsapp.js` | Processo principal Node.js: conecta ao WhatsApp via `@whiskeysockets/baileys`, gerencia o Motor Python como subprocesso, hospeda o Servidor Web/PWA na porta `5006` com Login/Senha, QR Code, Logs ao Vivo e rota `/health`. |
| `bot.py` | Motor de regras de negócio em Python/Flask (porta interna `5007`), banco SQLite em modo WAL (`triagem.db`), máquina de estados, validações de CPF/Data, timer de ociosidade e pausa de 1h. |
| `test_suite.py` | Suíte com 15 testes automatizados cobrindo todas as regras de negócio (`python test_suite.py`). |
| `Dockerfile` | Imagem Docker unificada (`node:20-bookworm-slim` + `python3` + `flask` + `baileys`) usada pelo Render.com. |
| `render.yaml` | Blueprint de configuração do serviço gratuito no Render.com. |
| `package.json` | Dependências Node.js (`@whiskeysockets/baileys`, `pino`, `qrcode`, `qrcode-terminal`). |
| `requirements.txt` | Dependências Python (`flask`, `python-dotenv`). |
| `app-icon.png` / `app-icon-192.png` | Ícones PNG reais (`512x512` e `192x192`) para instalação do PWA no iOS, Android e Desktop. |
| `.env` / `.env.example` | Variáveis de ambiente locais e modelo de configuração. |

---

## 4. Máquina de Estados (`sessions.state` no SQLite)

- `IDLE` — Sem triagem ativa (ou aguardando início / pausado para atendente se `paused_for_human = 1`).
- `WAIT_MENU_OPTION` — Menu principal de 5 opções enviado; aguardando escolha ou intenção de cotação.
- `WAIT_MODALITY_AFTER_QUOTE` — Cliente pediu cotação/exame direto; aguardando escolha entre `1` (Unidade) ou `2` (Domiciliar).
- `WAIT_TOX_CONCURSO` — Cliente escolheu Exame Toxicológico; aguardando resposta se é para Concurso Público (`1 - Sim` / `2 - Não`).
- `WAIT_TOX_WHICH_CONCURSO` — Cliente informou que o Toxicológico é para concurso; aguardando nome do concurso.
- `WAIT_ADDRESS` — Coleta Domiciliar escolhida; aguardando bairro e endereço completo.
- `WAIT_EXAMS` — Aguardando lista de exames (texto, foto/PDF ou áudio).
- `WAIT_NAME` — Aguardando nome completo do(a) paciente por texto.
- `WAIT_CPF_OR_BIRTH` — Aguardando CPF válido ou Data de Nascimento válida para finalizar a triagem.

---

## 5. Hospedagem Gratuita 24h (Render + Cron-Job.org)

1. **GitHub:** Código hospedado em `https://github.com/caioaraujo-it/saudelab-triagem.git` (branch `main`).
2. **Render.com:** Web Service Docker gratuito conectado à branch `main` com Auto-Deploy ativado (`https://saudelab-triagem.onrender.com`).
3. **Keep-Alive 24h:** Monitor externo no `cron-job.org` fazendo `GET https://saudelab-triagem.onrender.com/health` a cada 5 minutos + auto-ping interno em `whatsapp.js`.
4. **Como atualizar no futuro:**
   ```powershell
   cd D:\Projetos\saudelab-triagem
   git add -A
   git commit -m "Descricao da alteracao"
   git push origin main
   ```
   O Render detecta o `git push` e publica a nova versão automaticamente em ~2 minutos.

---

## 6. Histórico de Versões

- **v1.0.0:** Versão inicial enxuta focada em triagem direta.
- **v2.0.0:** Motor Python persistente em Flask, correção de JID `@lid`, opção 4 de agendamento existente e timer de inatividade.
- **v3.0.0:** Validação de CPF e Data de Nascimento (com/sem máscara), detecção de cotação, regras de áudio e chamadas perdidas, remoção do bloco de resumo técnico.
- **v4.0.0:** Polimento completo do código, autenticação por Login e Senha no painel, botão de troca Teste/Produção, botão de desconexão de WhatsApp e deploy em nuvem no Render.
- **v4.1.0:** Correção de responsividade mobile (cards empilhados em telas pequenas), ícones PNG reais e notificação/botão de instalação do aplicativo PWA.
- **v4.2.0:** Ajuste de `safe-area-inset-top` para o Notch/Dynamic Island do iPhone 13/14/15 no modo PWA instalado e novo espaçamento visual do menu.
- **v4.3.0:** Pausa imediata de 1 hora quando a atendente assume a conversa (`fromMe`), limite de 2 tentativas de áudio/erro com transbordo automático para a Opção 5, fluxo de Exame Toxicológico perguntando se é Concurso Público e qual concurso, remoção de emojis das opções e renomeação da Opção 1 para `Agendamentos / Orçamentos`.

---

**Criado por: Caio Araujo - Analista de TI | Build v4.3.0**
