import os
import re
import json
import time
import sqlite3
import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv(override=True)

VERSION = "4.3.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "triagem.db")
LOG_PATH = os.path.join(BASE_DIR, "triagem.log")

app = Flask(__name__)


# ==============================================================================
# UTILITÁRIOS DE CONFIGURAÇÃO E LOGS DE AUDITORIA
# ==============================================================================
def log_event(event_type: str, jid: str, details: str) -> None:
    now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    short_jid = str(jid).split("@")[0]
    line = f"[{now_str}] [{event_type}] [{short_jid}] {details}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_recent_logs(limit: int = 80) -> list[str]:
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.readlines() if ln.strip()]
        return lines[-limit:][::-1]
    except Exception:
        return []


def is_test_mode() -> bool:
    load_dotenv(override=True)
    return os.getenv("TEST_MODE", "true").strip().lower() in ("true", "1", "yes", "sim")


def get_trigger_word() -> str:
    load_dotenv(override=True)
    return os.getenv("TRIGGER_WORD", "#saudelab").strip().lower()


def get_inactivity_seconds() -> int:
    load_dotenv(override=True)
    mins = float(os.getenv("INACTIVITY_MINUTES", "5"))
    return max(10, int(mins * 60))


def get_max_followups() -> int:
    load_dotenv(override=True)
    return int(os.getenv("MAX_FOLLOWUPS", "2"))


def get_human_pause_seconds() -> int:
    load_dotenv(override=True)
    mins = float(os.getenv("HUMAN_PAUSE_MINUTES", "60"))
    return max(60, int(mins * 60))


# ==============================================================================
# VALIDAÇÃO DE CPF E DATA DE NASCIMENTO (COM OU SEM MÁSCARA)
# ==============================================================================
def is_valid_cpf_digits(digits: str) -> bool:
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for i in range(9, 11):
        val = sum(int(digits[num]) * ((i + 1) - num) for num in range(0, i))
        digit = ((val * 10) % 11) % 10
        if digit != int(digits[i]):
            return False
    return True


