import time
import bot


def run_all_tests() -> None:
    print("============================================================")
    print(" EXECUTANDO BATERIA COMPLETA DE TESTES — SAUDELAB v4.0.0")
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

    # 7: Cliente pedindo cotação/valor de exame direto no menu -> segue preenchimento
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
    print("[OK] 07. Fluxo de Cotação Direta + Rejeição de dado errado + Sucesso sem resumo na mensagem.")

    # 8 a 11: Ociosidade de 5 minutos (2 tentativas -> encerra -> reativa quando mandar nova mensagem)
    lid_jid = "268594420183281@lid"
    bot.handle_message(lid_jid, "#saudelab")

    with bot.get_db() as conn:
        conn.execute("UPDATE sessions SET last_activity_ts = ? WHERE phone = ?", (int(time.time()) - 305, lid_jid))
        conn.commit()
    out1 = bot.check_inactive_sessions()
    assert len(out1) == 1 and out1[0]["attempt"] == 1 and out1[0]["jid"] == lid_jid
    print("[OK] 08. 1ª tentativa de ociosidade após 5 minutos enviada para @lid.")

    with bot.get_db() as conn:
        conn.execute("UPDATE sessions SET last_activity_ts = ? WHERE phone = ?", (int(time.time()) - 305, lid_jid))
        conn.commit()
    out2 = bot.check_inactive_sessions()
    assert len(out2) == 1 and out2[0]["attempt"] == 2
    print("[OK] 09. 2ª tentativa de ociosidade após +5 minutos enviada.")

    with bot.get_db() as conn:
        conn.execute("UPDATE sessions SET last_activity_ts = ? WHERE phone = ?", (int(time.time()) - 305, lid_jid))
        conn.commit()
    out_close = bot.check_inactive_sessions()
    assert len(out_close) == 1 and out_close[0]["attempt"] == "closed"
    print("[OK] 10. Atendimento encerrado automaticamente após 2 tentativas sem resposta.")

    r_reactivate = bot.handle_message(lid_jid, "#saudelab")
    assert "1 - Exames na Unidade" in r_reactivate
    print("[OK] 11. Reativação automática após encerramento por ociosidade funcionando.")

    # 12: Fluxo Opção 4 (Falar sobre agendamento realizado)
    phone_ag = "5521988882222@s.whatsapp.net"
    bot.handle_message(phone_ag, "#saudelab")
    r_op4 = bot.handle_message(phone_ag, "4")
    assert "localizar o seu agendamento" in r_op4
    bot.handle_message(phone_ag, "Roberto Alves")
    r_ag_err = bot.handle_message(phone_ag, "111.222.333-44")
    assert "incorreto" in r_ag_err
    r_ag_ok = bot.handle_message(phone_ag, "529.982.247-25")
    assert "recepcionista localizar o seu agendamento" in r_ag_ok and "SOLICITAÇÃO SOBRE AGENDAMENTO" not in r_ag_ok
    print("[OK] 12. Fluxo Opção 4 (Agendamento Existente) validado sem bloco de resumo.")

    # 13: Regra de Áudio (pede texto no Menu/CPF, mas aceita nos exames)
    phone_aud = "5521977774444@s.whatsapp.net"
    bot.handle_message(phone_aud, "#saudelab")
    r_aud_menu = bot.handle_message(phone_aud, "", is_audio=True)
    assert "ainda não consigo ouvir áudios" in r_aud_menu
    bot.handle_message(phone_aud, "1")
    r_aud_exams = bot.handle_message(phone_aud, "", is_audio=True)
    assert "nome completo" in r_aud_exams
    r_aud_name = bot.handle_message(phone_aud, "", is_audio=True)
    assert "por texto" in r_aud_name
    print("[OK] 13. Tratamento inteligente de Áudio (Menu, Exames e Cadastro) validado.")

    # 14: Chamada não atendida inicia a triagem
    r_call = bot.handle_missed_call(phone_aud)
    assert "Vimos que você tentou nos ligar" in r_call
    print("[OK] 14. Chamada não atendida inicia a triagem automaticamente.")

    # Limpa dados fictícios de teste mantendo banco limpo
    with bot.get_db() as conn:
        conn.execute("DELETE FROM sessions;")
        conn.execute("DELETE FROM triagens WHERE patient_name IN ('Giovanna Teste', 'Roberto Alves');")
        conn.commit()

    print("============================================================")
    print(" TODOS OS 14 TESTES AUTOMATIZADOS PASSARAM COM 100% DE SUCESSO")
    print("============================================================")


if __name__ == "__main__":
    run_all_tests()
