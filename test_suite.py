import time
import bot


def run_all_tests() -> None:
    print("============================================================")
    print(" EXECUTANDO BATERIA COMPLETA DE TESTES — SAUDELAB v4.3.0")
    print("============================================================")

    bot.init_db()
    with bot.get_db() as conn:
        conn.execute("DELETE FROM sessions;")
        conn.commit()

    # 1 a 6: Validação de CPF e Data de Nascimento (com e sem máscara)
    ok_cpf1, val_cpf1 = bot.validate_cpf_or_birthdate("52998224725")
    assert ok_cpf1 and "529.982.247-25" in val_cpf1
    print(f"[OK] 01. CPF sem máscara validado e formatado: {val_cpf1}")

    ok_cpf2, val_cpf2 = bot.validate_cpf_or_birthdate("529.982.247-25")
    assert ok_cpf2 and "529.982.247-25" in val_cpf2
    print(f"[OK] 02. CPF com máscara validado: {val_cpf2}")

    ok_bad_cpf, err_cpf = bot.validate_cpf_or_birthdate("111.111.111-11")
    assert not ok_bad_cpf and "incorreto" in err_cpf
    print("[OK] 03. CPF inválido (111.111.111-11) rejeitado corretamente.")

    ok_dt1, val_dt1 = bot.validate_cpf_or_birthdate("01/03/2000")
    assert ok_dt1 and "01/03/2000" in val_dt1
    print(f"[OK] 04. Data com barras validada: {val_dt1}")

    ok_dt2, val_dt2 = bot.validate_cpf_or_birthdate("01032000")
    assert ok_dt2 and "01/03/2000" in val_dt2
    print(f"[OK] 05. Data sem máscara (01032000) validada e formatada: {val_dt2}")

    ok_bad_dt, _ = bot.validate_cpf_or_birthdate("35/14/2000")
    assert not ok_bad_dt
    print("[OK] 06. Data impossível (35/14/2000) rejeitada corretamente.")

    # 7: Novo nome da Opção 1 ("1 - Agendamentos / Orçamentos") e ausência de emojis
    jid_menu = "5521999990000@s.whatsapp.net"
    r_menu = bot.handle_message(jid_menu, "#saudelab")
    assert "*1 - Agendamentos / Orçamentos*" in r_menu
    for emoji in ("📍", "🏠", "🚗", "📅", "👩‍⚕️"):
        assert emoji not in r_menu
    print("[OK] 07. Menu sem emojis e com '1 - Agendamentos / Orçamentos' validado.")

    # 8: Fluxo de Cotação Direta + Rejeição de dado errado + Sucesso sem resumo
    jid_quote = "5521999995555@s.whatsapp.net"
    bot.handle_message(jid_quote, "#saudelab")
    r_quote = bot.handle_message(jid_quote, "Oi, quanto custa o exame de hemograma e glicose?")
    assert "Unidade Vila Valqueire" in r_quote and "Coleta Domiciliar" in r_quote
    r_after_mod = bot.handle_message(jid_quote, "1")
    assert "nome completo" in r_after_mod
    bot.handle_message(jid_quote, "Giovanna Teste")
    r_wrong = bot.handle_message(jid_quote, "123456")
    assert "Não consegui validar" in r_wrong
    r_done = bot.handle_message(jid_quote, "01032000")
    assert "Uma de nossas recepcionistas já recebeu" in r_done and "RESUMO DA TRIAGEM" not in r_done
    print("[OK] 08. Fluxo de Cotação Direta + Rejeição de dado errado + Sucesso sem resumo.")

    # 9: Exame Toxicológico (Opção 3) perguntando se é Concurso e Qual Concurso
    jid_tox = "5521988881111@s.whatsapp.net"
    bot.handle_message(jid_tox, "#saudelab")
    r_tox1 = bot.handle_message(jid_tox, "3")
    assert "Concurso Público" in r_tox1
    r_tox2 = bot.handle_message(jid_tox, "1")  # Sim, é para Concurso Público
    assert "qual *concurso*" in r_tox2.lower()
    r_tox3 = bot.handle_message(jid_tox, "Polícia Militar PMERJ")
    assert "nome completo" in r_tox3
    bot.handle_message(jid_tox, "Carlos Concurseiro")
    r_tox_done = bot.handle_message(jid_tox, "01/03/2000")
    assert "Uma de nossas recepcionistas já recebeu" in r_tox_done
    with bot.get_db() as conn:
        t_row = conn.execute("SELECT * FROM triagens WHERE patient_name = 'Carlos Concurseiro' ORDER BY id DESC LIMIT 1").fetchone()
        assert t_row and "Concurso: Polícia Militar PMERJ" in t_row["exams"]
    print("[OK] 09. Fluxo Exame Toxicológico (pergunta se é Concurso + Qual Concurso) validado.")

    # 10: Regra de 2 tentativas para Áudio -> Encaminha para Opção 5 (Atendente) na 2ª tentativa!
    phone_aud = "5521977774444@s.whatsapp.net"
    bot.handle_message(phone_aud, "#saudelab")
    r_aud1 = bot.handle_message(phone_aud, "", is_audio=True)  # 1º áudio no menu
    assert "ainda não consigo ouvir áudios" in r_aud1
    r_aud2 = bot.handle_message(phone_aud, "", is_audio=True)  # 2º áudio seguido -> Transfere p/ Opção 5!
    assert "Opção 5" in r_aud2 and "recepcionistas já vai ouvir" in r_aud2
    # Se mandar 3º áudio, bot já está pausado por 1h para a atendente
    r_aud3 = bot.handle_message(phone_aud, "", is_audio=True)
    assert r_aud3 is None
    print("[OK] 10. Regra de 2 tentativas de Áudio -> Transbordo automático para Opção 5 e pausa de 1h.")

    # 11: Atendente assumindo no meio da conversa (fromMe=True, mesmo em TEST_MODE=true) -> Aborta triagem por 1 hora!
    phone_takeover = "5521966663333@s.whatsapp.net"
    bot.handle_message(phone_takeover, "#saudelab")
    bot.handle_message(phone_takeover, "1")  # escolhe Agendamentos/Orçamentos
    r_step_name = bot.handle_message(phone_takeover, "Hemograma")
    assert "nome completo" in r_step_name
    # Agora a atendente (fromMe=True) manda "Pode falar" no meio da triagem!
    with bot.app.test_client() as client:
        resp = client.post("/api/message", json={"jid": phone_takeover, "text": "Pode falar", "fromMe": True})
        assert resp.status_code == 200 and resp.get_json()["reply"] is None
    # Cliente responde "Te amo" -> O bot NÃO pode responder porque a atendente assumiu!
    r_after_human = bot.handle_message(phone_takeover, "Te amo")
    assert r_after_human is None
    # Simula passagem de 1 hora (3605 segundos) -> Bot volta a ficar disponível caso o cliente chame depois!
    with bot.get_db() as conn:
        conn.execute("UPDATE sessions SET paused_until_ts = ? WHERE phone = ?", (int(time.time()) - 10, phone_takeover))
        conn.commit()
    r_after_1h = bot.handle_message(phone_takeover, "Oi, quero fazer exame")
    assert "1 - Agendamentos / Orçamentos" in r_after_1h or "Unidade Vila Valqueire" in r_after_1h
    print("[OK] 11. Atendente assumindo aborta a triagem na hora por 1h e reativa após 1h.")

    # 12 a 15: Ociosidade de 5 minutos (2 tentativas -> encerra -> reativa quando mandar nova mensagem)
    lid_jid = "268594420183281@lid"
    bot.handle_message(lid_jid, "#saudelab")

    with bot.get_db() as conn:
        conn.execute("UPDATE sessions SET last_activity_ts = ? WHERE phone = ?", (int(time.time()) - 305, lid_jid))
        conn.commit()
    out1 = bot.check_inactive_sessions()
    assert len(out1) == 1 and out1[0]["attempt"] == 1 and out1[0]["jid"] == lid_jid
    print("[OK] 12. 1ª tentativa de ociosidade após 5 minutos enviada para @lid.")

    with bot.get_db() as conn:
        conn.execute("UPDATE sessions SET last_activity_ts = ? WHERE phone = ?", (int(time.time()) - 305, lid_jid))
        conn.commit()
    out2 = bot.check_inactive_sessions()
    assert len(out2) == 1 and out2[0]["attempt"] == 2
    print("[OK] 13. 2ª tentativa de ociosidade após +5 minutos enviada.")

    with bot.get_db() as conn:
        conn.execute("UPDATE sessions SET last_activity_ts = ? WHERE phone = ?", (int(time.time()) - 305, lid_jid))
        conn.commit()
    out_close = bot.check_inactive_sessions()
    assert len(out_close) == 1 and out_close[0]["attempt"] == "closed"
    print("[OK] 14. Atendimento encerrado automaticamente após 2 tentativas sem resposta.")

    r_reactivate = bot.handle_message(lid_jid, "#saudelab")
    assert "1 - Agendamentos / Orçamentos" in r_reactivate
    print("[OK] 15. Reativação automática após encerramento por ociosidade funcionando.")

    # Limpa dados fictícios de teste mantendo banco limpo
    with bot.get_db() as conn:
        conn.execute("DELETE FROM sessions;")
        conn.execute("DELETE FROM triagens WHERE patient_name IN ('Giovanna Teste', 'Carlos Concurseiro');")
        conn.commit()

    print("============================================================")
    print(" TODOS OS 15 TESTES AUTOMATIZADOS PASSARAM COM 100% DE SUCESSO")
    print("============================================================")


if __name__ == "__main__":
    run_all_tests()