def format_cpf(digits: str) -> str:
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def parse_valid_birth_date(text: str, digits: str) -> str | None:
    current_year = datetime.date.today().year
    day, month, year = None, None, None

    m = re.search(r"\b(\d{1,2})[/\-\.\s](\d{1,2})[/\-\.\s](\d{2,4})\b", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 1900 if year > (current_year % 100) else 2000
    elif len(digits) == 8:
        day, month, year = int(digits[:2]), int(digits[2:4]), int(digits[4:])

    if day and month and year and (1900 <= year <= current_year):
        try:
            dt = datetime.date(year, month, day)
            if dt <= datetime.date.today():
                return dt.strftime("%d/%m/%Y")
        except ValueError:
            return None
    return None


def validate_cpf_or_birthdate(raw_text: str) -> tuple[bool, str]:
    text = (raw_text or "").strip()
    digits = "".join(c for c in text if c.isdigit())
    found_parts = []

    cpf_candidates = re.findall(r"(?:\d{3}[\.\-\s]?\d{3}[\.\-\s]?\d{3}[\.\-\s]?\d{2}|\b\d{11}\b)", text)
    for cand in cpf_candidates:
        c_digits = "".join(c for c in cand if c.isdigit())
        if len(c_digits) == 11 and is_valid_cpf_digits(c_digits):
            found_parts.append(f"CPF: {format_cpf(c_digits)}")
            break

    if not found_parts and len(digits) == 11:
        if is_valid_cpf_digits(digits):
            found_parts.append(f"CPF: {format_cpf(digits)}")
        else:
            return (
                False,
                "O CPF informado parece conter algum número incorreto.\n"
                "Por favor, confira e digite novamente o seu CPF (apenas números ou com pontos) ou a sua data de nascimento (ex: 01/03/2000):",
            )

    bdate = parse_valid_birth_date(text, digits if len(digits) == 8 else "")
    if bdate:
        found_parts.append(f"Data Nasc.: {bdate}")

    if found_parts:
        return True, " | ".join(found_parts)

    return (
        False,
        "Não consegui validar o CPF ou a data de nascimento informada.\n"
        "Por favor, digite novamente um CPF válido (11 dígitos) ou a data de nascimento com dia, mês e ano (ex: 01/03/2000 ou 01032000):",
    )


# ==============================================================================
# DETECÇÃO DE INTENÇÃO DE COTAÇÃO / ORÇAMENTO
# ==============================================================================
QUOTE_KEYWORDS = (
    "valor",
    "valores",
    "preco",
    "preço",
    "preços",
    "cotacao",
    "cotação",
    "orcamento",
    "orçamento",
    "quanto custa",
    "quanto é",
    "quanto e",
    "quanto ta",
    "quanto tá",
    "quanto fica",
    "exame",
    "exames",
    "hemograma",
    "sangue",
    "glicose",
    "colesterol",
    "urina",
    "fezes",
    "tsh",
    "t4",
    "vitamina",
    "beta",
    "sexagem",
    "pedido",
)


def detect_quote_or_exam_intent(text_lower: str) -> bool:
    return any(kw in text_lower for kw in QUOTE_KEYWORDS)


# ==============================================================================
# MENSAGENS PADRONIZADAS (SEM EMOJIS, LIMPAS E BEM ESPAÇADAS)
# ==============================================================================
BLOCO_OPCOES_MENU = (
    "*1 - Agendamentos / Orçamentos*\n"
    "Unidade Vila Valqueire (Rua dos Miosótis, 55 - Sala 504)\n\n"
    "*2 - Coleta Domiciliar / Orçamento*\n"
    "Atendimento no endereço da sua residência\n\n"
    "*3 - Exame Toxicológico*\n"
    "CNH / DETRAN / Concurso / CLT\n\n"
    "*4 - Falar sobre um agendamento já realizado*\n"
    "Dúvidas ou remarcação de agendamento\n\n"
    "*5 - Falar diretamente com uma atendente*\n"
    "Atendimento direto com a nossa recepção"
)

MENSAGEM_MENU = (
    "Olá! Seja bem-vindo(a) à *Saúdelab Exames Laboratoriais* (Vila Valqueire).\n"
    "Nosso atendimento é *particular* e personalizado.\n\n"
    "Como podemos ajudar você hoje?\n"
    "Digite apenas o *número* da opção desejada:\n\n"
    + BLOCO_OPCOES_MENU
)

MENSAGEM_CHAMADA_PERDIDA = (
    "Olá! Vimos que você tentou nos ligar agora na *Saúdelab Exames Laboratoriais* (Vila Valqueire).\n"
    "Podemos adiantar o seu atendimento ou orçamento por aqui mesmo!\n\n"
    "Como podemos ajudar você hoje?\n"
    "Digite apenas o *número* da opção desejada:\n\n"
    + BLOCO_OPCOES_MENU
)

MENSAGEM_AUDIO_NO_MENU = (
    "Recebemos o seu áudio! No momento estou no atendimento automático de triagem e ainda não consigo ouvir áudios.\n\n"
    "Para agilizarmos o seu atendimento, digite o *número* de uma das opções abaixo (ou digite *5* para uma atendente ouvir o seu áudio):\n\n"
    + BLOCO_OPCOES_MENU
)

MENSAGEM_AUDIO_DADOS_CADASTRAIS = (
    "Para que não haja nenhum erro de digitação no seu cadastro, por favor escreva essa informação *por texto* "
    "(ou digite *5* caso prefira falar diretamente com a nossa recepcionista):"
)

MENSAGEM_TRANSBORDO_APOS_TENTATIVAS = (
    "Recebemos a sua mensagem!\n\n"
    "Como não conseguimos concluir o preenchimento automático por aqui, vamos seguir pelo caminho da *Opção 5 (Falar diretamente com uma atendente)*.\n\n"
    "Uma de nossas recepcionistas já vai ouvir a sua mensagem e atender você por aqui em instantes!"
)

MENSAGEM_COTA_MODALIDADE = (
    "Olá! Seja bem-vindo(a) à *Saúdelab Exames Laboratoriais* (Vila Valqueire).\n\n"
    "Para prepararmos a cotação dos seus exames, onde você prefere realizar a coleta?\n"
    "Digite o *número* da opção:\n\n"
    "*1 - Na Unidade Vila Valqueire*\n"
    "Rua dos Miosótis, 55 - Sala 504\n\n"
    "*2 - Coleta Domiciliar*\n"
    "Vamos até o seu endereço"
)

MENSAGEM_PERGUNTA_TOX_CONCURSO = (
    "Realizamos o *Exame Toxicológico* na nossa unidade em Vila Valqueire (Rua dos Miosótis, 55 - Sala 504).\n\n"
    "O seu exame toxicológico é para *Concurso Público*?\n"
    "Digite o *número* da opção:\n\n"
    "*1 - Sim, é para Concurso Público*\n\n"
    "*2 - Não (é para CNH / DETRAN / CLT / Outros)*"
)

MENSAGEM_QUAL_CONCURSO = (
    "Certo! Para qual *concurso* é o seu Exame Toxicológico?\n"
    "Por favor, escreva o nome do concurso abaixo:"
)

MENSAGEM_ENDERECO_DOMICILIAR = (
    "Certo, faremos o atendimento por *Coleta Domiciliar*.\n\n"
    "Por favor, informe o seu *bairro e endereço completo* (rua, número e complemento):"
)

MENSAGEM_PEDIR_EXAMES = (
    "Quais *exames* você precisa realizar?\n\n"
    "Você pode:\n"
    "- Escrever os nomes dos exames\n"
    "- Enviar a *foto do pedido médico*\n"
    "- Ou mandar um *áudio* falando os exames"
)

MENSAGEM_PEDIR_NOME = (
    "Obrigado!\n\n"
    "Para adiantarmos o seu atendimento e orçamento, qual é o *nome completo* do(a) paciente?"
)

MENSAGEM_PEDIR_CPF_NASC = (
    "Por favor, informe também o *CPF* ou a *data de nascimento* do(a) paciente\n"
    "_(pode digitar com ou sem pontuação)_:"
)

MENSAGEM_FINAL_TRIAGEM = (
    "Perfeito, muito obrigado pelas informações!\n\n"
    "Uma de nossas recepcionistas já recebeu a sua solicitação e vai dar sequência ao seu atendimento por aqui mesmo "
    "para enviar o seu orçamento, as orientações de preparo e combinar o melhor horário com você."
)

MENSAGEM_FINAL_AGENDAMENTO = (
    "Obrigado pelas informações!\n\n"
    "Já encaminhei os seus dados para a nossa recepcionista localizar o seu agendamento e dar sequência ao seu atendimento por aqui."
)

MENSAGEM_FOLLOWUP_INATIVIDADE = (
    "Olá! Você ainda está por aí?\n"
    "Estamos aguardando a sua resposta para concluir a sua triagem na *Saúdelab Exames*.\n\n"
    "_(Caso deseje voltar ao menu inicial, digite *0*)_."
)

MENSAGEM_ENCERRAMENTO_INATIVIDADE = (
    "Como não recebemos sua resposta, encerramos este atendimento automático por enquanto.\n\n"
    "Quando precisar, basta enviar uma nova mensagem por aqui que o atendimento será iniciado novamente!"
)


# ==============================================================================
# CAMADA DE DADOS (SQLite WAL)
# ==============================================================================
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                phone TEXT PRIMARY KEY,
                state TEXT DEFAULT 'IDLE',
                data_json TEXT DEFAULT '{}',
                paused_for_human INTEGER DEFAULT 0,
                paused_until_ts INTEGER DEFAULT 0,
                whitelisted INTEGER DEFAULT 0,
                followup_count INTEGER DEFAULT 0,
                last_activity_ts INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS triagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                phone TEXT NOT NULL,
                modality TEXT NOT NULL,
                address TEXT DEFAULT '',
                exams TEXT NOT NULL,
                patient_name TEXT NOT NULL,
                cpf_or_birth TEXT NOT NULL
            );
            """
        )
        # Garante coluna paused_until_ts em bancos já existentes
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(sessions);").fetchall()]
        if "paused_until_ts" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN paused_until_ts INTEGER DEFAULT 0;")
        conn.commit()


def clean_phone(jid_or_phone: str) -> str:
    raw = str(jid_or_phone or "").strip()
    if "@" in raw:
        return raw
    digits = "".join(c for c in raw if c.isdigit())
    return f"{digits}@s.whatsapp.net" if digits else "desconhecido@s.whatsapp.net"


def pause_session_for_human(conn: sqlite3.Connection, jid: str, now_ts: int, now_str: str, reason_log: str) -> None:
    pause_until = now_ts + get_human_pause_seconds()
    conn.execute(
        """
        INSERT INTO sessions (phone, state, data_json, paused_for_human, paused_until_ts, followup_count, last_activity_ts, updated_at)
        VALUES (?, 'IDLE', '{}', 1, ?, 0, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            state = 'IDLE',
            data_json = '{}',
            paused_for_human = 1,
            paused_until_ts = excluded.paused_until_ts,
            followup_count = 0,
            last_activity_ts = excluded.last_activity_ts,
            updated_at = excluded.updated_at
        """,
        (jid, pause_until, now_ts, now_str),
    )
    conn.commit()
    log_event("PAUSA_HUMANA_1H", jid, reason_log)


def is_currently_paused_for_human(conn: sqlite3.Connection, row: sqlite3.Row, now_ts: int, now_str: str) -> bool:
    if int(row["paused_for_human"] or 0) == 0:
        return False
    paused_until = int(row["paused_until_ts"] or 0)
    if paused_until > 0 and now_ts >= paused_until:
        # Passou 1 hora desde que o humano assumiu -> libera o bot novamente
        conn.execute(
            """
            UPDATE sessions
            SET paused_for_human = 0, paused_until_ts = 0, state = 'IDLE', data_json = '{}', followup_count = 0, updated_at = ?
            WHERE phone = ?
            """,
            (now_str, row["phone"]),
        )
        conn.commit()
        log_event("PAUSA_1H_EXPIRADA", row["phone"], "Pausa de 1h expirou; bot reativado para este contato")
        return False
    return True


def escalate_after_two_retries(
    conn: sqlite3.Connection,
    jid: str,
    data: dict,
    now_ts: int,
    now_str: str,
    first_try_reply: str,
    log_label: str,
) -> tuple[bool, str]:
    """
    Controla até 2 tentativas quando o cliente manda áudio em etapa de opção/cadastro ou digita opção inválida.
    Na 1ª vez: retorna first_try_reply.
    Na 2ª vez seguida: encerra o bot e transfere para a atendente (Opção 5) pausando por 1 hora.
    """
    retries = int(data.get("retry_count", 0)) + 1
    data["retry_count"] = retries
    if retries >= 2:
        pause_session_for_human(
            conn,
            jid,
            now_ts,
            now_str,
            f"2 tentativas sem sucesso ({log_label}) -> Encaminhado automaticamente para Opção 5 (Atendente)",
        )
        return True, MENSAGEM_TRANSBORDO_APOS_TENTATIVAS
    return False, first_try_reply


# ==============================================================================
# MOTOR DE TRIAGEM E CHAMADAS PERDIDAS
# ==============================================================================
def handle_missed_call(phone: str) -> str | None:
    init_db()
    jid = clean_phone(phone)
    now_ts = int(time.time())
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE phone = ?", (jid,)).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO sessions (phone, state, data_json, paused_for_human, paused_until_ts, whitelisted, followup_count, last_activity_ts, updated_at)
                VALUES (?, 'IDLE', '{}', 0, 0, 0, 0, ?, ?)
                """,
                (jid, now_ts, now_str),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM sessions WHERE phone = ?", (jid,)).fetchone()

        if is_test_mode() and int(row["whitelisted"] or 0) == 0:
            return None

        if is_currently_paused_for_human(conn, row, now_ts, now_str):
            return None

        # Evita reenviar o menu se o bot já acabou de enviar mensagem há menos de 45s
        last_ts = int(row["last_activity_ts"] or 0)
        if row["state"] != "IDLE" and (now_ts - last_ts) < 45:
            log_event("CHAMADA_IGNORADA", jid, "Cliente já está com menu/triagem ativa nos últimos 45s")
            return None

        conn.execute(
            """
            UPDATE sessions
            SET state = 'WAIT_MENU_OPTION', data_json = '{}', paused_for_human = 0, paused_until_ts = 0,
                followup_count = 0, last_activity_ts = ?, updated_at = ?
            WHERE phone = ?
            """,
            (now_ts, now_str, jid),
        )
        conn.commit()
        log_event("CHAMADA_PERDIDA", jid, "Chamada não atendida -> Triagem iniciada")
        return MENSAGEM_CHAMADA_PERDIDA


def handle_message(phone: str, text: str, is_media: bool = False, is_audio: bool = False) -> str | None:
    init_db()
    jid = clean_phone(phone)
    text = (text or "").strip()
    text_lower = text.lower()
    now_ts = int(time.time())
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if is_audio and not text:
        text = "[Áudio enviado pelo cliente]"
        text_lower = text.lower()
    elif is_media and not text:
        text = "[Foto/Arquivo do Pedido Médico enviado pelo cliente]"
        text_lower = text.lower()

    trigger = get_trigger_word()
    test_mode = is_test_mode()

    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE phone = ?", (jid,)).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO sessions (phone, state, data_json, paused_for_human, paused_until_ts, whitelisted, followup_count, last_activity_ts, updated_at)
                VALUES (?, 'IDLE', '{}', 0, 0, 0, 0, ?, ?)
                """,
                (jid, now_ts, now_str),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM sessions WHERE phone = ?", (jid,)).fetchone()

        # Ativação explícita por #saudelab, #bot, #reiniciar ou #reinicio
        if text_lower in (trigger, "#bot", "#reiniciar", "#reinicio"):
            conn.execute(
                """
                UPDATE sessions
                SET state = 'WAIT_MENU_OPTION', data_json = '{}', paused_for_human = 0, paused_until_ts = 0,
                    whitelisted = 1, followup_count = 0, last_activity_ts = ?, updated_at = ?
                WHERE phone = ?
                """,
                (now_ts, now_str, jid),
            )
            conn.commit()
            log_event("INICIO_SESSAO", jid, f"Ativado por comando '{text}'")
            return MENSAGEM_MENU

        state = row["state"]
        whitelisted = int(row["whitelisted"] or 0)

        if test_mode and state == "IDLE" and whitelisted == 0:
            return None

        if is_currently_paused_for_human(conn, row, now_ts, now_str):
            return None

        data = json.loads(row["data_json"] or "{}")

        # Acumula fotos seguidas do pedido médico sem repetir a pergunta do nome
        if state == "WAIT_NAME" and is_media and not is_audio and data.get("exams"):
            data["exams"] = f"{data.get('exams')} + {text}"
            conn.execute(
                "UPDATE sessions SET data_json = ?, last_activity_ts = ?, updated_at = ? WHERE phone = ?",
                (json.dumps(data, ensure_ascii=False), now_ts, now_str, jid),
            )
            conn.commit()
            log_event("ANEXO_EXTRA_EXAMES", jid, "Foto adicional anexada aos exames")
            return None

        # Voltar ao menu inicial digitando 0
        if text_lower in ("0", "menu", "voltar") and state != "IDLE":
            conn.execute(
                """
                UPDATE sessions
                SET state = 'WAIT_MENU_OPTION', data_json = '{}', followup_count = 0,
                    last_activity_ts = ?, updated_at = ?
                WHERE phone = ?
                """,
                (now_ts, now_str, jid),
            )
            conn.commit()
            log_event("RETORNO_MENU", jid, "Cliente digitou 0/menu")
            return MENSAGEM_MENU

        # Permite digitar 5 em qualquer etapa para falar com a recepcionista (pausa por 1h)
        if text == "5" and state in ("WAIT_NAME", "WAIT_CPF_OR_BIRTH", "WAIT_MODALITY_AFTER_QUOTE", "WAIT_TOX_CONCURSO", "WAIT_TOX_WHICH_CONCURSO"):
            pause_session_for_human(conn, jid, now_ts, now_str, "Cliente digitou 5 para falar com atendente")
            return (
                "Certo. Uma de nossas recepcionistas já vai atender você por aqui em instantes. "
                "Se desejar, já pode adiantar sua dúvida ou enviar a foto do seu pedido médico abaixo."
            )

        reply = ""

        # ======================================================================
        # ESTADO 1: INÍCIO OU REATIVAÇÃO APÓS OCIOSIDADE
        # ======================================================================
        if state in ("IDLE", "START"):
            if is_audio:
                state = "WAIT_MENU_OPTION"
                data = {"retry_count": 1}
                log_event("AUDIO_INICIO", jid, "Cliente iniciou com áudio (1/2) -> Enviada orientação + Menu")
                reply = MENSAGEM_AUDIO_NO_MENU
            elif any(w in text_lower for w in ("toxicologico", "toxicológico", "detran", "cnh")):
                data = {
                    "flow": "TRIAGEM_EXAMES",
                    "modality": "Exame Toxicológico (Unidade)",
                    "address": "Unidade (Rua dos Miosótis, 55 - Sala 504)",
                    "retry_count": 0,
                }
                state = "WAIT_TOX_CONCURSO"
                log_event("INTENCAO_DIRETA", jid, f"Toxicológico detectado na abertura: '{text}'")
                reply = MENSAGEM_PERGUNTA_TOX_CONCURSO
            elif is_media:
                data = {"flow": "TRIAGEM_EXAMES", "exams": text, "retry_count": 0}
                state = "WAIT_MODALITY_AFTER_QUOTE"
                log_event("INTENCAO_FOTO_PEDIDO", jid, "Cliente enviou foto do pedido médico na abertura")
                reply = MENSAGEM_COTA_MODALIDADE
            elif detect_quote_or_exam_intent(text_lower):
                generic_phrases = ("quero fazer orcamento", "quero fazer orçamento", "orcamento", "orçamento", "cotacao", "cotação", "valor", "valores", "preco", "preço")
                if text_lower not in generic_phrases and len(text) > 12:
                    data = {"flow": "TRIAGEM_EXAMES", "exams": text, "retry_count": 0}
                else:
                    data = {"flow": "TRIAGEM_EXAMES", "retry_count": 0}
                state = "WAIT_MODALITY_AFTER_QUOTE"
                log_event("INTENCAO_ORCAMENTO", jid, f"Solicitação de cotação detectada: '{text}'")
                reply = MENSAGEM_COTA_MODALIDADE
            else:
                state = "WAIT_MENU_OPTION"
                data = {"retry_count": 0}
                log_event("MENU_ENVIADO", jid, f"Mensagem recebida: '{text}'")
                reply = MENSAGEM_MENU

        # ======================================================================
        # ESTADO 2: MENU PRINCIPAL (5 OPÇÕES)
        # ======================================================================
        elif state == "WAIT_MENU_OPTION":
            if is_audio:
                escalated, msg_out = escalate_after_two_retries(
                    conn, jid, data, now_ts, now_str, MENSAGEM_AUDIO_NO_MENU, "Áudio no menu"
                )
                if escalated:
                    return msg_out
                reply = msg_out

            elif text == "1" or "unidade" in text_lower:
                data["flow"] = "TRIAGEM_EXAMES"
                data["modality"] = "Agendamentos / Orçamentos (Unidade Vila Valqueire)"
                data["address"] = "Unidade (Rua dos Miosótis, 55 - Sala 504)"
                data["retry_count"] = 0
                state = "WAIT_EXAMS"
                reply = MENSAGEM_PEDIR_EXAMES

            elif text == "2" or "domiciliar" in text_lower or "casa" in text_lower:
                data["flow"] = "TRIAGEM_EXAMES"
                data["modality"] = "Coleta Domiciliar"
                data["retry_count"] = 0
                state = "WAIT_ADDRESS"
                reply = MENSAGEM_ENDERECO_DOMICILIAR

            elif text == "3" or any(w in text_lower for w in ("toxicologico", "toxicológico", "detran", "cnh")):
                data["flow"] = "TRIAGEM_EXAMES"
                data["modality"] = "Exame Toxicológico (Unidade)"
                data["address"] = "Unidade (Rua dos Miosótis, 55 - Sala 504)"
                data["retry_count"] = 0
                state = "WAIT_TOX_CONCURSO"
                reply = MENSAGEM_PERGUNTA_TOX_CONCURSO

            elif text == "4" or any(w in text_lower for w in ("agendamento", "marcado", "remarcar")):
                data["flow"] = "SUPORTE_AGENDAMENTO"
                data["modality"] = "Falar sobre Agendamento Realizado"
                data["address"] = "-"
                data["exams"] = "Solicitação referente a agendamento existente"
                data["retry_count"] = 0
                state = "WAIT_NAME"
                reply = (
                    "Certo, vamos localizar o seu agendamento.\n"
                    "Por favor, informe o *nome completo* do(a) paciente:"
                )

            elif text == "5" or "atendente" in text_lower or "recepcionista" in text_lower:
                pause_session_for_human(conn, jid, now_ts, now_str, "Cliente escolheu opção 5 (Atendente)")
                return (
                    "Certo. Uma de nossas recepcionistas já vai atender você por aqui em instantes. "
                    "Se desejar, já pode adiantar sua dúvida ou enviar a foto do seu pedido médico abaixo."
                )

            elif is_media or detect_quote_or_exam_intent(text_lower):
                generic_phrases = ("quero fazer orcamento", "quero fazer orçamento", "orcamento", "orçamento", "cotacao", "cotação", "valor", "valores", "preco", "preço")
                if is_media or (text_lower not in generic_phrases and len(text) > 10):
                    data["exams"] = text
                data["flow"] = "TRIAGEM_EXAMES"
                data["retry_count"] = 0
                state = "WAIT_MODALITY_AFTER_QUOTE"
                log_event("COTA_NO_MENU", jid, f"Cliente pediu cotação/exame direto no menu: '{text}'")
                reply = (
                    "Anotei a sua solicitação para cotação!\n\n"
                    "Onde você prefere realizar a coleta?\n"
                    "Digite o *número* da opção:\n\n"
                    "*1 - Na Unidade Vila Valqueire*\n"
                    "Rua dos Miosótis, 55 - Sala 504\n\n"
                    "*2 - Coleta Domiciliar*\n"
                    "Vamos até o seu endereço"
                )

            else:
                fallback_menu = (
                    "Por favor, digite apenas o *número* de uma das opções abaixo (ou escreva os exames que deseja orçar):\n\n"
                    + BLOCO_OPCOES_MENU
                )
                escalated, msg_out = escalate_after_two_retries(
                    conn, jid, data, now_ts, now_str, fallback_menu, f"Opção inválida no menu: '{text}'"
                )
                if escalated:
                    return msg_out
                reply = msg_out

        # ======================================================================
        # ESTADO 2.1: MODALIDADE APÓS PEDIDO DIRETO DE COTAÇÃO
        # ======================================================================
        elif state == "WAIT_MODALITY_AFTER_QUOTE":
            if is_audio:
                msg_try = (
                    "Não consigo ouvir áudios nesta etapa.\n"
                    "Por favor, digite *1* para realizar na Unidade Vila Valqueire ou *2* para Coleta Domiciliar "
                    "(ou digite *5* para falar com a recepcionista):"
                )
                escalated, msg_out = escalate_after_two_retries(
                    conn, jid, data, now_ts, now_str, msg_try, "Áudio na escolha de modalidade"
                )
                if escalated:
                    return msg_out
                reply = msg_out
            elif text == "1" or "unidade" in text_lower:
                data["modality"] = "Agendamentos / Orçamentos (Unidade Vila Valqueire)"
                data["address"] = "Unidade (Rua dos Miosótis, 55 - Sala 504)"
                data["retry_count"] = 0
                if data.get("exams"):
                    state = "WAIT_NAME"
                    reply = MENSAGEM_PEDIR_NOME
                else:
                    state = "WAIT_EXAMS"
                    reply = MENSAGEM_PEDIR_EXAMES
            elif text == "2" or "domiciliar" in text_lower or "casa" in text_lower:
                data["modality"] = "Coleta Domiciliar"
                data["retry_count"] = 0
                state = "WAIT_ADDRESS"
                reply = MENSAGEM_ENDERECO_DOMICILIAR
            else:
                msg_try = "Por favor, digite *1* para realizar na Unidade Vila Valqueire ou *2* para Coleta Domiciliar:"
                escalated, msg_out = escalate_after_two_retries(
                    conn, jid, data, now_ts, now_str, msg_try, f"Opção inválida na modalidade: '{text}'"
                )
                if escalated:
                    return msg_out
                reply = msg_out

        # ======================================================================
        # ESTADO 2.2: EXAME TOXICOLÓGICO — É CONCURSO PÚBLICO?
        # ======================================================================
        elif state == "WAIT_TOX_CONCURSO":
            if is_audio:
                msg_try = (
                    "Por favor, digite *1* se o Exame Toxicológico for para Concurso Público ou *2* se for para CNH / DETRAN / CLT:"
                )
                escalated, msg_out = escalate_after_two_retries(
                    conn, jid, data, now_ts, now_str, msg_try, "Áudio na pergunta de concurso toxicológico"
                )
                if escalated:
                    return msg_out
                reply = msg_out
            elif text == "1" or text_lower in ("sim", "s", "concurso", "concurso publico", "concurso público"):
                data["retry_count"] = 0
                state = "WAIT_TOX_WHICH_CONCURSO"
                reply = MENSAGEM_QUAL_CONCURSO
            elif text == "2" or any(w in text_lower for w in ("nao", "não", "n", "cnh", "detran", "clt", "carteira", "motorista")):
                data["exams"] = "Exame Toxicológico (CNH / DETRAN / CLT)"
                data["retry_count"] = 0
                state = "WAIT_NAME"
                reply = MENSAGEM_PEDIR_NOME
            elif "concurso" in text_lower and len(text) > 10:
                # Cliente já respondeu dizendo qual é o concurso na mesma frase
                data["exams"] = f"Exame Toxicológico — Concurso: {text}"
                data["retry_count"] = 0
                state = "WAIT_NAME"
                reply = MENSAGEM_PEDIR_NOME
            else:
                msg_try = (
                    "Por favor, digite *1* se for para Concurso Público ou *2* se não for (CNH / DETRAN / CLT):"
                )
                escalated, msg_out = escalate_after_two_retries(
                    conn, jid, data, now_ts, now_str, msg_try, f"Resposta inválida em WAIT_TOX_CONCURSO: '{text}'"
                )
                if escalated:
                    return msg_out
                reply = msg_out

        # ======================================================================
        # ESTADO 2.3: EXAME TOXICOLÓGICO — QUAL CONCURSO?
        # ======================================================================
        elif state == "WAIT_TOX_WHICH_CONCURSO":
            data["exams"] = f"Exame Toxicológico — Concurso: {text}"
            data["retry_count"] = 0
            state = "WAIT_NAME"
            reply = MENSAGEM_PEDIR_NOME

        # ======================================================================
        # ESTADO 2.4: ENDEREÇO DA COLETA DOMICILIAR
        # ======================================================================
        elif state == "WAIT_ADDRESS":
            data["address"] = text
            data["retry_count"] = 0
            if is_audio:
                log_event("AUDIO_ENDERECO", jid, "Cliente enviou o endereço por áudio")
            if data.get("exams"):
                state = "WAIT_NAME"
                reply = "Endereço registrado.\n\n" + MENSAGEM_PEDIR_NOME
            else:
                state = "WAIT_EXAMS"
                reply = "Endereço registrado.\n\n" + MENSAGEM_PEDIR_EXAMES

        # ======================================================================
        # ESTADO 3: EXAMES OU PEDIDO MÉDICO (TEXTO, FOTO/PDF OU ÁUDIO)
        # ======================================================================
        elif state == "WAIT_EXAMS":
            data["exams"] = text
            data["retry_count"] = 0
            if is_audio:
                log_event("AUDIO_EXAMES", jid, "Cliente enviou os exames por áudio")
            state = "WAIT_NAME"
            reply = MENSAGEM_PEDIR_NOME

        # ======================================================================
        # ESTADO 4: NOME COMPLETO DO PACIENTE
        # ======================================================================
        elif state == "WAIT_NAME":
            if is_audio:
                escalated, msg_out = escalate_after_two_retries(
                    conn, jid, data, now_ts, now_str, MENSAGEM_AUDIO_DADOS_CADASTRAIS, "Áudio na etapa de Nome"
                )
                if escalated:
                    return msg_out
                reply = msg_out
            elif len(text) < 3 or text.isdigit():
                msg_try = "Por favor, informe o *nome completo* do(a) paciente por texto:"
                escalated, msg_out = escalate_after_two_retries(
                    conn, jid, data, now_ts, now_str, msg_try, f"Nome inválido: '{text}'"
                )
                if escalated:
                    return msg_out
                reply = msg_out
            else:
                data["patient_name"] = text
                data["retry_count"] = 0
                state = "WAIT_CPF_OR_BIRTH"
                reply = MENSAGEM_PEDIR_CPF_NASC

        # ======================================================================
        # ESTADO 5: VALIDAÇÃO DE CPF OU DATA DE NASCIMENTO -> FINALIZA TRIAGEM
        # ======================================================================
        elif state == "WAIT_CPF_OR_BIRTH":
            if is_audio:
                escalated, msg_out = escalate_after_two_retries(
                    conn, jid, data, now_ts, now_str, MENSAGEM_AUDIO_DADOS_CADASTRAIS, "Áudio na etapa de CPF/Data"
                )
                if escalated:
                    return msg_out
                reply = msg_out
            else:
                is_valid, formatted_or_error = validate_cpf_or_birthdate(text)
                if not is_valid:
                    log_event("CPF_DATA_INVALIDO", jid, f"Digitou '{text}' -> Solicitada correção")
                    escalated, msg_out = escalate_after_two_retries(
                        conn, jid, data, now_ts, now_str, formatted_or_error, f"CPF/Data inválido: '{text}'"
                    )
                    if escalated:
                        return msg_out
                    reply = msg_out
                else:
                    data["cpf_or_birth"] = formatted_or_error
                    flow_type = data.get("flow", "TRIAGEM_EXAMES")

                    conn.execute(
                        """
                        INSERT INTO triagens (created_at, phone, modality, address, exams, patient_name, cpf_or_birth)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            now_str,
                            jid,
                            data.get("modality", "Unidade"),
                            data.get("address", ""),
                            data.get("exams", ""),
                            data.get("patient_name", ""),
                            data.get("cpf_or_birth", ""),
                        ),
                    )

                    resumo = MENSAGEM_FINAL_AGENDAMENTO if flow_type == "SUPORTE_AGENDAMENTO" else MENSAGEM_FINAL_TRIAGEM
                    pause_session_for_human(
                        conn,
                        jid,
                        now_ts,
                        now_str,
                        f"Triagem concluída: {data.get('patient_name')} ({data.get('cpf_or_birth')})",
                    )
                    return resumo

        conn.execute(
            """
            UPDATE sessions
            SET state = ?, data_json = ?, followup_count = 0, last_activity_ts = ?, updated_at = ?
            WHERE phone = ?
            """,
            (state, json.dumps(data, ensure_ascii=False), now_ts, now_str, jid),
        )
        conn.commit()
        log_event("AVANCO_ETAPA", jid, f"Etapa atual: {state}")
        return reply


