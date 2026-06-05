"""
Bot DAS-SIMEI — lógica de automação
Pode ser chamado via CLI (main) ou pelo app web (executar)
"""

import base64
import os
import random
import re
import smtplib
import time
import urllib.request
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

try:
    from playwright_stealth import stealth_sync
except ImportError:
    try:
        from playwright_stealth import Stealth
        def stealth_sync(page):
            Stealth().apply_stealth_sync(page)
    except Exception:
        def stealth_sync(page):
            pass

load_dotenv()

URL_PGMEI = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app/Identificacao"

MESES_PT = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
            "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

# ── Callbacks globais (substituídos pelo app web) ─────────────────────────────
_log_func       = print
_pergunta_func  = None   # fn(dados_dict) → dict resposta  — bloqueia até responder

def set_log_func(func):       global _log_func;      _log_func = func
def set_pergunta_func(func):  global _pergunta_func;  _pergunta_func = func

def log(msg): _log_func(msg)

def perguntar(dados: dict) -> dict:
    """Envia uma pergunta para a UI e aguarda resposta (bloqueante)."""
    if _pergunta_func:
        return _pergunta_func(dados) or {}
    # CLI fallback: imprime e pede input
    log(f"\n❓ {dados.get('titulo','Pergunta')}")
    for m in dados.get("meses", []):
        log(f"   [{m['num']:02d}] {m['texto']} — {m['situacao']} — {m['total']}")
    resp = input("Deseja emitir DAS para algum mês? (s/n): ").strip().lower()
    if resp != "s":
        return {"emitir": False}
    selecionados = input("Informe os números dos meses separados por vírgula: ")
    nums = [int(x.strip()) for x in selecionados.split(",") if x.strip().isdigit()]
    return {"emitir": True, "meses": nums}


# ── Utilitários ───────────────────────────────────────────────────────────────

def limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)

def pasta_empresa(cnpj: str, pasta_base: Path) -> Path:
    pasta = pasta_base / limpar_cnpj(cnpj)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta

def vencimento_para_mes(mes: int, ano: int) -> str:
    """Calcula a data de vencimento para um mês/ano de competência específico."""
    # Vencimento = dia 20 do mês seguinte
    if mes == 12:
        venc = datetime(ano + 1, 1, 20)
    else:
        venc = datetime(ano, mes + 1, 20)
    if venc.weekday() == 5:   # sábado → sexta
        venc = venc.replace(day=venc.day - 1)
    elif venc.weekday() == 6: # domingo → sexta
        venc = venc.replace(day=venc.day - 2)
    return venc.strftime("%d/%m/%Y")

def espera_humana(minimo=0.8, maximo=2.5):
    time.sleep(random.uniform(minimo, maximo))

def digitar_como_humano(page, elemento, texto: str):
    elemento.click()
    espera_humana(0.2, 0.5)
    elemento.fill("")
    for char in texto:
        elemento.type(char, delay=random.randint(60, 180))
    espera_humana(0.2, 0.5)

def mover_mouse_aleatoriamente(page):
    for _ in range(random.randint(2, 4)):
        page.mouse.move(random.randint(100, 900), random.randint(100, 600))
        time.sleep(random.uniform(0.1, 0.3))

def screenshot_base64(page) -> str:
    """Tira screenshot da página e retorna como base64."""
    try:
        return base64.b64encode(page.screenshot()).decode()
    except Exception:
        return ""


# ── Detecção de elementos ─────────────────────────────────────────────────────

def encontrar_input_cnpj(page):
    for sel in [
        "input[id='cnpj']", "input[name='cnpj']",
        "input[id*='cnpj' i]", "input[name*='cnpj' i]",
        "input[placeholder*='CNPJ' i]",
        "input[maxlength='14']", "input[maxlength='18']",
        "input[type='text']:visible",
    ]:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                el.wait_for(state="visible", timeout=3000)
                return el
        except Exception:
            continue
    return None

def encontrar_botao(page, textos: list):
    for texto in textos:
        for sel in [
            f"button:has-text('{texto}')",
            f"input[value='{texto}']",
            f"input[value*='{texto}']",
            f"a:has-text('{texto}')",
        ]:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.wait_for(state="visible", timeout=3000)
                    return el
            except Exception:
                continue
    return None

def verificar_e_resolver_captcha(page):
    try:
        if page.locator("iframe[src*='hcaptcha'], div.h-captcha, [data-sitekey]").count() > 0:
            log("  ⏳ Captcha invisível detectado, aguardando validação automática...")
            espera_humana(3, 5)
    except Exception:
        pass

