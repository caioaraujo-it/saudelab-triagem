# Saúdelab Exames Laboratoriais — Bot de Triagem 24h & Painel PWA Autenticado (v4.3.0)

Sistema completo de triagem automática 24h via WhatsApp para a **Saúdelab Exames Laboratoriais** (`saudelabexames.com.br` — Rua dos Miosótis, 55 - Sala 504, Vila Valqueire, Rio de Janeiro/RJ), com Painel Web + PWA Responsivo (Celular, Tablet e PC) protegido por Login e Senha.

- **URL em Produção:** `https://saudelab-triagem.onrender.com`
- **Healthcheck 24h:** `https://saudelab-triagem.onrender.com/health`
- **Repositório GitHub:** `https://github.com/caioaraujo-it/saudelab-triagem.git`

---

## 1. Principais Funcionalidades

1. **Menu de 5 Opções Limpo e Espaçado (Sem Emojis):**
   - `1 - Agendamentos / Orçamentos` (Unidade Vila Valqueire)
   - `2 - Coleta Domiciliar / Orçamento` (Atendimento na residência)
   - `3 - Exame Toxicológico` (Pergunta se é para Concurso Público e qual concurso, ou CNH/DETRAN/CLT)
   - `4 - Falar sobre um agendamento já realizado`
   - `5 - Falar diretamente com uma atendente`
2. **Atendente Assume a Conversa $\rightarrow$ Pausa Automática de 1 Hora:**
   - Assim que uma recepcionista envia qualquer mensagem na conversa (`fromMe`), o bot aborta a triagem imediatamente e fica pausado por **1 hora** para aquele cliente, sem interromper o atendimento humano.
3. **Regra de 2 Tentativas para Áudios / Dificuldade de Leitura:**
   - Aceita áudios normalmente quando o cliente está informando os exames, o endereço ou o nome do concurso.
   - Nas etapas de escolha de opção ou Nome/CPF, tenta orientar até **2 vezes**; na 2ª tentativa sem sucesso, transfere automaticamente para a **Opção 5 (Atendente)**.
4. **Validação de CPF e Data de Nascimento (Com ou Sem Pontuação):**
   - Valida dígitos verificadores de CPF (`123.456.789-01` ou `12345678901`) e datas reais (`01/03/2000` ou `01032000`).
5. **Chamadas de Voz/Vídeo Não Atendidas:**
   - Se um cliente ligar pelo WhatsApp e a chamada **não for atendida**, o bot inicia a triagem por texto automaticamente. Se a chamada for atendida, o bot não envia nada.
6. **Timer de Ociosidade (5 Minutos, até 2 Avisos):**
   - Envia até 2 lembretes a cada 5 minutos de inatividade e encerra o atendimento caso não haja resposta, reativando quando o cliente mandar nova mensagem.
7. **Painel PWA Instalável (iOS, Android e PC):**
   - Protegido por Login e Senha (`PANEL_USER` / `PANEL_PASS`), adaptável ao Notch do iPhone e com botão para instalar na tela inicial, alternar entre Modo Teste (`#saudelab`) e Produção 24h, visualizar logs em tempo real e gerar novo QR Code.

---

## 2. Variáveis de Ambiente (`.env` / Render Environment)

```env
TEST_MODE=true
TRIGGER_WORD=#saudelab
INACTIVITY_MINUTES=5
MAX_FOLLOWUPS=2
HUMAN_PAUSE_MINUTES=60
STATUS_PORT=5006
BOT_ENGINE_PORT=5007
PANEL_USER=saudelab
PANEL_PASS= DEFINIR_SENHA_NO_AMBIENTE
PANEL_SECRET= DEFINIR_CHAVE_SECRETA
```

---

## 3. Comandos Úteis (Execução Local, Testes e Deploy)

### Rodar a suíte de 15 testes automatizados:
```powershell
cd D:\Projetos\saudelab-triagem
python test_suite.py
```

### Enviar atualizações para o Render (Auto-Deploy via GitHub):
```powershell
cd D:\Projetos\saudelab-triagem
git add -A
git commit -m "Descricao da alteracao"
git push origin main
```

Para detalhes completos da arquitetura, máquina de estados e histórico de decisões, consulte o arquivo [`CONTEXTO_PROJETO.md`](./CONTEXTO_PROJETO.md).

---

**Criado por: Caio Araujo - Analista de TI | Build v4.3.0**