# ==============================================================================
# VERIFICADOR DE OCIOSIDADE (5 MINUTOS E ATÉ 2 TENTATIVAS -> ENCERRA E REATIVA DEPOIS)
# ==============================================================================
def check_inactive_sessions() -> list[dict]:
    init_db()
    now_ts = int(time.time())
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    interval_sec = get_inactivity_seconds()
    max_followups = get_max_followups()
    outbound = []

    with get_db() as conn:
        # Libera sessões cuja pausa humana de 1h já expirou
        paused_rows = conn.execute("SELECT * FROM sessions WHERE paused_for_human = 1").fetchall()
        for p_row in paused_rows:
            is_currently_paused_for_human(conn, p_row, now_ts, now_str)

        active_rows = conn.execute(
            """
            SELECT * FROM sessions
            WHERE state NOT IN ('IDLE', 'START')
              AND paused_for_human = 0
            """
        ).fetchall()

        for row in active_rows:
            last_ts = int(row["last_activity_ts"] or 0)
            if now_ts - last_ts < interval_sec:
                continue

            f_count = int(row["followup_count"] or 0)
            jid = row["phone"]

            if f_count < max_followups:
                new_count = f_count + 1
                conn.execute(
                    """
                    UPDATE sessions
                    SET followup_count = ?, last_activity_ts = ?, updated_at = ?
                    WHERE phone = ?
                    """,
                    (new_count, now_ts, now_str, jid),
                )
                log_event("AVISO_INATIVIDADE", jid, f"Aviso {new_count}/{max_followups} enviado (5 min sem resposta)")
                outbound.append({"jid": jid, "text": MENSAGEM_FOLLOWUP_INATIVIDADE, "attempt": new_count})
            else:
                conn.execute(
                    """
                    UPDATE sessions
                    SET state = 'IDLE', data_json = '{}', paused_for_human = 0, paused_until_ts = 0,
                        followup_count = 0, last_activity_ts = ?, updated_at = ?
                    WHERE phone = ?
                    """,
                    (now_ts, now_str, jid),
                )
                log_event("ENCERRADO_POR_OCIOSIDADE", jid, f"Atendimento encerrado após {max_followups} avisos; pronto p/ reativar")
                outbound.append({"jid": jid, "text": MENSAGEM_ENCERRAMENTO_INATIVIDADE, "attempt": "closed"})

        conn.commit()

    return outbound