def diagnosticar_pagina(page, etapa: str):
    try:
        path = Path(f"debug_{etapa}_{int(time.time())}.png")
        page.screenshot(path=str(path))
        log(f"  📸 Screenshot salvo: {path}")
    except Exception:
        pass


# ── Leitura da tabela de DAS ──────────────────────────────────────────────────

def ler_tabela_das(page) -> list[dict]:
    """
    Lê todas as linhas da tabela de períodos de apuração.
    Retorna lista de dicts: {num, texto, situacao, principal, total, vencimento, atrasado}
    """
    meses = []
    try:
        linhas = page.locator("tbody tr").all()
        for linha in linhas:
            cels = linha.locator("td").all()
            if len(cels) < 3:
                continue
            try:
                # Coluna 0: checkbox + texto do mês
                texto_periodo = cels[0].inner_text().strip()
                # Extrai "Janeiro/2026" do texto
                match = re.search(r"(\w+)/(\d{4})", texto_periodo)
                if not match:
                    continue
                nome_mes_txt = match.group(1)
                ano_txt      = int(match.group(2))
                if nome_mes_txt not in MESES_PT:
                    continue
                num_mes = MESES_PT.index(nome_mes_txt) + 1

                # Situação (procura em todas as células)
                situacao  = ""
                principal = ""
                total     = ""
                vencimento = ""
                for cel in cels:
                    t = cel.inner_text().strip()
                    if t in ("Devedor", "A Vencer", "Pago", "Em Aberto"):
                        situacao = t
                    elif re.match(r"R\$\s*[\d.,]+", t) and not principal:
                        principal = t
                    elif re.match(r"R\$\s*[\d.,]+", t):
                        total = t
                    elif re.match(r"\d{2}/\d{2}/\d{4}", t) and not vencimento:
                        vencimento = t

                atrasado = situacao in ("Devedor", "Em Aberto")

                meses.append({
                    "num":       num_mes,
                    "ano":       ano_txt,
                    "texto":     f"{nome_mes_txt}/{ano_txt}",
                    "situacao":  situacao or "—",
                    "principal": principal,
                    "total":     total or principal,
                    "vencimento": vencimento,
                    "atrasado":  atrasado,
                })
            except Exception:
                continue
    except Exception as e:
        log(f"  ! Erro ao ler tabela: {e}")
    return meses


# ── Navegação até a tabela de DAS ─────────────────────────────────────────────

def navegar_ate_tabela(page, cnpj: str, ano: int) -> bool:
    """
    Acessa o portal, preenche CNPJ, navega até a tabela de períodos.
    Retorna True se chegou na tabela com sucesso.
    """
    cnpj_limpo = limpar_cnpj(cnpj)

    # ETAPA 1 — Carregar portal
    try:
        page.goto(URL_PGMEI, wait_until="domcontentloaded", timeout=30000)
        espera_humana(2, 4)
    except PlaywrightTimeout:
        log("  ✗ Timeout ao carregar o portal.")
        return False

    mover_mouse_aleatoriamente(page)
    verificar_e_resolver_captcha(page)

    # ETAPA 2 — Preencher CNPJ
    campo_cnpj = encontrar_input_cnpj(page)
    if not campo_cnpj:
        log("  ✗ Campo CNPJ não encontrado.")
        diagnosticar_pagina(page, "sem_campo_cnpj")
        return False

    digitar_como_humano(page, campo_cnpj, cnpj_limpo)
    mover_mouse_aleatoriamente(page)

    btn = encontrar_botao(page, ["Continuar", "Consultar", "Avançar"])
    if not btn:
        log("  ✗ Botão Continuar não encontrado.")
        return False

    espera_humana(0.5, 1.5)
    btn.click()
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    espera_humana(2, 3)
    verificar_e_resolver_captcha(page)

    # ETAPA 3 — Clicar em Emitir DAS
    btn_das = encontrar_botao(page, ["Emitir DAS", "Gerar DAS", "DAS-SIMEI", "Emitir Guia"])
    if not btn_das:
        log("  ✗ Link Emitir DAS não encontrado.")
        return False

    espera_humana(0.5, 1.0)
    btn_das.click()
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    espera_humana(2, 3)

    # ETAPA 4 — Selecionar Ano-Calendário + OK
    log(f"  → Selecionando ano-calendário: {ano}")
    try:
        selecionou = False
        for sel in ["select[id*='ano' i]", "select[name*='ano' i]", "select[id*='year' i]"]:
            el = page.locator(sel).first
            if el.count() > 0:
                el.wait_for(state="visible", timeout=5000)
                el.select_option(value=str(ano))
                espera_humana(0.8, 1.5)
                selecionou = True
                break
        if not selecionou:
            diagnosticar_pagina(page, "sem_seletor_ano")
            return False

        espera_humana(0.5, 1.0)
        btn_ok = encontrar_botao(page, ["Ok", "OK", "Confirmar", "Continuar"])
        if btn_ok:
            btn_ok.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            espera_humana(2, 3)
            log(f"  ✓ Ano {ano} selecionado.")
        else:
            log("  ! Botão OK não encontrado.")
            return False
    except Exception as e:
        log(f"  ! Erro ao selecionar ano: {e}")
        return False

    return True


# ── Emissão de um mês específico ──────────────────────────────────────────────

def emitir_mes(page, cnpj: str, mes: int, ano: int, pasta: Path) -> Path | None:
    """
    Marca o checkbox do mês, preenche data, gera e baixa o DAS.
    Pressupõe que a página já está na tabela de períodos.
    """
    cnpj_limpo   = limpar_cnpj(cnpj)
    nome_mes     = MESES_PT[mes - 1]
    texto_mes    = f"{nome_mes}/{ano}"
    data_venc    = vencimento_para_mes(mes, ano)
    nome_arquivo = f"DAS_{cnpj_limpo}_{ano}{mes:02d}.pdf"
    caminho      = pasta / nome_arquivo

    log(f"  → Emitindo {texto_mes} | Vencimento: {data_venc}")

    # Garante que nenhum checkbox esteja marcado antes
    try:
        for cb in page.locator("input[type='checkbox']:checked").all():
            cb.uncheck()
        espera_humana(0.3, 0.6)
    except Exception:
        pass

    # Marca checkbox do mês
    try:
        linha = page.locator(f"tr:has-text('{texto_mes}')").first
        linha.wait_for(state="visible", timeout=10000)
        checkbox = linha.locator("input[type='checkbox']").first
        if not checkbox.is_checked():
            checkbox.check()
        espera_humana(0.5, 1.0)

        # Lê vencimento da própria linha se disponível
        for cel in linha.locator("td").all():
            t = cel.inner_text().strip()
            if re.match(r"\d{2}/\d{2}/\d{4}", t):
                data_venc = t
                break
        log(f"  ✓ Checkbox de '{texto_mes}' marcado. Vencimento: {data_venc}")
    except Exception as e:
        log(f"  ! Erro ao marcar checkbox: {e}")
        return None

    # Preenche data de pagamento
    try:
        campo_data = page.locator(
            "input[id*='dtPagamento' i], input[id*='dataPagamento' i], "
            "input[id*='acolhimento' i], input[id*='pagamento' i]"
        ).first
        if campo_data.count() == 0:
            campo_data = page.locator("input[type='text']:visible").last
        campo_data.wait_for(state="visible", timeout=5000)
        campo_data.triple_click()
        espera_humana(0.2, 0.4)
        digitar_como_humano(page, campo_data, data_venc)
    except Exception as e:
        log(f"  ! Erro ao preencher data: {e}")

    # Clica em Gerar DAS
    btn_gerar = encontrar_botao(page, ["Gerar DAS","Apurar/Gerar DAS","Apurar","Gerar","Emitir DAS","Emitir"])
    if not btn_gerar:
        try:
            for btn in page.locator("input[type='button']:visible, input[type='submit']:visible, button:visible").all():
                txt = (btn.get_attribute("value") or btn.inner_text() or "").strip()
                if txt and "Atualizar" not in txt and "Pagar" not in txt and "Online" not in txt:
                    btn_gerar = btn
                    break
        except Exception:
            pass
    if not btn_gerar:
        log("  ✗ Botão Gerar DAS não encontrado.")
        return None

    espera_humana(0.5, 1.0)
    btn_gerar.click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    espera_humana(2, 3)

    # Clica em Imprimir/Visualizar PDF
    btn_pdf = encontrar_botao(page, [
        "Imprimir/Visualizar PDF","Imprimir / Visualizar PDF",
        "Visualizar PDF","Imprimir PDF","Imprimir","PDF"
    ])
    if not btn_pdf:
        log("  ✗ Botão PDF não encontrado.")
        diagnosticar_pagina(page, "sem_botao_pdf")
        return None

    # Tenta download direto
    try:
        with page.expect_download(timeout=30000) as dl_info:
            btn_pdf.click()
        dl_info.value.save_as(str(caminho))
        log(f"  ✓ PDF salvo: {caminho.name}")
        return caminho
    except Exception:
        pass

    # Fallback: nova aba com PDF
    try:
        espera_humana(2, 3)
        paginas = page.context.pages
        aba_pdf = paginas[-1] if len(paginas) > 1 else page
        url_pdf = aba_pdf.url
        if "pdf" in url_pdf.lower():
            cookies   = page.context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            req = urllib.request.Request(url_pdf, headers={
                "Cookie": cookie_str,
                "User-Agent": page.evaluate("navigator.userAgent"),
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                caminho.write_bytes(resp.read())
        else:
            aba_pdf.pdf(path=str(caminho))
        log(f"  ✓ PDF salvo: {caminho.name}")
        if len(paginas) > 1:
            aba_pdf.close()
        return caminho
    except Exception as e:
        log(f"  ✗ Erro ao salvar PDF: {e}")
        return None


# ── Envio de email ────────────────────────────────────────────────────────────

def enviar_email(destinatario: str, nome_empresa: str, cnpj: str,
                 arquivo: Path, competencia: str = None):
    remetente = os.getenv("EMAIL_REMETENTE")
    senha     = os.getenv("EMAIL_SENHA_APP")
    if not remetente or not senha:
        log("  ✗ Credenciais de email não configuradas no .env")
        return

    if not competencia:
        hoje = datetime.now()
        competencia = f"12/{hoje.year-1}" if hoje.month == 1 else f"{hoje.month-1:02d}/{hoje.year}"

    assunto = f"DAS-SIMEI {competencia} – {nome_empresa}"
    msg = MIMEMultipart("related")
    msg["From"]    = remetente
    msg["To"]      = destinatario
    msg["Subject"] = assunto

    alternativa = MIMEMultipart("alternative")
    msg.attach(alternativa)

    corpo_texto = (
        f"Olá,\n\nSegue em anexo o DAS-SIMEI referente à competência {competencia} "
        f"da empresa {nome_empresa} (CNPJ: {cnpj}).\n\nAtenciosamente,\nTesserato Contabilidade"
    )
    alternativa.attach(MIMEText(corpo_texto, "plain", "utf-8"))

    assinatura_path = Path(__file__).parent / "assinatura.png"
    tem_assinatura  = assinatura_path.exists()
    img_tag = '<img src="cid:assinatura" alt="Assinatura" style="max-width:580px;display:block;">' if tem_assinatura else ""

    corpo_html = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#333;margin:0;padding:20px;">
      <p>Olá,</p>
      <p>Segue em anexo o <strong>DAS-SIMEI</strong> referente à competência
         <strong>{competencia}</strong> da empresa <strong>{nome_empresa}</strong>
         (CNPJ: {cnpj}).</p>
      <br><p>Atenciosamente,</p>{img_tag}
    </body></html>"""
    alternativa.attach(MIMEText(corpo_html, "html", "utf-8"))

    if tem_assinatura:
        with open(assinatura_path, "rb") as f:
            img = MIMEBase("image", "png")
            img.set_payload(f.read())
        encoders.encode_base64(img)
        img.add_header("Content-ID", "<assinatura>")
        img.add_header("Content-Disposition", "inline", filename="assinatura.png")
        msg.attach(img)

    with open(arquivo, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{arquivo.name}"')
    msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(remetente, senha)
            s.sendmail(remetente, destinatario, msg.as_string())
        log(f"  ✓ Email enviado para {destinatario}")
    except Exception as e:
        log(f"  ✗ Falha ao enviar email: {e}")


# ── Execução principal ────────────────────────────────────────────────────────

def executar(empresas: list, pasta_downloads: Path,
             log_callback=None, parar_flag=None, pergunta_callback=None):
    if log_callback:    set_log_func(log_callback)
    if pergunta_callback: set_pergunta_func(pergunta_callback)

    pasta_downloads = Path(pasta_downloads)
    pasta_downloads.mkdir(parents=True, exist_ok=True)

    hoje = datetime.now()
    mes_padrao = 12 if hoje.month == 1 else hoje.month - 1
    ano_padrao = hoje.year - 1 if hoje.month == 1 else hoje.year

    log(f"{'='*60}")
    log(f"Bot DAS-SIMEI | Competência padrão: {mes_padrao:02d}/{ano_padrao}")
    log(f"Processando {len(empresas)} empresa(s)...")
    log(f"{'='*60}")

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=False)
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": random.randint(1280, 1920), "height": random.randint(800, 1080)},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR','pt','en-US'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
        """)

        for i, empresa in enumerate(empresas, 1):
            if parar_flag and parar_flag[0]:
                log("⛔ Processo interrompido pelo usuário.")
                break

            cnpj  = empresa.get("cnpj", "")
            nome  = empresa.get("nome", cnpj)
            email = empresa.get("email") or os.getenv("EMAIL_DESTINATARIO", "")

            log(f"\n[{i}/{len(empresas)}] {nome} — CNPJ: {cnpj}")

            try:
                pasta = pasta_empresa(cnpj, pasta_downloads)

                # Navega até a tabela
                ok = navegar_ate_tabela(page, cnpj, ano_padrao)
                if not ok:
                    log(f"  ✗ Não foi possível acessar a tabela para {cnpj}.")
                    continue

                # Lê todos os meses da tabela
                meses_tabela = ler_tabela_das(page)
                atrasados    = [m for m in meses_tabela if m["atrasado"]]

                # Tira screenshot da tabela
                log("  📸 Capturando tabela de períodos...")
                img_b64 = screenshot_base64(page)

                # Se há meses atrasados, pergunta ao usuário
                meses_extras = []
                if atrasados:
                    log(f"  ⚠️  {len(atrasados)} mês(es) com boleto(s) em aberto/atraso encontrado(s)!")
                    for m in atrasados:
                        log(f"     • {m['texto']} — {m['situacao']} — {m['total']}")

                    resposta = perguntar({
                        "tipo":      "boletos_abertos",
                        "empresa":   nome,
                        "cnpj":      cnpj,
                        "screenshot": img_b64,
                        "meses":     atrasados,
                    })

                    if resposta.get("emitir"):
                        nums_selecionados = resposta.get("meses", [])
                        meses_extras = [
                            m for m in atrasados
                            if m["num"] in nums_selecionados
                        ]
                        log(f"  ✓ Usuário selecionou {len(meses_extras)} mês(es) para emissão.")
                    else:
                        log("  → Usuário optou por não emitir meses em atraso.")
                else:
                    log("  ✓ Nenhum boleto em atraso encontrado.")

                # Lista final de meses a emitir: selecionados pelo usuário + mês padrão
                meses_emitir = list(meses_extras)
                # Adiciona mês padrão se não estiver na lista
                ja_tem_padrao = any(m["num"] == mes_padrao and m["ano"] == ano_padrao for m in meses_emitir)
                if not ja_tem_padrao:
                    meses_emitir.append({"num": mes_padrao, "ano": ano_padrao,
                                         "texto": f"{MESES_PT[mes_padrao-1]}/{ano_padrao}"})

                # Emite cada mês selecionado
                for idx_mes, mes_info in enumerate(meses_emitir):
                    if parar_flag and parar_flag[0]:
                        break

                    mes_num = mes_info["num"]
                    mes_ano = mes_info["ano"]
                    competencia_str = f"{mes_num:02d}/{mes_ano}"

                    log(f"\n  📄 Emitindo {mes_info['texto']}...")

                    # Se não é o primeiro mês, precisa voltar à tabela
                    if idx_mes > 0:
                        log("  → Voltando à tabela para próximo mês...")
                        ok = navegar_ate_tabela(page, cnpj, mes_ano)
                        if not ok:
                            log(f"  ✗ Falha ao navegar de volta para {mes_info['texto']}.")
                            continue

                    arquivo = emitir_mes(page, cnpj, mes_num, mes_ano, pasta)

                    if arquivo and arquivo.exists():
                        log(f"  ✓ DAS {mes_info['texto']} gerado com sucesso.")
                        if email:
                            enviar_email(email, nome, cnpj, arquivo, competencia_str)
                    else:
                        log(f"  ✗ Falha ao gerar DAS de {mes_info['texto']}.")

            except Exception as e:
                log(f"  ✗ Erro inesperado: {e}")

            if i < len(empresas):
                espera_humana(2, 4)

        browser.close()

    log(f"\n{'='*60}")
    log(f"✅ Concluído! Arquivos em: {pasta_downloads.resolve()}")
    log(f"{'='*60}")


if __name__ == "__main__":
    import json
    p = Path("empresas.json")
    if p.exists():
        executar(json.loads(p.read_text(encoding="utf-8")), Path("DAS"))
    else:
        print("empresas.json não encontrado.")