# ==============================================================================
# ENDPOINTS HTTP INTERNOS DO MOTOR PYTHON
# ==============================================================================
@app.route("/api/message", methods=["POST"])
def api_message():
    init_db()
    d = request.json or {}
    jid = clean_phone(d.get("jid", ""))
    text = d.get("text", "")
    from_me = bool(d.get("fromMe"))
    is_media = bool(d.get("isMedia"))
    is_audio = bool(d.get("isAudio"))

    trigger = get_trigger_word()
    text_clean = (text or "").strip().lower()

    if from_me:
        # Comandos explícitos de ativação/reinício do bot
        if text_clean in (trigger, "#bot", "#reiniciar", "#reinicio"):
            reply = handle_message(jid, text, is_media=is_media, is_audio=is_audio)
            return jsonify({"reply": reply})

        # Qualquer outra mensagem enviada pela atendente/aparelho aborta a triagem na hora por 1 hora!
        now_ts = int(time.time())
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            pause_session_for_human(
                conn,
                jid,
                now_ts,
                now_str,
                "Atendente assumiu a conversa -> Triagem abortada por 1 hora",
            )
        return jsonify({"reply": None})

    reply = handle_message(jid, text, is_media=is_media, is_audio=is_audio)
    return jsonify({"reply": reply})


@app.route("/api/missed_call", methods=["POST"])
def api_missed_call():
    d = request.json or {}
    jid = clean_phone(d.get("jid", ""))
    reply = handle_missed_call(jid)
    return jsonify({"reply": reply})


@app.route("/api/inactivity", methods=["POST"])
def api_inactivity():
    items = check_inactive_sessions()
    return jsonify({"items": items})


@app.route("/api/toggle_mode", methods=["POST"])
def api_toggle_mode():
    d = request.json or {}
    new_test_mode = "true" if d.get("test_mode") else "false"
    os.environ["TEST_MODE"] = new_test_mode
    env_path = os.path.join(BASE_DIR, ".env")
    content = ""
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()
    if "TEST_MODE=" in content:
        content = re.sub(r"TEST_MODE=\w+", f"TEST_MODE={new_test_mode}", content)
    else:
        content = (content.rstrip() + f"\nTEST_MODE={new_test_mode}\n").lstrip()
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass
    log_event("MODO_ALTERADO", "PAINEL", f"Modo alterado pelo painel: TEST_MODE={new_test_mode}")
    return jsonify({"ok": True, "test_mode": is_test_mode()})


@app.route("/api/status", methods=["GET"])
def api_status():
    init_db()
    now_ts = int(time.time())
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        paused_rows = conn.execute("SELECT * FROM sessions WHERE paused_for_human = 1").fetchall()
        for p_row in paused_rows:
            is_currently_paused_for_human(conn, p_row, now_ts, now_str)

        active = [
            dict(r)
            for r in conn.execute("SELECT * FROM sessions WHERE state != 'IDLE' OR paused_for_human = 1 ORDER BY updated_at DESC").fetchall()
        ]
        triagens = [
            dict(r)
            for r in conn.execute("SELECT * FROM triagens ORDER BY id DESC LIMIT 15").fetchall()
        ]
    return jsonify(
        {
            "version": VERSION,
            "test_mode": is_test_mode(),
            "trigger_word": get_trigger_word(),
            "inactivity_minutes": int(get_inactivity_seconds() / 60),
            "max_followups": get_max_followups(),
            "active_sessions": active,
            "recent_triagens": triagens,
            "logs": get_recent_logs(80),
        }
    )


if __name__ == "__main__":
    init_db()
    api_port = int(os.getenv("BOT_ENGINE_PORT", "5007"))
    log_event("SISTEMA_INICIADO", "SISTEMA", f"Motor Saúdelab v{VERSION} online")
    print(f"[ENGINE PYTHON] Saúdelab Triagem v{VERSION} rodando em http://127.0.0.1:{api_port}")
    app.run(host="127.0.0.1", port=api_port, debug=False, threaded=True)
